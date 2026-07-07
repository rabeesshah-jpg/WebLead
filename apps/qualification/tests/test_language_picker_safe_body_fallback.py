"""Tests for safe pending-picker body fallback on Twilio Quick Reply buttons."""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from apps.qualification.conversation_state import clear_conversations, get_accepted_fields, save_accepted_fields
from apps.qualification.domain.language_picker_pending import language_picker_pending_timeout
from apps.qualification.domain.language_selection import LANGUAGE_ARABIC, LANGUAGE_ENGLISH
from apps.qualification.domain.messages import get_language_changed_confirmation_message
from apps.qualification.message_idempotency import clear_message_sid_cache, get_cached_turn_response
from apps.qualification.models import QualificationFieldFilterResult, WhatsAppConversationSession
from apps.qualification.tests.internal_api_test_helpers import API_SECRET, internal_api_auth_headers

pytestmark = [pytest.mark.language_gate, pytest.mark.django_db]

ENDPOINT_PATH = "/api/internal/qualification/extract/"
VALID_WHATSAPP_NUMBER = "+923001234567"
MESSAGE_SID = "SM0cc5a1d9e22bf9850ca24261ee23ce90"
CHANGE_MESSAGE_SID = "SM0cc5a1d9e22bf9850ca24261ee23ce91"
SELECT_MESSAGE_SID = "SM0cc5a1d9e22bf9850ca24261ee23ce92"

LANGUAGE_PICKER_SETTINGS = {
    "TWILIO_LANGUAGE_PICKER_CONTENT_SID": "HXtestcontentsidfortest0000000000",
    "TWILIO_WHATSAPP_FROM_NUMBER": "whatsapp:+15557654321",
    "N8N_QUALIFICATION_API_SECRET": API_SECRET,
}

IN_PROGRESS_FIELDS = {
    "project_type": "new_website",
    "requirements": "A restaurant website with online ordering",
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


def _english_session_with_progress() -> WhatsAppConversationSession:
    save_accepted_fields(VALID_WHATSAPP_NUMBER, dict(IN_PROGRESS_FIELDS))
    return WhatsAppConversationSession.objects.create(
        whatsapp_number=VALID_WHATSAPP_NUMBER,
        language=LANGUAGE_ENGLISH,
        language_selected_at=timezone.now(),
    )


def _arabic_session_with_progress() -> WhatsAppConversationSession:
    save_accepted_fields(VALID_WHATSAPP_NUMBER, dict(IN_PROGRESS_FIELDS))
    return WhatsAppConversationSession.objects.create(
        whatsapp_number=VALID_WHATSAPP_NUMBER,
        language=LANGUAGE_ARABIC,
        language_selected_at=timezone.now(),
    )


# --- Pending picker state ---


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker", return_value="SMpicker000000000000000000000001")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_slash_language_sets_pending_picker_until(mock_extract, mock_send_picker, client):
    _english_session_with_progress()

    response = _post_extract(client, _text_payload(message="/language", message_sid=CHANGE_MESSAGE_SID))

    assert response.status_code == 200
    session = WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER)
    assert session.language_picker_pending_until is not None
    assert session.language_picker_pending_until > timezone.now()
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker", return_value="SMpicker000000000000000000000001")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_slash_language_preserves_saved_language(mock_extract, mock_send_picker, client):
    session = _arabic_session_with_progress()
    previous_language = session.language

    _post_extract(client, _text_payload(message="/language", message_sid=CHANGE_MESSAGE_SID))

    session.refresh_from_db()
    assert session.language == previous_language


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker", return_value="SMpicker000000000000000000000001")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_slash_language_preserves_qualification_progress(mock_extract, mock_send_picker, client):
    _english_session_with_progress()

    _post_extract(client, _text_payload(message="/language", message_sid=CHANGE_MESSAGE_SID))

    assert get_accepted_fields(VALID_WHATSAPP_NUMBER) == IN_PROGRESS_FIELDS


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch(
    "apps.qualification.services.language_gate_service.send_language_picker",
    side_effect=RuntimeError("twilio unavailable"),
)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_picker_send_failure_does_not_set_pending_state(mock_extract, mock_send_picker, client):
    _english_session_with_progress()

    response = _post_extract(client, _text_payload(message="/language", message_sid=CHANGE_MESSAGE_SID))

    assert response.status_code == 502
    session = WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER)
    assert session.language_picker_pending_until is None
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_expired_pending_picker_ignores_exact_english(mock_extract, mock_send_picker, client):
    session = _arabic_session_with_progress()
    session.language_picker_pending_until = timezone.now() - timedelta(seconds=1)
    session.save(update_fields=["language_picker_pending_until"])

    response = _post_extract(client, _text_payload(message="English", message_sid=SELECT_MESSAGE_SID))

    assert response.status_code == 200
    session.refresh_from_db()
    assert session.language == LANGUAGE_ARABIC
    assert session.language_picker_pending_until is not None
    mock_extract.assert_called_once()


# --- Safe body fallback ---


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker", return_value="SMpicker000000000000000000000001")
@patch("apps.qualification.services.transcription_service.VoiceNoteTranscriptionService.transcribe")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_arabic_session_pending_english_body_switches_language(
    mock_extract,
    mock_transcribe,
    mock_send_picker,
    client,
):
    _arabic_session_with_progress()

    _post_extract(client, _text_payload(message="/language", message_sid=CHANGE_MESSAGE_SID))
    response = _post_extract(
        client,
        _text_payload(message="English", message_sid=SELECT_MESSAGE_SID),
    )

    assert response.status_code == 200
    body = response.json()
    session = WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER)
    assert session.language == LANGUAGE_ENGLISH
    assert session.language_picker_pending_until is None
    assert get_accepted_fields(VALID_WHATSAPP_NUMBER) == IN_PROGRESS_FIELDS
    assert body["next_field"] == "referral_source"
    assert body["reply_text"] == get_language_changed_confirmation_message(
        language=LANGUAGE_ENGLISH,
    )
    mock_extract.assert_not_called()
    mock_transcribe.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker", return_value="SMpicker000000000000000000000001")
@patch("apps.qualification.services.transcription_service.VoiceNoteTranscriptionService.transcribe")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_english_session_pending_arabic_body_switches_language(
    mock_extract,
    mock_transcribe,
    mock_send_picker,
    client,
):
    _english_session_with_progress()

    _post_extract(client, _text_payload(message="/language", message_sid=CHANGE_MESSAGE_SID))
    response = _post_extract(
        client,
        _text_payload(message="العربية", message_sid=SELECT_MESSAGE_SID),
    )

    assert response.status_code == 200
    body = response.json()
    session = WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER)
    assert session.language == LANGUAGE_ARABIC
    assert session.language_picker_pending_until is None
    assert get_accepted_fields(VALID_WHATSAPP_NUMBER) == IN_PROGRESS_FIELDS
    assert body["reply_text"] == get_language_changed_confirmation_message(
        language=LANGUAGE_ARABIC,
    )
    mock_extract.assert_not_called()
    mock_transcribe.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter", return_value=QualificationFieldFilterResult(
    accepted_fields={},
    rejected_fields=(),
    human_handoff_requested=False,
))
def test_exact_english_without_pending_does_not_change_arabic_session(mock_extract, mock_send_picker, client):
    _arabic_session_with_progress()

    response = _post_extract(client, _text_payload(message="English", message_sid=SELECT_MESSAGE_SID))

    assert response.status_code == 200
    assert WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER).language == LANGUAGE_ARABIC
    mock_extract.assert_called_once()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter", return_value=QualificationFieldFilterResult(
    accepted_fields={},
    rejected_fields=(),
    human_handoff_requested=False,
))
def test_exact_arabic_without_pending_does_not_change_english_session(mock_extract, mock_send_picker, client):
    _english_session_with_progress()

    response = _post_extract(client, _text_payload(message="العربية", message_sid=SELECT_MESSAGE_SID))

    assert response.status_code == 200
    assert WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER).language == LANGUAGE_ENGLISH
    mock_extract.assert_called_once()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter", return_value=QualificationFieldFilterResult(
    accepted_fields={},
    rejected_fields=(),
    human_handoff_requested=False,
))
def test_sentence_mentioning_english_without_pending_does_not_change_language(
    mock_extract,
    mock_send_picker,
    client,
):
    _arabic_session_with_progress()

    response = _post_extract(
        client,
        _text_payload(message="I need an English website", message_sid=SELECT_MESSAGE_SID),
    )

    assert response.status_code == 200
    assert WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER).language == LANGUAGE_ARABIC
    mock_extract.assert_called_once()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter", return_value=QualificationFieldFilterResult(
    accepted_fields={},
    rejected_fields=(),
    human_handoff_requested=False,
))
def test_sentence_mentioning_arabic_without_pending_does_not_change_language(
    mock_extract,
    mock_send_picker,
    client,
):
    _english_session_with_progress()

    response = _post_extract(
        client,
        _text_payload(message="I need an Arabic website", message_sid=SELECT_MESSAGE_SID),
    )

    assert response.status_code == 200
    assert WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER).language == LANGUAGE_ENGLISH
    mock_extract.assert_called_once()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker", return_value="SMpicker000000000000000000000001")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter", return_value=QualificationFieldFilterResult(
    accepted_fields={},
    rejected_fields=(),
    human_handoff_requested=False,
))
def test_sentence_mentioning_english_while_pending_does_not_change_language(
    mock_extract,
    mock_send_picker,
    client,
):
    _arabic_session_with_progress()
    _post_extract(client, _text_payload(message="/language", message_sid=CHANGE_MESSAGE_SID))

    response = _post_extract(
        client,
        _text_payload(message="I need an English website", message_sid=SELECT_MESSAGE_SID),
    )

    assert response.status_code == 200
    assert WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER).language == LANGUAGE_ARABIC
    mock_extract.assert_called_once()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker", return_value="SMpicker000000000000000000000001")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter", return_value=QualificationFieldFilterResult(
    accepted_fields={},
    rejected_fields=(),
    human_handoff_requested=False,
))
def test_sentence_mentioning_arabic_while_pending_does_not_change_language(
    mock_extract,
    mock_send_picker,
    client,
):
    _english_session_with_progress()
    _post_extract(client, _text_payload(message="/language", message_sid=CHANGE_MESSAGE_SID))

    response = _post_extract(
        client,
        _text_payload(message="Can you make an Arabic landing page?", message_sid=SELECT_MESSAGE_SID),
    )

    assert response.status_code == 200
    assert WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER).language == LANGUAGE_ENGLISH
    mock_extract.assert_called_once()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter", return_value=QualificationFieldFilterResult(
    accepted_fields={},
    rejected_fields=(),
    human_handoff_requested=False,
))
def test_expired_pending_plus_exact_english_does_not_change_arabic_session(
    mock_extract,
    mock_send_picker,
    client,
):
    session = _arabic_session_with_progress()
    session.language_picker_pending_until = timezone.now() - timedelta(seconds=1)
    session.save(update_fields=["language_picker_pending_until"])

    response = _post_extract(client, _text_payload(message="English", message_sid=SELECT_MESSAGE_SID))

    assert response.status_code == 200
    assert WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER).language == LANGUAGE_ARABIC
    mock_extract.assert_called_once()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker", return_value="SMpicker000000000000000000000001")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_whitespace_normalized_english_works_while_pending(mock_extract, mock_send_picker, client):
    _arabic_session_with_progress()
    _post_extract(client, _text_payload(message="/language", message_sid=CHANGE_MESSAGE_SID))

    response = _post_extract(
        client,
        _text_payload(message="   English   ", message_sid=SELECT_MESSAGE_SID),
    )

    assert response.status_code == 200
    assert WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER).language == LANGUAGE_ENGLISH
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker", return_value="SMpicker000000000000000000000001")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_whitespace_normalized_arabic_works_while_pending(mock_extract, mock_send_picker, client):
    _english_session_with_progress()
    _post_extract(client, _text_payload(message="/language", message_sid=CHANGE_MESSAGE_SID))

    response = _post_extract(
        client,
        _text_payload(message="  العربية  ", message_sid=SELECT_MESSAGE_SID),
    )

    assert response.status_code == 200
    assert WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER).language == LANGUAGE_ARABIC
    mock_extract.assert_not_called()


# --- Existing behavior regression ---


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_slash_language_set_en_without_pending(mock_extract, mock_send_picker, client):
    _arabic_session_with_progress()

    response = _post_extract(
        client,
        _text_payload(message="/language set en", message_sid=CHANGE_MESSAGE_SID),
    )

    assert response.status_code == 200
    assert WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER).language == LANGUAGE_ENGLISH
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_slash_language_set_ar_without_pending(mock_extract, mock_send_picker, client):
    _english_session_with_progress()

    response = _post_extract(
        client,
        _text_payload(message="/language set ar", message_sid=CHANGE_MESSAGE_SID),
    )

    assert response.status_code == 200
    assert WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER).language == LANGUAGE_ARABIC
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker", return_value="SMpicker000000000000000000000001")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_button_payload_lang_en_clears_pending_state(mock_extract, mock_send_picker, client):
    _arabic_session_with_progress()
    _post_extract(client, _text_payload(message="/language", message_sid=CHANGE_MESSAGE_SID))

    response = _post_extract(
        client,
        _text_payload(message="English", message_sid=SELECT_MESSAGE_SID, button_payload="lang_en"),
    )

    session = WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER)
    assert session.language == LANGUAGE_ENGLISH
    assert session.language_picker_pending_until is None
    assert response.status_code == 200


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker", return_value="SMpicker000000000000000000000001")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_button_payload_lang_ar_clears_pending_state(mock_extract, mock_send_picker, client):
    _english_session_with_progress()
    _post_extract(client, _text_payload(message="/language", message_sid=CHANGE_MESSAGE_SID))

    response = _post_extract(
        client,
        _text_payload(message="العربية", message_sid=SELECT_MESSAGE_SID, button_payload="lang_ar"),
    )

    session = WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER)
    assert session.language == LANGUAGE_ARABIC
    assert session.language_picker_pending_until is None
    assert response.status_code == 200


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_button_payload_takes_priority_over_conflicting_body(mock_extract, mock_send_picker, client):
    _english_session_with_progress()
    _post_extract(client, _text_payload(message="/language", message_sid=CHANGE_MESSAGE_SID))

    response = _post_extract(
        client,
        _text_payload(
            message="العربية",
            message_sid=SELECT_MESSAGE_SID,
            button_payload="lang_en",
        ),
    )

    assert response.status_code == 200
    assert WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER).language == LANGUAGE_ENGLISH
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker", return_value="SMpicker000000000000000000000001")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_new_customer_language_null_picker_still_works(mock_extract, mock_send_picker, client):
    response = _post_extract(client, _text_payload(message="hello", message_sid=MESSAGE_SID))

    assert response.status_code == 200
    assert response.json()["status"] == "awaiting_language_selection"
    session = WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER)
    assert session.language is None
    assert session.language_picker_pending_until is not None
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker", return_value="SMpicker000000000000000000000001")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_duplicate_message_sid_for_slash_language_does_not_send_picker_twice(
    mock_extract,
    mock_send_picker,
    client,
):
    _english_session_with_progress()
    payload = _text_payload(message="/language", message_sid=CHANGE_MESSAGE_SID)

    first = _post_extract(client, payload)
    second = _post_extract(client, payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    mock_send_picker.assert_called_once()
    assert get_cached_turn_response(CHANGE_MESSAGE_SID) is not None


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker", return_value="SMpicker000000000000000000000001")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_duplicate_message_sid_for_pending_english_selection_is_idempotent(
    mock_extract,
    mock_send_picker,
    client,
):
    _arabic_session_with_progress()
    _post_extract(client, _text_payload(message="/language", message_sid=CHANGE_MESSAGE_SID))

    payload = _text_payload(message="English", message_sid=SELECT_MESSAGE_SID)
    first = _post_extract(client, payload)
    second = _post_extract(client, payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    session = WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER)
    assert session.language == LANGUAGE_ENGLISH
    mock_extract.assert_not_called()


def test_language_picker_pending_timeout_matches_settings():
    assert language_picker_pending_timeout().total_seconds() == 900
