"""Tests for WhatsApp language-gate routing on the extract endpoint."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from apps.qualification.conversation_flow import QUESTIONS
from apps.qualification.conversation_state import clear_conversations, save_accepted_fields
from apps.qualification.domain.language_selection import LANGUAGE_ARABIC, LANGUAGE_ENGLISH
from apps.qualification.message_idempotency import clear_message_sid_cache, get_cached_turn_response
from apps.qualification.models import QualificationFieldFilterResult, WhatsAppConversationSession
from apps.qualification.tests.internal_api_test_helpers import API_SECRET, internal_api_auth_headers

pytestmark = [pytest.mark.language_gate, pytest.mark.django_db]

ENDPOINT_PATH = "/api/internal/qualification/extract/"
VALID_WHATSAPP_NUMBER = "+923001234567"
MESSAGE_SID = "SM0cc5a1d9e22bf9850ca24261ee23ce90"
VOICE_MESSAGE_SID = "MM0cc5a1d9e22bf9850ca24261ee23ce90"
TWILIO_MEDIA_URL = "https://api.twilio.com/2010-04-01/Accounts/ACtest/Media/MEtestvoice001"
ARABIC_FIRST_QUESTION = "ما نوع الموقع الإلكتروني الذي تحتاجه؟"

LANGUAGE_PICKER_SETTINGS = {
    "TWILIO_LANGUAGE_PICKER_CONTENT_SID": "HXtestcontentsidfortest0000000000",
    "TWILIO_WHATSAPP_FROM_NUMBER": "whatsapp:+15557654321",
}


@pytest.fixture
def client() -> Client:
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()
    return Client()


@pytest.fixture(autouse=True)
def _reset_state():
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()
    yield
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()


def _post_extract(client: Client, payload: dict) -> object:
    return client.post(
        ENDPOINT_PATH,
        data=json.dumps(payload),
        content_type="application/json",
        **internal_api_auth_headers(secret=API_SECRET),
    )


def _text_payload(
    *,
    message: str,
    message_sid: str = MESSAGE_SID,
    button_payload: str | None = None,
) -> dict:
    payload = {
        "message": message,
        "whatsapp_number": VALID_WHATSAPP_NUMBER,
        "input_channel": "whatsapp_text",
        "message_sid": message_sid,
        "media_url": None,
        "media_content_type": None,
    }
    if button_payload is not None:
        payload["button_payload"] = button_payload
    return payload


def _voice_payload() -> dict:
    return {
        "message": "",
        "whatsapp_number": VALID_WHATSAPP_NUMBER,
        "input_channel": "whatsapp_voice_note",
        "message_sid": VOICE_MESSAGE_SID,
        "media_url": TWILIO_MEDIA_URL,
        "media_content_type": "audio/ogg",
    }


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker", return_value="SMpicker000000000000000000000001")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_new_customer_text_sends_selector_without_openrouter(mock_extract, mock_send_picker, client):
    response = _post_extract(client, _text_payload(message="hello"))

    assert response.status_code == 200
    assert response.json() == {
        "status": "awaiting_language_selection",
        "message": "Language selector sent.",
    }
    mock_send_picker.assert_called_once_with(to_number=f"whatsapp:{VALID_WHATSAPP_NUMBER}")
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker", return_value="SMpicker000000000000000000000001")
@patch("apps.qualification.services.transcription_service.VoiceNoteTranscriptionService.transcribe")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_new_customer_voice_note_sends_selector_without_deepgram(
    mock_extract,
    mock_transcribe,
    mock_send_picker,
    client,
):
    response = _post_extract(client, _voice_payload())

    assert response.status_code == 200
    assert response.json()["status"] == "awaiting_language_selection"
    mock_send_picker.assert_called_once()
    mock_transcribe.assert_not_called()
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_lang_en_button_saves_language_and_starts_qualification(mock_extract, mock_send_picker, client):
    response = _post_extract(
        client,
        _text_payload(message="English", button_payload="lang_en"),
    )

    assert response.status_code == 200
    session = WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER)
    assert session.language == LANGUAGE_ENGLISH
    assert session.language_selected_at is not None
    assert response.json()["reply_text"] == QUESTIONS["project_type"]
    assert response.json()["conversation_language"] == LANGUAGE_ENGLISH
    assert response.json()["qualification_status"] == "in_progress"
    mock_send_picker.assert_not_called()
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_lang_ar_button_saves_arabic_and_starts_qualification(mock_extract, mock_send_picker, client):
    response = _post_extract(
        client,
        _text_payload(message="العربية", button_payload="lang_ar"),
    )

    assert response.status_code == 200
    session = WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER)
    assert session.language == LANGUAGE_ARABIC
    assert session.language_selected_at is not None
    assert response.json()["reply_text"] == ARABIC_FIRST_QUESTION
    assert response.json()["conversation_language"] == LANGUAGE_ARABIC
    mock_send_picker.assert_not_called()
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter", return_value=QualificationFieldFilterResult(
    accepted_fields={"project_type": "new_website"},
    rejected_fields=(),
    human_handoff_requested=False,
))
def test_existing_english_conversation_continues_qualification(mock_extract, mock_send_picker, client):
    WhatsAppConversationSession.objects.create(
        whatsapp_number=VALID_WHATSAPP_NUMBER,
        language=LANGUAGE_ENGLISH,
        language_selected_at=timezone.now(),
    )

    response = _post_extract(client, _text_payload(message="I need a new website"))

    assert response.status_code == 200
    mock_send_picker.assert_not_called()
    mock_extract.assert_called_once()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker", return_value="SMpicker000000000000000000000001")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_pending_picker_body_english_only_when_language_unset(mock_extract, mock_send_picker, client):
    first = _post_extract(client, _text_payload(message="hello", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce91"))

    assert first.status_code == 200
    assert first.json()["status"] == "awaiting_language_selection"
    session = WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER)
    assert session.language is None
    assert session.language_picker_pending_until is not None

    second = _post_extract(
        client,
        _text_payload(message="English", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce92"),
    )

    assert second.status_code == 200
    session.refresh_from_db()
    assert session.language == LANGUAGE_ENGLISH
    assert session.language_picker_pending_until is None
    assert second.json()["reply_text"] == QUESTIONS["project_type"]
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter", return_value=QualificationFieldFilterResult(
    accepted_fields={},
    rejected_fields=(),
    human_handoff_requested=False,
))
def test_typed_fallback_does_not_change_active_english_conversation(mock_extract, mock_send_picker, client):
    WhatsAppConversationSession.objects.create(
        whatsapp_number=VALID_WHATSAPP_NUMBER,
        language=LANGUAGE_ENGLISH,
        language_selected_at=timezone.now(),
    )

    response = _post_extract(client, _text_payload(message="English"))

    assert response.status_code == 200
    mock_send_picker.assert_not_called()
    mock_extract.assert_called_once()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker", return_value="SMpicker000000000000000000000001")
def test_duplicate_message_sid_does_not_send_duplicate_selector(mock_send_picker, client):
    payload = _text_payload(message="hello")
    first = _post_extract(client, payload)
    second = _post_extract(client, payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    mock_send_picker.assert_called_once()
    assert get_cached_turn_response(MESSAGE_SID) is not None


@override_settings(TWILIO_LANGUAGE_PICKER_CONTENT_SID="")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_missing_content_sid_returns_503_without_openrouter(mock_extract, client):
    response = _post_extract(client, _text_payload(message="hello"))

    assert response.status_code == 503
    assert response.json() == {"error": "Qualification service is unavailable."}
    mock_extract.assert_not_called()
    assert WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER).language is None


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch(
    "apps.qualification.services.language_gate_service.send_language_picker",
    side_effect=RuntimeError("twilio unavailable"),
)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_twilio_send_failure_leaves_language_unset(mock_extract, mock_send_picker, client):
    response = _post_extract(client, _text_payload(message="hello"))

    assert response.status_code == 502
    assert response.json() == {"error": "Qualification service request failed."}
    session = WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER)
    assert session.language is None
    assert session.language_picker_pending_until is None
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter", return_value=QualificationFieldFilterResult(
    accepted_fields={},
    rejected_fields=(),
    human_handoff_requested=False,
))
def test_redis_progress_lazy_backfills_english_without_selector(mock_extract, mock_send_picker, client):
    save_accepted_fields(VALID_WHATSAPP_NUMBER, {"project_type": "new_website"})

    response = _post_extract(client, _text_payload(message="restaurant website details"))

    assert response.status_code == 200
    session = WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER)
    assert session.language == LANGUAGE_ENGLISH
    mock_send_picker.assert_not_called()
    mock_extract.assert_called_once()
