"""Tests for per-WhatsApp-number conversation session isolation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.qualification.conversation_state import (
    append_conversation_turn,
    clear_conversations,
    get_accepted_fields,
    get_conversation_history,
    save_accepted_fields,
)
from apps.qualification.domain.menu_picker_pending import mark_menu_pending
from apps.qualification.domain.validators import normalize_whatsapp_session_number
from apps.qualification.message_idempotency import (
    begin_idempotent_turn,
    cache_turn_response,
    clear_message_sid_cache,
)
from apps.qualification.models import WhatsAppConversationSession
from apps.qualification.services.booking_link_delivery_service import (
    deliver_booking_link_whatsapp_text,
)
from apps.qualification.services.conversation_restart_service import (
    restart_qualification_conversation,
)
from apps.qualification.services.conversation_session_service import (
    FRESH_SESSION_DEFAULTS,
    get_or_create_conversation_session,
    mark_booking_link_sent,
    mark_session_human_handoff_requested,
)
from apps.qualification.services.extract_service import ExtractService
from apps.qualification.services.language_gate_service import LanguageGateResult
from apps.qualification.tests.internal_api_test_helpers import OPENROUTER_FALLBACK_MESSAGE

pytestmark = pytest.mark.django_db

USER_A = "+923001234567"
USER_B = "+923009876543"
USER_A_SPACED = "+92 300 1234567"
USER_A_WHATSAPP_PREFIX = "whatsapp:+923001234567"
BOOKING_LINK = "https://booking.example.com/test-schedule"
USER_A_MESSAGE_SID = "SM0cc5a1d9e22bf9850ca24261ee23ce90"
USER_B_MESSAGE_SID = "SM0cc5a1d9e22bf9850ca24261ee23ce91"
VOICE_MEDIA_URL = "https://api.twilio.com/2010-04-01/Accounts/ACtest/Media/MEtestvoice001"

IN_PROGRESS_FIELDS = {
    "project_type": "new_website",
    "requirements": "A restaurant website with online ordering",
    "referral_source": "Google",
    "whatsapp_confirmed": True,
    "preferred_phone": USER_A,
}


@pytest.fixture(autouse=True)
def _reset_state():
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()
    yield
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()


def test_fresh_session_defaults_are_isolated():
    session, created = get_or_create_conversation_session(whatsapp_number=USER_A)

    assert created is True
    assert session.language is None
    assert session.menu_pending is False
    assert session.menu_pending_until is None
    assert session.booking_link_sent_at is None
    assert session.human_handoff_requested_at is None
    assert session.last_message_at is None


def test_get_or_create_reuses_session_for_equivalent_number_formats():
    first, created_first = get_or_create_conversation_session(whatsapp_number=USER_A_SPACED)
    second, created_second = get_or_create_conversation_session(
        whatsapp_number=USER_A_WHATSAPP_PREFIX,
    )

    assert created_first is True
    assert created_second is False
    assert first.pk == second.pk
    assert first.whatsapp_number == USER_A
    assert normalize_whatsapp_session_number(USER_A_SPACED) == USER_A


def test_two_numbers_have_independent_session_flags():
    session_a, _ = get_or_create_conversation_session(whatsapp_number=USER_A)
    session_b, _ = get_or_create_conversation_session(whatsapp_number=USER_B)

    mark_menu_pending(session=session_a)
    mark_booking_link_sent(session_a)
    mark_session_human_handoff_requested(session_a)

    session_a.refresh_from_db()
    session_b.refresh_from_db()

    assert session_a.menu_pending is True
    assert session_a.booking_link_sent_at is not None
    assert session_a.human_handoff_requested_at is not None

    assert session_b.menu_pending is False
    assert session_b.booking_link_sent_at is None
    assert session_b.human_handoff_requested_at is None


def test_two_numbers_have_independent_qualification_state():
    save_accepted_fields(USER_A, {"project_type": "new_website"})
    save_accepted_fields(USER_B, {"project_type": "website_upgrade"})

    assert get_accepted_fields(USER_A)["project_type"] == "new_website"
    assert get_accepted_fields(USER_B)["project_type"] == "website_upgrade"


def test_restart_clears_one_customer_without_affecting_another():
    session_a, _ = get_or_create_conversation_session(whatsapp_number=USER_A)
    session_b, _ = get_or_create_conversation_session(whatsapp_number=USER_B)

    save_accepted_fields(USER_A, {"project_type": "new_website"})
    save_accepted_fields(USER_B, {"project_type": "website_upgrade"})
    mark_menu_pending(session=session_a)
    mark_session_human_handoff_requested(session_a)

    restart_qualification_conversation(whatsapp_number=USER_A, session=session_a)

    session_a.refresh_from_db()
    session_b.refresh_from_db()

    assert get_accepted_fields(USER_A) == {}
    assert get_accepted_fields(USER_B)["project_type"] == "website_upgrade"
    assert session_a.menu_pending is False
    assert session_a.human_handoff_requested_at is None
    assert session_b.menu_pending is False


@pytest.mark.language_gate
def test_extract_service_creates_session_for_new_number_on_first_turn():
    service = ExtractService()
    gate_response = LanguageGateResult(
        handled=True,
        response_payload={
            "status": "awaiting_language_selection",
            "message": "Language selector sent.",
        },
    )

    assert not WhatsAppConversationSession.objects.filter(whatsapp_number=USER_B).exists()

    with patch.object(service._language_gate_service, "evaluate_turn", return_value=gate_response):
        service.run_turn(
            {
                "whatsapp_number": USER_B,
                "message": "Hello",
                "input_channel": "whatsapp_text",
                "message_sid": None,
                "media_url": None,
                "media_content_type": None,
            }
        )

    session = WhatsAppConversationSession.objects.get(whatsapp_number=USER_B)
    assert session.language is None
    assert session.menu_pending is False
    assert session.booking_link_sent_at is None
    assert session.last_message_at is not None


@pytest.mark.language_gate
def test_extract_service_normalizes_number_before_session_lookup():
    service = ExtractService()
    gate_response = LanguageGateResult(
        handled=True,
        response_payload={
            "status": "awaiting_language_selection",
            "message": "Language selector sent.",
        },
    )

    with patch.object(service._language_gate_service, "evaluate_turn", return_value=gate_response):
        service.run_turn(
            {
                "whatsapp_number": USER_A_SPACED,
                "message": "Hello",
                "input_channel": "whatsapp_text",
                "message_sid": None,
                "media_url": None,
                "media_content_type": None,
            }
        )

    assert WhatsAppConversationSession.objects.count() == 1
    assert WhatsAppConversationSession.objects.filter(whatsapp_number=USER_A).exists()


def test_fresh_session_defaults_constant_matches_model_defaults():
    session, _ = get_or_create_conversation_session(whatsapp_number=USER_A)

    for field_name, expected_value in FRESH_SESSION_DEFAULTS.items():
        assert getattr(session, field_name) == expected_value


def test_existing_session_last_message_at_is_scoped_per_number():
    session_a, _ = get_or_create_conversation_session(whatsapp_number=USER_A)
    session_b, _ = get_or_create_conversation_session(whatsapp_number=USER_B)
    now = timezone.now()

    session_a.last_message_at = now
    session_a.save(update_fields=["last_message_at"])

    session_a.refresh_from_db()
    session_b.refresh_from_db()

    assert session_a.last_message_at == now
    assert session_b.last_message_at is None


def test_persistence_normalizes_number_formats_for_shared_state():
    save_accepted_fields(USER_A_SPACED, {"project_type": "new_website"})
    append_conversation_turn(
        USER_A_WHATSAPP_PREFIX,
        user_message="text hello",
        assistant_reply="text reply",
    )

    assert get_accepted_fields(USER_A)["project_type"] == "new_website"
    history = get_conversation_history(USER_A)
    assert history == [
        {"role": "user", "content": "text hello"},
        {"role": "assistant", "content": "text reply"},
    ]


def test_conversation_history_is_scoped_per_number():
    append_conversation_turn(
        USER_A,
        user_message="User A message",
        assistant_reply="Reply to A",
    )
    append_conversation_turn(
        USER_B,
        user_message="User B message",
        assistant_reply="Reply to B",
    )

    assert get_conversation_history(USER_A) == [
        {"role": "user", "content": "User A message"},
        {"role": "assistant", "content": "Reply to A"},
    ]
    assert get_conversation_history(USER_B) == [
        {"role": "user", "content": "User B message"},
        {"role": "assistant", "content": "Reply to B"},
    ]


def test_booking_link_delivery_is_scoped_per_number():
    session_a, _ = get_or_create_conversation_session(whatsapp_number=USER_A)
    session_b, _ = get_or_create_conversation_session(whatsapp_number=USER_B)
    sender = MagicMock(side_effect=["SMbookingA00000000000000001", "SMbookingB00000000000000001"])

    assert deliver_booking_link_whatsapp_text(
        whatsapp_number=USER_A,
        language="en",
        booking_link=BOOKING_LINK,
        message_sid=USER_A_MESSAGE_SID,
        input_channel="whatsapp_text",
        sender=sender,
    )
    assert deliver_booking_link_whatsapp_text(
        whatsapp_number=USER_B,
        language="en",
        booking_link=BOOKING_LINK,
        message_sid=USER_B_MESSAGE_SID,
        input_channel="whatsapp_text",
        sender=sender,
    )

    session_a.refresh_from_db()
    session_b.refresh_from_db()
    assert session_a.booking_link_sent_at is not None
    assert session_b.booking_link_sent_at is not None
    assert sender.call_count == 2
    assert sender.call_args_list[0].kwargs["to_number"] == USER_A
    assert sender.call_args_list[1].kwargs["to_number"] == USER_B


@pytest.mark.language_gate
def test_existing_user_continues_while_new_user_starts_fresh():
    save_accepted_fields(USER_A, IN_PROGRESS_FIELDS)
    session_a, _ = get_or_create_conversation_session(whatsapp_number=USER_A)
    session_a.language = "en"
    session_a.save(update_fields=["language"])

    service = ExtractService()
    gate_response = LanguageGateResult(
        handled=True,
        response_payload={
            "status": "awaiting_language_selection",
            "message": "Language selector sent.",
        },
    )

    with patch.object(service._language_gate_service, "evaluate_turn", return_value=gate_response):
        service.run_turn(
            {
                "whatsapp_number": USER_B,
                "message": "Hello",
                "input_channel": "whatsapp_text",
                "message_sid": USER_B_MESSAGE_SID,
                "media_url": None,
                "media_content_type": None,
            }
        )

    assert get_accepted_fields(USER_A) == IN_PROGRESS_FIELDS
    assert get_accepted_fields(USER_B) == {}
    assert WhatsAppConversationSession.objects.filter(whatsapp_number=USER_B).exists()


@pytest.mark.language_gate
@patch("apps.qualification.services.extract_service.run_qualification_turn")
def test_voice_and_text_inputs_share_session_for_same_number(mock_turn_handler):
    mock_turn_handler.return_value = {
        "accepted_fields": {"project_type": "new_website"},
        "rejected_fields": {},
        "human_handoff_requested": False,
        "next_field": "requirements",
        "reply_text": "Tell me more.",
        "qualification_status": "in_progress",
        "preferred_phone": None,
    }
    transcription_service = MagicMock()
    transcription_service.transcribe.return_value = "I need a bakery website"
    service = ExtractService(transcription_service=transcription_service)
    session_a, _ = get_or_create_conversation_session(whatsapp_number=USER_A)
    session_a.language = "en"
    session_a.save(update_fields=["language"])

    text_payload = {
        "whatsapp_number": USER_A_SPACED,
        "message": OPENROUTER_FALLBACK_MESSAGE,
        "input_channel": "whatsapp_text",
        "message_sid": USER_A_MESSAGE_SID,
        "media_url": None,
        "media_content_type": None,
        "call_sid": None,
        "utterance_id": None,
        "is_final": True,
    }
    voice_payload = {
        "whatsapp_number": USER_A_WHATSAPP_PREFIX,
        "message": None,
        "input_channel": "whatsapp_voice_note",
        "message_sid": "SM0cc5a1d9e22bf9850ca24261ee23ce92",
        "media_url": VOICE_MEDIA_URL,
        "media_content_type": "audio/ogg",
    }

    service.run_turn(text_payload)
    service.run_turn(voice_payload)

    assert WhatsAppConversationSession.objects.count() == 1
    assert mock_turn_handler.call_count == 2
    assert mock_turn_handler.call_args_list[0].kwargs["whatsapp_number"] == USER_A
    assert mock_turn_handler.call_args_list[1].kwargs == {
        "whatsapp_number": USER_A,
        "message": "I need a bakery website",
        "message_sid": voice_payload["message_sid"],
        "for_voice": True,
    }
    transcription_service.transcribe.assert_called_once()


def test_message_sid_idempotency_cache_is_per_message_not_per_number_state():
    user_a_payload = {"reply_text": "Reply for A", "qualification_status": "in_progress"}
    cache_turn_response(USER_A_MESSAGE_SID, user_a_payload)

    assert begin_idempotent_turn(USER_A_MESSAGE_SID) == user_a_payload
    assert begin_idempotent_turn(USER_B_MESSAGE_SID) is None
    assert get_accepted_fields(USER_A) == {}
    assert get_accepted_fields(USER_B) == {}
