"""Tests for WhatsApp booking-link text delivery."""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from apps.qualification.conversation_state import clear_conversations, save_accepted_fields
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.message_idempotency import cache_turn_response, clear_message_sid_cache
from apps.qualification.models import QualificationFieldFilterResult, WhatsAppConversationSession
from apps.qualification.services.booking_link_delivery_service import deliver_booking_link_whatsapp_text
from apps.qualification.tests.internal_api_test_helpers import (
    API_SECRET,
    MOCK_VOICE_AUDIO_DOWNLOAD,
    internal_api_auth_headers,
)

pytestmark = pytest.mark.django_db

BOOKING_LINK = "https://booking.example.com/test-schedule"
ENDPOINT_PATH = "/api/internal/qualification/extract/"
WHATSAPP_NUMBER = "+923001234567"
MEDIA_URL = "https://api.twilio.com/2010-04-01/Accounts/ACtest/Media/MEtestvoice001"
TEXT_COMPLETION_WITH_LINK = get_customer_message(
    language="en",
    key="completion_with_booking_link",
    booking_link=BOOKING_LINK,
)
VOICE_COMPLETION_SPOKEN = get_customer_message(
    language="en",
    key="completion_spoken",
)
VOICE_COMPLETION_WHATSAPP = get_customer_message(
    language="en",
    key="completion_whatsapp_booking_link",
    booking_link=BOOKING_LINK,
)

COMPLETED_FIELDS = {
    "project_type": "new_website",
    "requirements": "I need a new website for my restaurant",
    "referral_source": "Facebook",
    "whatsapp_confirmed": True,
    "preferred_phone": WHATSAPP_NUMBER,
}


def _seed_completed_qualification() -> None:
    """Leave qualification complete so delivery idempotency is not cleared as stale."""
    save_accepted_fields(WHATSAPP_NUMBER, COMPLETED_FIELDS)


def _filter_result(*, accepted_fields: dict[str, object]) -> QualificationFieldFilterResult:
    return QualificationFieldFilterResult(
        accepted_fields=accepted_fields,
        rejected_fields=(),
        human_handoff_requested=False,
    )


def _post_turn(
    client: Client,
    *,
    message: str | None = None,
    input_channel: str = "whatsapp_text",
    message_sid: str,
    media_url: str | None = None,
):
    payload: dict[str, object] = {
        "whatsapp_number": WHATSAPP_NUMBER,
        "input_channel": input_channel,
        "message_sid": message_sid,
        "media_url": media_url,
        "media_content_type": "audio/ogg" if media_url else None,
    }
    if message is not None:
        payload["message"] = message
    return client.post(
        ENDPOINT_PATH,
        data=json.dumps(payload),
        content_type="application/json",
        **internal_api_auth_headers(secret=API_SECRET),
    )


@pytest.fixture(autouse=True)
def _reset_state():
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()
    yield
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()


def test_deliver_booking_link_whatsapp_text_marks_session_once():
    _seed_completed_qualification()
    session = WhatsAppConversationSession.objects.create(
        whatsapp_number=WHATSAPP_NUMBER,
        language="en",
    )
    sender = MagicMock(return_value="SMbookinglink0000000000000001")

    first = deliver_booking_link_whatsapp_text(
        whatsapp_number=WHATSAPP_NUMBER,
        language="en",
        booking_link=BOOKING_LINK,
        message_sid="SM0cc5a1d9e22bf9850ca24261ee23ceb1",
        input_channel="whatsapp_text",
        sender=sender,
    )
    second = deliver_booking_link_whatsapp_text(
        whatsapp_number=WHATSAPP_NUMBER,
        language="en",
        booking_link=BOOKING_LINK,
        message_sid="SM0cc5a1d9e22bf9850ca24261ee23ceb2",
        input_channel="whatsapp_text",
        sender=sender,
    )

    assert first is True
    assert second is True
    send_calls = [call for call in sender.call_args_list if "to_number" in call.kwargs]
    assert len(send_calls) == 1
    session.refresh_from_db()
    assert session.booking_link_sent_at is not None


def test_deliver_booking_link_whatsapp_text_logs_delivery_event(caplog):
    _seed_completed_qualification()
    sender = MagicMock(return_value="SMbookinglink0000000000000001")

    with caplog.at_level(logging.INFO, logger="apps.qualification"):
        deliver_booking_link_whatsapp_text(
            whatsapp_number=WHATSAPP_NUMBER,
            language="en",
            booking_link=BOOKING_LINK,
            message_sid="SM0cc5a1d9e22bf9850ca24261ee23ceb1",
            input_channel="whatsapp_text",
            sender=sender,
        )

    delivered = [
        json.loads(record.message)
        for record in caplog.records
        if record.message.startswith("{")
        and json.loads(record.message).get("event") == "booking_link_whatsapp_text_delivered"
    ]

    assert len(delivered) == 1
    assert delivered[0]["delivery"] == "whatsapp_text"
    assert delivered[0]["input_channel"] == "whatsapp_text"


def test_deliver_booking_link_whatsapp_text_logs_duplicate_suppression(caplog):
    _seed_completed_qualification()
    WhatsAppConversationSession.objects.create(
        whatsapp_number=WHATSAPP_NUMBER,
        language="en",
        booking_link_sent_at=timezone.now(),
    )
    sender = MagicMock(return_value="SMbookinglink0000000000000001")

    with caplog.at_level(logging.INFO, logger="apps.qualification"):
        deliver_booking_link_whatsapp_text(
            whatsapp_number=WHATSAPP_NUMBER,
            language="en",
            booking_link=BOOKING_LINK,
            sender=sender,
        )

    suppressed = [
        json.loads(record.message)
        for record in caplog.records
        if record.message.startswith("{")
        and json.loads(record.message).get("event") == "booking_link_whatsapp_text_duplicate_suppressed"
    ]

    assert len(suppressed) == 1
    assert [call for call in sender.call_args_list if "to_number" in call.kwargs] == []


def _reach_whatsapp_confirmation_prompt() -> None:
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "project_type": "new_website",
            "requirements": "I need a new website for my restaurant",
            "referral_source": "Facebook",
        },
    )


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_booking_link_sent_after_server_restart_clears_stale_session_flag(
    mock_extract,
    mock_twilio_booking_link_send: MagicMock,
    client: Client,
):
    """Simulate runserver restart: DB session still marked sent, memory state cleared."""
    WhatsAppConversationSession.objects.create(
        whatsapp_number=WHATSAPP_NUMBER,
        language="en",
        booking_link_sent_at=timezone.now(),
    )
    clear_conversations()
    _reach_whatsapp_confirmation_prompt()

    response = _post_turn(client, message="Yes", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ceb3")
    body = response.json()

    assert body["booking_link_sent"] is True
    assert body["send_booking_link"] is False
    assert body["reply_text"] == TEXT_COMPLETION_WITH_LINK
    assert BOOKING_LINK in body["reply_text"]
    mock_twilio_booking_link_send.assert_not_called()
    mock_extract.assert_not_called()
    session = WhatsAppConversationSession.objects.get(whatsapp_number=WHATSAPP_NUMBER)
    assert session.booking_link_sent_at is None


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_text_completion_puts_booking_link_in_single_reply_text(
    mock_extract,
    mock_twilio_booking_link_send: MagicMock,
    client: Client,
):
    _reach_whatsapp_confirmation_prompt()

    response = _post_turn(client, message="Yes", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ceb5")
    body = response.json()

    assert body["reply_mode"] == "text"
    assert body["reply_text"] == TEXT_COMPLETION_WITH_LINK
    assert BOOKING_LINK in body["reply_text"]
    assert "I will send you a booking link" not in body["reply_text"]
    assert body["booking_link_sent"] is True
    assert body["send_booking_link"] is False
    mock_twilio_booking_link_send.assert_not_called()
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.core.legacy_compat.transcribe_audio", return_value="Yes")
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_voice_completion_puts_booking_link_in_single_reply_text(
    mock_extract,
    mock_download,
    mock_transcribe,
    mock_twilio_booking_link_send: MagicMock,
    client: Client,
):
    _reach_whatsapp_confirmation_prompt()

    response = _post_turn(
        client,
        input_channel="whatsapp_voice_note",
        media_url=MEDIA_URL,
        message_sid="SM0cc5a1d9e22bf9850ca24261ee23ceb8",
    )
    body = response.json()

    assert body["reply_mode"] == "voice"
    assert body["spoken_text"] == VOICE_COMPLETION_SPOKEN
    assert body["reply_text"] == VOICE_COMPLETION_SPOKEN
    assert BOOKING_LINK not in body["spoken_text"]
    assert body["whatsapp_text"] == VOICE_COMPLETION_WHATSAPP
    assert BOOKING_LINK in body["whatsapp_text"]
    assert body["booking_link_sent"] is True
    assert body["send_booking_link"] is True
    assert body["booking_link"] == BOOKING_LINK
    mock_twilio_booking_link_send.assert_called_once()
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
def test_cached_completion_with_send_booking_link_false_does_not_send(
    mock_twilio_booking_link_send: MagicMock,
    client: Client,
):
    message_sid = "SM0cc5a1d9e22bf9850ca24261ee23ceb0"
    cache_turn_response(
        message_sid,
        {
            "accepted_fields": {
                "project_type": "new_website",
                "requirements": "I need a new website for my restaurant",
                "referral_source": "Facebook",
                "whatsapp_confirmed": True,
            },
            "rejected_fields": {},
            "human_handoff_requested": False,
            "next_field": None,
            "reply_text": TEXT_COMPLETION_WITH_LINK,
            "qualification_status": "completed",
            "conversation_language": "en",
            "preferred_phone": None,
            "reply_mode": "text",
            "send_booking_link": False,
            "booking_link_sent": True,
            "booking_link": BOOKING_LINK,
        },
    )

    response = _post_turn(
        client,
        message="Yes",
        message_sid=message_sid,
    )
    body = response.json()

    assert body["booking_link_sent"] is True
    assert body["send_booking_link"] is False
    assert body["reply_text"] == TEXT_COMPLETION_WITH_LINK
    mock_twilio_booking_link_send.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_duplicate_completion_message_sid_does_not_resend_booking_link(
    mock_extract,
    mock_twilio_booking_link_send: MagicMock,
    client: Client,
):
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "project_type": "new_website",
            "requirements": "I need a new website for my restaurant",
            "referral_source": "Facebook",
        },
    )
    message_sid = "SM0cc5a1d9e22bf9850ca24261ee23ceb9"
    payload = {
        "message": "Yes",
        "whatsapp_number": WHATSAPP_NUMBER,
        "input_channel": "whatsapp_text",
        "message_sid": message_sid,
        "media_url": None,
        "media_content_type": None,
    }

    first = client.post(
        ENDPOINT_PATH,
        data=json.dumps(payload),
        content_type="application/json",
        **internal_api_auth_headers(secret=API_SECRET),
    )
    second = client.post(
        ENDPOINT_PATH,
        data=json.dumps(payload),
        content_type="application/json",
        **internal_api_auth_headers(secret=API_SECRET),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    assert first.json()["send_booking_link"] is False
    assert BOOKING_LINK in first.json()["reply_text"]
    mock_twilio_booking_link_send.assert_not_called()
    mock_extract.assert_not_called()
