"""Regression tests for voice utterance idempotency and spoken/WhatsApp split."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client, override_settings

from apps.qualification.conversation_state import clear_conversations, save_accepted_fields
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.domain.tts_safety import (
    sanitize_spoken_text_for_tts,
    spoken_text_contains_url,
)
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.services.extract_service import ExtractService
from apps.qualification.tests.internal_api_test_helpers import (
    API_SECRET,
    MOCK_VOICE_AUDIO_DOWNLOAD,
    internal_api_auth_headers,
)
from apps.qualification.voice_turn_idempotency import (
    begin_voice_utterance_turn,
    cache_voice_utterance_response,
)

pytestmark = pytest.mark.django_db

ENDPOINT_PATH = "/api/internal/qualification/extract/"
WHATSAPP_NUMBER = "+923001234567"
BOOKING_LINK = "https://booking.example.com/test-schedule"
CALL_SID = "CAabcdefghijklmnopqrstuvwxyz012345"
SPOKEN_COMPLETION = get_customer_message(language="en", key="completion_spoken")
WHATSAPP_BOOKING = get_customer_message(
    language="en",
    key="completion_with_booking_link",
    booking_link=BOOKING_LINK,
)


def _post(client: Client, payload: dict) -> object:
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
    yield
    clear_conversations()
    clear_message_sid_cache()


def test_url_sanitizer_replaces_booking_url_before_tts():
    spoken = sanitize_spoken_text_for_tts(
        f"Perfect, thank you. Please book a time here: {BOOKING_LINK}"
    )
    assert BOOKING_LINK not in spoken
    assert spoken_text_contains_url(spoken) is False
    assert "booking link above" in spoken.lower()


def test_partial_transcript_is_ignored(client: Client):
    response = _post(
        client,
        {
            "whatsapp_number": WHATSAPP_NUMBER,
            "input_channel": "whatsapp_text",
            "message": "I need a website",
            "call_sid": CALL_SID,
            "utterance_id": "utt-partial-1",
            "is_final": False,
        },
    )
    body = response.json()
    assert response.status_code == 200
    assert body["reply_text"] == ""
    assert body["spoken_text"] == ""
    assert body["tts_enqueued"] is False
    assert body["duplicate_detected"] is False
    assert get_accepted_fields_safe() == {}


def get_accepted_fields_safe() -> dict:
    from apps.qualification.conversation_state import get_accepted_fields

    return get_accepted_fields(WHATSAPP_NUMBER)


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
def test_duplicate_final_transcript_enqueues_tts_only_once(client: Client):
    turn_count = {"n": 0}

    def fake_turn(**kwargs):
        turn_count["n"] += 1
        return {
            "accepted_fields": {"project_type": "new_website"},
            "rejected_fields": {},
            "human_handoff_requested": False,
            "next_field": "requirements",
            "reply_text": "What are you specifically looking for?",
            "qualification_status": "in_progress",
            "preferred_phone": None,
            "conversation_language": "en",
        }

    service = ExtractService(turn_handler=fake_turn)
    payload = {
        "whatsapp_number": WHATSAPP_NUMBER,
        "input_channel": "whatsapp_text",
        "message": "I need SEO help",
        "call_sid": CALL_SID,
        "utterance_id": "utt-final-1",
        "is_final": True,
    }
    first = service.run_turn(payload)
    second = service.run_turn(payload)

    assert turn_count["n"] == 1
    assert first["tts_enqueued"] is True
    assert first["duplicate_detected"] is False
    assert second["duplicate_detected"] is True
    assert second["tts_enqueued"] is False
    assert first["reply_text"] == second["reply_text"]


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
def test_debounce_ignores_same_transcript_without_utterance_id():
    response = {
        "reply_text": "ok",
        "spoken_text": "ok",
        "tts_enqueued": True,
        "duplicate_detected": False,
    }
    cache_voice_utterance_response(
        call_sid=CALL_SID,
        utterance_id=None,
        transcript="hello there",
        response=response,
    )
    duplicate = begin_voice_utterance_turn(
        call_sid=CALL_SID,
        utterance_id=None,
        transcript="Hello there",
    )
    assert duplicate is not None
    assert duplicate["tts_enqueued"] is True


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.core.legacy_compat.transcribe_audio", return_value="Yes")
@patch(
    "apps.qualification.core.legacy_compat.download_twilio_media",
    return_value=MOCK_VOICE_AUDIO_DOWNLOAD,
)
@patch(
    "apps.qualification.services.booking_link_delivery_service.send_booking_link_whatsapp_text",
    return_value="SMbooked",
)
def test_voice_booking_complete_spoken_has_no_url(
    mock_send: MagicMock,
    mock_download,
    mock_transcribe,
    client: Client,
):
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "project_type": "new_website",
            "requirements": "restaurant website",
            "referral_source": "Facebook",
        },
    )
    response = _post(
        client,
        {
            "whatsapp_number": WHATSAPP_NUMBER,
            "input_channel": "whatsapp_voice_note",
            "message": "Yup",
            "message_sid": "SM0cc5a1d9e22bf9850ca24261ee23cef1",
            "media_url": (
                "https://api.twilio.com/2010-04-01/Accounts/ACtest/Media/MEtestvoice001"
            ),
            "media_content_type": "audio/ogg",
            "call_sid": CALL_SID,
            "utterance_id": "utt-yes-1",
            "is_final": True,
        },
    )
    body = response.json()
    assert body["qualification_status"] == "completed"
    assert body["spoken_text"] == SPOKEN_COMPLETION
    assert body["reply_text"] == WHATSAPP_BOOKING
    assert BOOKING_LINK in body["reply_text"]
    assert BOOKING_LINK not in body["spoken_text"]
    assert body["whatsapp_text"] == WHATSAPP_BOOKING
    assert BOOKING_LINK in body["whatsapp_text"]
    assert body["send_booking_link"] is True
    assert body["booking_link_sent"] is True
    assert body["should_send_text"] is True
    assert body["should_send_audio"] is True
    assert body["tts_enqueued"] is True
    mock_send.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
def test_irrelevant_message_redirects_politely(client: Client):
    save_accepted_fields(WHATSAPP_NUMBER, {})
    response = _post(
        client,
        {
            "whatsapp_number": WHATSAPP_NUMBER,
            "message": "maybe",
            "input_channel": "whatsapp_text",
        },
    )
    body = response.json()
    assert "few basic project details" in body["reply_text"]
    assert "new website" in body["reply_text"]
    assert body["next_field"] == "business_type"


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
def test_unsupported_question_uses_meeting_fallback(client: Client):
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "project_type": "new_website",
            "requirements": "website",
        },
    )
    response = _post(
        client,
        {
            "whatsapp_number": WHATSAPP_NUMBER,
            "message": "Can you guarantee 1 million sales?",
            "input_channel": "whatsapp_text",
        },
    )
    body = response.json()
    assert "website specialist" in body["reply_text"]
    assert body["next_field"] == "referral_source"


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
def test_multiple_services_are_merged(client: Client):
    response = _post(
        client,
        {
            "whatsapp_number": WHATSAPP_NUMBER,
            "message": "I need website, SEO, and AI chatbot",
            "input_channel": "whatsapp_text",
        },
    )
    body = response.json()
    assert body["accepted_fields"]["services_required"] == [
        "website",
        "seo",
        "ai_chatbot",
    ]


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
def test_fallback_and_normal_response_not_both_queued():
    """Duplicate processing must not enqueue a second TTS payload."""
    service = ExtractService(
        turn_handler=lambda **kwargs: {
            "accepted_fields": {},
            "rejected_fields": {},
            "human_handoff_requested": False,
            "next_field": "business_type",
            "reply_text": "Are you looking for a new website or an upgrade to your existing website?",
            "qualification_status": "in_progress",
            "preferred_phone": None,
            "conversation_language": "en",
        }
    )
    payload = {
        "whatsapp_number": WHATSAPP_NUMBER,
        "input_channel": "whatsapp_text",
        "message": "hello",
        "call_sid": CALL_SID,
        "utterance_id": "utt-lock-1",
        "is_final": True,
    }
    first = service.run_turn(payload)
    second = service.run_turn(payload)
    assert first["tts_enqueued"] is True
    assert second["tts_enqueued"] is False
    assert second["duplicate_detected"] is True
