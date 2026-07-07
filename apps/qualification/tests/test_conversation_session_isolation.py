"""Tests for per-WhatsApp-number conversation session isolation."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.qualification.conversation_state import (
    clear_conversations,
    get_accepted_fields,
    save_accepted_fields,
)
from apps.qualification.domain.menu_picker_pending import mark_menu_pending
from apps.qualification.domain.validators import normalize_whatsapp_session_number
from apps.qualification.models import WhatsAppConversationSession
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

pytestmark = pytest.mark.django_db

USER_A = "+923001234567"
USER_B = "+923009876543"
USER_A_SPACED = "+92 300 1234567"
USER_A_WHATSAPP_PREFIX = "whatsapp:+923001234567"


@pytest.fixture(autouse=True)
def _reset_state():
    clear_conversations()
    WhatsAppConversationSession.objects.all().delete()
    yield
    clear_conversations()
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
