"""Tests for inbound-message idle reset after SESSION_IDLE_RESET_SECONDS."""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from apps.qualification.conversation_state import (
    clear_conversations,
    get_accepted_fields,
    save_accepted_fields,
)
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.models import WhatsAppConversationSession
from apps.qualification.services.conversation_session_service import mark_booking_link_sent
from apps.qualification.tests.internal_api_test_helpers import (
    API_SECRET,
    MOCK_VOICE_AUDIO_DOWNLOAD,
    internal_api_auth_headers,
)

pytestmark = pytest.mark.django_db

ENDPOINT_PATH = "/api/internal/qualification/extract/"
WHATSAPP_NUMBER = "+923001234567"
BOOKING_LINK = "https://booking.example.com/test-schedule"
MEDIA_URL = "https://api.twilio.com/2010-04-01/Accounts/ACtest/Media/MEtestvoice001"
ONBOARDING_INTRO = get_customer_message(language="en", key="onboarding_intro")


def _post_text(client: Client, message: str, *, message_sid: str) -> object:
    return client.post(
        ENDPOINT_PATH,
        data=json.dumps(
            {
                "whatsapp_number": WHATSAPP_NUMBER,
                "input_channel": "whatsapp_text",
                "message": message,
                "message_sid": message_sid,
            }
        ),
        content_type="application/json",
        **internal_api_auth_headers(),
    )


def _post_voice(
    client: Client,
    *,
    message_sid: str,
    mock_transcribe,
    transcript: str,
) -> object:
    mock_transcribe.return_value = transcript
    return client.post(
        ENDPOINT_PATH,
        data=json.dumps(
            {
                "whatsapp_number": WHATSAPP_NUMBER,
                "input_channel": "whatsapp_voice_note",
                "message_sid": message_sid,
                "media_url": MEDIA_URL,
                "media_content_type": "audio/ogg",
            }
        ),
        content_type="application/json",
        **internal_api_auth_headers(),
    )


@pytest.fixture
def client() -> Client:
    clear_conversations()
    clear_message_sid_cache()
    return Client()


@pytest.fixture(autouse=True)
def _english_session():
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()
    WhatsAppConversationSession.objects.create(
        whatsapp_number=WHATSAPP_NUMBER,
        language="en",
        language_selected_at=timezone.now(),
        onboarding_intro_sent=True,
        last_message_at=timezone.now() - timedelta(minutes=10),
    )
    yield
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()


def _set_last_activity(*, seconds_ago: int) -> WhatsAppConversationSession:
    session = WhatsAppConversationSession.objects.get(whatsapp_number=WHATSAPP_NUMBER)
    session.last_message_at = timezone.now() - timedelta(seconds=seconds_ago)
    session.save(update_fields=["last_message_at"])
    return session


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK, SESSION_IDLE_RESET_SECONDS=300)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@pytest.mark.parametrize("gap_seconds", [299])
def test_idle_reset_does_not_trigger_below_threshold(mock_extract, client, gap_seconds):
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {"project_type": "new_website"},
    )
    _set_last_activity(seconds_ago=gap_seconds)

    response = _post_text(client, "hello", message_sid="SM0cc5a1d9e22bf9850ca24261ee23cea0")
    body = response.json()

    assert response.status_code == 200
    assert body.get("idle_reset_triggered") is not True
    assert get_accepted_fields(WHATSAPP_NUMBER)["project_type"] == "new_website"
    assert ONBOARDING_INTRO not in body["reply_text"]
    assert body["next_field"] == "requirements"
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK, SESSION_IDLE_RESET_SECONDS=300)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@pytest.mark.parametrize(
    ("gap_seconds", "message_sid"),
    [
        (300, "SM0cc5a1d9e22bf9850ca24261ee23ceb0"),
        (301, "SM0cc5a1d9e22bf9850ca24261ee23ceb1"),
    ],
)
def test_idle_reset_triggers_at_or_above_threshold(
    mock_extract,
    client,
    gap_seconds,
    message_sid,
):
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "project_type": "new_website",
            "requirements": "restaurant website",
        },
    )
    _set_last_activity(seconds_ago=gap_seconds)

    response = _post_text(client, "Hello", message_sid=message_sid)
    body = response.json()

    assert response.status_code == 200
    assert body["idle_reset_triggered"] is True
    assert body["inactivity_gap_seconds"] == gap_seconds
    assert get_accepted_fields(WHATSAPP_NUMBER) == {}
    assert ONBOARDING_INTRO in body["reply_text"]
    assert "new website" in body["reply_text"].lower()
    assert body.get("conversation_state") == "WAITING_FOR_PROJECT_TYPE"
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK, SESSION_IDLE_RESET_SECONDS=300)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_idle_reset_after_requirements_step_sends_onboarding(mock_extract, client):
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {"project_type": "new_website"},
    )
    _set_last_activity(seconds_ago=360)

    response = _post_text(client, "Hello", message_sid="SM0cc5a1d9e22bf9850ca24261ee23cec0")
    body = response.json()

    assert body["idle_reset_triggered"] is True
    assert ONBOARDING_INTRO in body["reply_text"]
    assert "new website" in body["reply_text"].lower()
    assert get_accepted_fields(WHATSAPP_NUMBER) == {}


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK, SESSION_IDLE_RESET_SECONDS=300)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_idle_reset_after_booking_link_clears_booking_state(mock_extract, client):
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "project_type": "new_website",
            "requirements": "restaurant",
            "referral_source": "Facebook",
            "whatsapp_confirmed": True,
            "preferred_phone": WHATSAPP_NUMBER,
        },
    )
    session = _set_last_activity(seconds_ago=360)
    mark_booking_link_sent(session)

    response = _post_text(client, "Hello", message_sid="SM0cc5a1d9e22bf9850ca24261ee23cec1")
    body = response.json()

    assert body["idle_reset_triggered"] is True
    assert body["booking_link_sent"] is False
    assert "booking link above" not in body["reply_text"].lower()
    assert ONBOARDING_INTRO in body["reply_text"]
    session.refresh_from_db()
    assert session.booking_link_sent_at is None


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK, SESSION_IDLE_RESET_SECONDS=300)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_booking_link_follow_up_within_threshold_is_preserved(mock_extract, client):
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "project_type": "new_website",
            "requirements": "restaurant",
            "referral_source": "Facebook",
            "whatsapp_confirmed": True,
            "preferred_phone": WHATSAPP_NUMBER,
        },
    )
    session = _set_last_activity(seconds_ago=120)
    mark_booking_link_sent(session)

    response = _post_text(client, "How are you?", message_sid="SM0cc5a1d9e22bf9850ca24261ee23cec2")
    body = response.json()

    assert body.get("idle_reset_triggered") is not True
    assert body["booking_link_sent"] is True
    assert "booking link above" in body["reply_text"].lower()
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK, SESSION_IDLE_RESET_SECONDS=300)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.core.legacy_compat.transcribe_audio")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_voice_idle_reset_sends_onboarding_audio_only(
    mock_extract,
    mock_transcribe,
    mock_download,
    client,
):
    save_accepted_fields(WHATSAPP_NUMBER, {"project_type": "new_website"})
    _set_last_activity(seconds_ago=360)

    response = _post_voice(
        client,
        message_sid="SM0cc5a1d9e22bf9850ca24261ee23cec3",
        mock_transcribe=mock_transcribe,
        transcript="Hello",
    )
    body = response.json()

    assert body["idle_reset_triggered"] is True
    assert body["should_send_audio"] is True
    assert body["should_send_text"] is False
    assert body.get("whatsapp_text", "") == ""
    assert "new website" in body["spoken_text"].lower()
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK, SESSION_IDLE_RESET_SECONDS=300)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_text_idle_reset_sends_onboarding_text_only(mock_extract, client):
    save_accepted_fields(WHATSAPP_NUMBER, {"project_type": "new_website"})
    _set_last_activity(seconds_ago=360)

    response = _post_text(client, "Hello", message_sid="SM0cc5a1d9e22bf9850ca24261ee23cec4")
    body = response.json()

    assert body["idle_reset_triggered"] is True
    assert body["should_send_text"] is True
    assert body["should_send_audio"] is False
    assert ONBOARDING_INTRO in body["reply_text"]
    assert "new website" in body["reply_text"].lower()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK, SESSION_IDLE_RESET_SECONDS=300)
@patch("apps.qualification.services.extract_service.ExtractService._touch_session_activity")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_idle_reset_uses_previous_last_activity_before_touch(
    mock_extract,
    mock_touch,
    client,
):
    previous = timezone.now() - timedelta(seconds=360)
    session = WhatsAppConversationSession.objects.get(whatsapp_number=WHATSAPP_NUMBER)
    session.last_message_at = previous
    session.save(update_fields=["last_message_at"])
    save_accepted_fields(WHATSAPP_NUMBER, {"project_type": "new_website"})

    response = _post_text(client, "Hello", message_sid="SM0cc5a1d9e22bf9850ca24261ee23cec5")
    body = response.json()

    assert body["idle_reset_triggered"] is True
    assert body["inactivity_gap_seconds"] == 360
    mock_touch.assert_called_once()
