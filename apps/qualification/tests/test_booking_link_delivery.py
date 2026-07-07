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
TTS_SAFE_COMPLETION = get_customer_message(language="en", key="completion")


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
    sender.assert_called_once()
    session.refresh_from_db()
    assert session.booking_link_sent_at is not None


def test_deliver_booking_link_whatsapp_text_logs_delivery_event(caplog):
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
    sender.assert_not_called()


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

    mock_extract.side_effect = [
        _filter_result(
            accepted_fields={
                "project_type": "new_website",
                "requirements": "I need a new website for my restaurant",
            },
        ),
        _filter_result(accepted_fields={"referral_source": "Facebook"}),
    ]

    _post_turn(
        client,
        message="I need a new website for my restaurant.",
        message_sid="SM0cc5a1d9e22bf9850ca24261ee23ceb1",
    )
    _post_turn(client, message="Facebook", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ceb2")
    response = _post_turn(client, message="Yes", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ceb3")
    body = response.json()

    assert body["booking_link_sent"] is True
    mock_twilio_booking_link_send.assert_called_once()
    sent_body = mock_twilio_booking_link_send.call_args.kwargs["body"]
    assert BOOKING_LINK in sent_body
    session = WhatsAppConversationSession.objects.get(whatsapp_number=WHATSAPP_NUMBER)
    assert session.booking_link_sent_at is not None


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_text_completion_sends_booking_link_as_whatsapp_text_only(
    mock_extract,
    mock_twilio_booking_link_send: MagicMock,
    client: Client,
):
    mock_extract.side_effect = [
        _filter_result(
            accepted_fields={
                "project_type": "new_website",
                "requirements": "I need a new website for my restaurant",
            },
        ),
        _filter_result(accepted_fields={"referral_source": "Facebook"}),
    ]
    save_accepted_fields(WHATSAPP_NUMBER, {})

    _post_turn(
        client,
        message="I need a new website for my restaurant.",
        message_sid="SM0cc5a1d9e22bf9850ca24261ee23ceb3",
    )
    _post_turn(client, message="Facebook", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ceb4")
    response = _post_turn(client, message="Yes", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ceb5")
    body = response.json()

    assert body["reply_mode"] == "text"
    assert body["reply_text"] == TTS_SAFE_COMPLETION
    assert BOOKING_LINK not in body["reply_text"]
    assert body["booking_link_sent"] is True
    mock_twilio_booking_link_send.assert_called_once()
    sent_body = mock_twilio_booking_link_send.call_args.kwargs["body"]
    assert BOOKING_LINK in sent_body


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.core.legacy_compat.transcribe_audio", return_value="Yes")
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_voice_completion_sends_booking_link_as_text_not_in_tts_reply(
    mock_extract,
    mock_download,
    mock_transcribe,
    mock_twilio_booking_link_send: MagicMock,
    client: Client,
):
    mock_extract.side_effect = [
        _filter_result(
            accepted_fields={
                "project_type": "new_website",
                "requirements": "I need a new website for my restaurant",
            },
        ),
        _filter_result(accepted_fields={"referral_source": "Facebook"}),
    ]

    _post_turn(
        client,
        message="I need a new website for my restaurant.",
        message_sid="SM0cc5a1d9e22bf9850ca24261ee23ceb6",
    )
    _post_turn(client, message="Facebook", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ceb7")
    response = _post_turn(
        client,
        input_channel="whatsapp_voice_note",
        media_url=MEDIA_URL,
        message_sid="SM0cc5a1d9e22bf9850ca24261ee23ceb8",
    )
    body = response.json()

    assert body["reply_mode"] == "voice"
    assert body["reply_text"] == TTS_SAFE_COMPLETION
    assert BOOKING_LINK not in body["reply_text"]
    assert body["booking_link_sent"] is True
    assert body["booking_link"] == BOOKING_LINK
    mock_twilio_booking_link_send.assert_called_once()
    sent_body = mock_twilio_booking_link_send.call_args.kwargs["body"]
    assert BOOKING_LINK in sent_body


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
def test_cached_completion_retries_booking_link_delivery(
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
            "reply_text": TTS_SAFE_COMPLETION,
            "qualification_status": "completed",
            "conversation_language": "en",
            "preferred_phone": None,
            "reply_mode": "text",
            "send_booking_link": True,
            "booking_link_sent": False,
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
    mock_twilio_booking_link_send.assert_called_once()
    sent_body = mock_twilio_booking_link_send.call_args.kwargs["body"]
    assert BOOKING_LINK in sent_body


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
    mock_twilio_booking_link_send.assert_called_once()
    mock_extract.assert_not_called()
