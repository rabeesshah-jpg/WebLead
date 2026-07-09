"""Tests for WhatsApp text and voice qualification channel handling."""

from __future__ import annotations

import json
from unittest.mock import ANY, MagicMock, patch

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from apps.qualification.conversation_state import clear_conversations, save_accepted_fields
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.models import QualificationFieldFilterResult, RejectedQualificationField, WhatsAppConversationSession
from apps.qualification.tests.internal_api_test_helpers import (
    API_SECRET,
    MOCK_VOICE_AUDIO_BYTES,
    MOCK_VOICE_AUDIO_DOWNLOAD,
    internal_api_auth_headers,
)

ENDPOINT_PATH = "/api/internal/qualification/extract/"
WHATSAPP_NUMBER = "+923001234567"
BOOKING_LINK = "https://booking.example.com/test-schedule"
MEDIA_URL = (
    "https://api.twilio.com/2010-04-01/Accounts/ACtest/Media/MEtestvoice001"
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
TEXT_COMPLETION_REPLY = get_customer_message(
    language="en",
    key="completion_with_booking_link",
    booking_link=BOOKING_LINK,
)

pytestmark = pytest.mark.django_db


def _filter_result(
    *,
    accepted_fields: dict[str, object],
    human_handoff_requested: bool = False,
    rejected_fields: tuple[RejectedQualificationField, ...] = (),
) -> QualificationFieldFilterResult:
    return QualificationFieldFilterResult(
        accepted_fields=accepted_fields,
        rejected_fields=rejected_fields,
        human_handoff_requested=human_handoff_requested,
    )


def _post_turn(
    client: Client,
    *,
    message: str | None = None,
    input_channel: str = "whatsapp_text",
    message_sid: str | None = None,
    media_url: str | None = None,
    media_content_type: str = "audio/ogg",
) -> object:
    payload: dict[str, object] = {
        "whatsapp_number": WHATSAPP_NUMBER,
        "input_channel": input_channel,
    }
    if message is not None:
        payload["message"] = message
    if message_sid is not None:
        payload["message_sid"] = message_sid
    if media_url is not None:
        payload["media_url"] = media_url
        payload["media_content_type"] = media_content_type

    return client.post(
        ENDPOINT_PATH,
        data=json.dumps(payload),
        content_type="application/json",
        **internal_api_auth_headers(),
    )


@pytest.fixture
def client() -> Client:
    clear_conversations()
    clear_message_sid_cache()
    return Client()


@pytest.fixture(autouse=True)
def _reset_state():
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()
    WhatsAppConversationSession.objects.create(
        whatsapp_number=WHATSAPP_NUMBER,
        language="en",
        language_selected_at=timezone.now(),
    )
    yield
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()


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
def test_text_input_returns_reply_mode_text(mock_extract, client):
    response = _post_turn(
        client,
        message="I need a new website for my restaurant.",
        input_channel="whatsapp_text",
    )

    body = response.json()
    assert response.status_code == 200
    assert body["reply_mode"] == "text"
    assert body["send_booking_link"] is False
    assert body["booking_link"] is None
    assert "transcript" not in body
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.core.legacy_compat.transcribe_audio", return_value="Facebook")
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_voice_note_input_returns_reply_mode_voice_and_transcript(
    mock_extract,
    mock_download,
    mock_transcribe,
    client,
):
    mock_extract.return_value = _filter_result(accepted_fields={"referral_source": "Facebook"})

    first = _post_turn(
        client,
        message="I need a new website for my restaurant.",
        input_channel="whatsapp_text",
        message_sid="SM11111111111111111111111111111111",
    )
    second = _post_turn(
        client,
        input_channel="whatsapp_voice_note",
        media_url=MEDIA_URL,
        message_sid="SM22222222222222222222222222222222",
    )

    assert first.status_code == 200
    assert second.status_code == 200
    body = second.json()
    assert body["reply_mode"] == "voice"
    assert body["transcript"] == "Facebook"
    assert body["next_field"] == "whatsapp_confirmed"
    mock_download.assert_called_once_with(MEDIA_URL)
    mock_transcribe.assert_called_once_with(
        MOCK_VOICE_AUDIO_BYTES,
        content_type="audio/ogg",
        transcription_config=ANY,
    )
    mock_extract.assert_called_once()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.core.legacy_compat.transcribe_audio", return_value="Yes")
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_text_to_voice_switch_uses_latest_reply_mode(mock_extract, mock_download, mock_transcribe, client):
    _reach_whatsapp_confirmation_prompt()

    text_response = _post_turn(
        client,
        message="Yes",
        message_sid="SMaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )
    voice_response = _post_turn(
        client,
        message="Yes",
        input_channel="whatsapp_voice_note",
        media_url=MEDIA_URL,
        message_sid="SMcccccccccccccccccccccccccccccccc",
    )

    assert text_response.json()["reply_mode"] == "text"
    voice_body = voice_response.json()
    assert voice_body["reply_mode"] == "voice"
    assert voice_body["qualification_status"] == "completed"
    assert voice_body["transcript"] == "Yes"
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.core.legacy_compat.transcribe_audio")
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_voice_to_text_switch_uses_latest_reply_mode(
    mock_extract,
    mock_download,
    mock_transcribe,
    client,
):
    _reach_whatsapp_confirmation_prompt()
    mock_transcribe.return_value = "Yes"

    voice_response = _post_turn(
        client,
        input_channel="whatsapp_voice_note",
        media_url=MEDIA_URL,
        message_sid="SMeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    )
    text_response = _post_turn(
        client,
        message="Yes",
        input_channel="whatsapp_text",
        message_sid="SMffffffffffffffffffffffffffffffff",
    )

    assert voice_response.json()["reply_mode"] == "voice"
    text_body = text_response.json()
    assert text_body["reply_mode"] == "text"
    assert text_body["qualification_status"] == "completed"
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.core.legacy_compat.transcribe_audio", return_value="Yes")
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_completed_voice_flow_returns_voice_completion_text_and_booking_link(
    mock_extract,
    mock_download,
    mock_transcribe,
    mock_twilio_booking_link_send: MagicMock,
    client,
):
    _reach_whatsapp_confirmation_prompt()

    response = _post_turn(
        client,
        input_channel="whatsapp_voice_note",
        media_url=MEDIA_URL,
        message_sid="SMiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiii",
    )

    body = response.json()
    assert body["reply_mode"] == "voice"
    assert body["qualification_status"] == "completed"
    assert body["spoken_text"] == VOICE_COMPLETION_SPOKEN
    assert body["reply_text"] == VOICE_COMPLETION_SPOKEN
    assert BOOKING_LINK not in body["spoken_text"]
    assert BOOKING_LINK not in body["reply_text"]
    assert body["whatsapp_text"] == VOICE_COMPLETION_WHATSAPP
    assert BOOKING_LINK in body["whatsapp_text"]
    assert body["send_booking_link"] is True
    assert body["booking_link_sent"] is True
    assert body["booking_link"] == BOOKING_LINK
    mock_twilio_booking_link_send.assert_called_once()
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_duplicate_message_sid_does_not_create_duplicate_turn(mock_extract, client):
    message_sid = "SMjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjj"

    first = _post_turn(
        client,
        message="I need a new website for my restaurant.",
        message_sid=message_sid,
    )
    second = _post_turn(
        client,
        message="I need a new website for my restaurant.",
        message_sid=message_sid,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    mock_extract.assert_not_called()
