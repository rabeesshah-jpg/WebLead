"""Tests for language-aware Deepgram voice-note routing."""

from __future__ import annotations

import json
import logging
from unittest.mock import ANY, patch

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from apps.qualification.conversation_state import clear_conversations
from apps.qualification.domain.deepgram_config import get_deepgram_transcription_config
from apps.qualification.domain.language_selection import LANGUAGE_ARABIC, LANGUAGE_ENGLISH
from apps.qualification.message_idempotency import clear_message_sid_cache, get_cached_turn_response
from apps.qualification.models import QualificationFieldFilterResult, WhatsAppConversationSession
from apps.qualification.tests.internal_api_test_helpers import (
    API_SECRET,
    MOCK_VOICE_AUDIO_DOWNLOAD,
    internal_api_auth_headers,
)
from apps.qualification.tests.test_internal_extract_endpoint import (
    SAMPLE_FILTER_RESULT,
    VOICE_TRANSCRIPT,
)

pytestmark = [pytest.mark.language_gate, pytest.mark.django_db]

ENDPOINT_PATH = "/api/internal/qualification/extract/"
VALID_WHATSAPP_NUMBER = "+923001234567"
VOICE_MESSAGE_SID = "MM0cc5a1d9e22bf9850ca24261ee23ce90"
WAHA_MEDIA_URL = "https://waha.example.com/api/files/true_923246271149@c.us_VOICE001.ogg"

DEEPGRAM_SETTINGS = {
    "N8N_QUALIFICATION_API_SECRET": API_SECRET,
    "WAHA_BASE_URL": "https://waha.example.com",
    "WAHA_API_KEY": "test-waha-api-key",
    "DEEPGRAM_API_KEY": "test-deepgram-api-key",
    "DEEPGRAM_MODEL": "nova-2",
    "DEEPGRAM_LANGUAGE": "en",
    "DEEPGRAM_ARABIC_MODEL": "nova-3",
    "DEEPGRAM_ARABIC_LANGUAGE": "ar"}


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


def _voice_payload(*, message_sid: str = VOICE_MESSAGE_SID) -> dict:
    return {
        "message": "",
        "whatsapp_number": VALID_WHATSAPP_NUMBER,
        "input_channel": "whatsapp_voice_note",
        "message_sid": message_sid,
        "media_url": WAHA_MEDIA_URL,
        "media_content_type": "audio/ogg"}


def _post_extract(client: Client, payload: dict) -> object:
    return client.post(
        ENDPOINT_PATH,
        data=json.dumps(payload),
        content_type="application/json",
        **internal_api_auth_headers(secret=API_SECRET),
    )


def _english_session() -> WhatsAppConversationSession:
    return WhatsAppConversationSession.objects.create(
        whatsapp_number=VALID_WHATSAPP_NUMBER,
        language=LANGUAGE_ENGLISH,
        language_selected_at=timezone.now(),
    )


def _arabic_session() -> WhatsAppConversationSession:
    return WhatsAppConversationSession.objects.create(
        whatsapp_number=VALID_WHATSAPP_NUMBER,
        language=LANGUAGE_ARABIC,
        language_selected_at=timezone.now(),
    )


@override_settings(**DEEPGRAM_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker", return_value="SMpicker000000000000000000000001")
@patch("apps.qualification.core.legacy_compat.download_twilio_media")
@patch("apps.qualification.core.legacy_compat.transcribe_audio")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_new_customer_voice_note_skips_media_and_deepgram(
    mock_extract,
    mock_transcribe,
    mock_download,
    mock_send_picker,
    client,
):
    response = _post_extract(client, _voice_payload())

    assert response.status_code == 200
    assert response.json()["status"] == "awaiting_language_selection"
    mock_send_picker.assert_called_once()
    mock_download.assert_not_called()
    mock_transcribe.assert_not_called()
    mock_extract.assert_not_called()


@override_settings(**DEEPGRAM_SETTINGS)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.core.legacy_compat.transcribe_audio", return_value=VOICE_TRANSCRIPT)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter", return_value=SAMPLE_FILTER_RESULT)
def test_english_voice_note_uses_english_deepgram_configuration(
    mock_extract,
    mock_transcribe,
    mock_download,
    client,
):
    _english_session()
    message_sid = "MM0cc5a1d9e22bf9850ca24261ee23ce92"

    response = _post_extract(client, _voice_payload(message_sid=message_sid))

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_language"] == LANGUAGE_ENGLISH
    assert body["reply_mode"] == "voice"
    assert body["transcript"] == VOICE_TRANSCRIPT
    mock_download.assert_called_once()
    english_config = get_deepgram_transcription_config(conversation_language=LANGUAGE_ENGLISH)
    mock_transcribe.assert_called_once_with(
        ANY,
        content_type="audio/ogg",
        transcription_config=english_config,
    )
    mock_extract.assert_not_called()


@override_settings(**DEEPGRAM_SETTINGS)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.core.legacy_compat.transcribe_audio", return_value="أحتاج موقعًا جديدًا")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter", return_value=QualificationFieldFilterResult(
    accepted_fields={"project_type": "new_website"},
    rejected_fields=(),
    human_handoff_requested=False,
))
def test_arabic_voice_note_uses_arabic_deepgram_configuration(
    mock_extract,
    mock_transcribe,
    mock_download,
    client,
):
    _arabic_session()
    arabic_transcript = "أحتاج موقعًا جديدًا"
    message_sid = "MM0cc5a1d9e22bf9850ca24261ee23ce93"

    response = _post_extract(client, _voice_payload(message_sid=message_sid))

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_language"] == LANGUAGE_ARABIC
    assert body["transcript"] == arabic_transcript
    arabic_config = get_deepgram_transcription_config(conversation_language=LANGUAGE_ARABIC)
    assert arabic_config.model == "nova-3"
    assert arabic_config.language == "ar"
    mock_transcribe.assert_called_once_with(
        ANY,
        content_type="audio/ogg",
        transcription_config=arabic_config,
    )
    english_config = get_deepgram_transcription_config(conversation_language=LANGUAGE_ENGLISH)
    assert mock_transcribe.call_args.kwargs["transcription_config"].model != english_config.model
    assert mock_transcribe.call_args.kwargs["transcription_config"].language != english_config.language
    mock_extract.assert_called_once_with(
        customer_message=arabic_transcript,
        known_whatsapp_number=VALID_WHATSAPP_NUMBER,
        phone_confirmation_question_asked=False,
        message_sid=message_sid,
        collected_fields={},
        conversation_history=[],
        conversation_language=LANGUAGE_ARABIC,
    )


@override_settings(**DEEPGRAM_SETTINGS)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.core.legacy_compat.transcribe_audio", return_value=VOICE_TRANSCRIPT)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter", return_value=SAMPLE_FILTER_RESULT)
def test_duplicate_voice_message_sid_does_not_retranscribe(
    mock_extract,
    mock_transcribe,
    mock_download,
    client,
):
    _english_session()
    duplicate_sid = "MM0cc5a1d9e22bf9850ca24261ee23ce91"
    payload = _voice_payload(message_sid=duplicate_sid)

    first = _post_extract(client, payload)
    second = _post_extract(client, payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    mock_download.assert_called_once()
    mock_transcribe.assert_called_once()
    mock_extract.assert_not_called()
    assert get_cached_turn_response(duplicate_sid) is not None


@override_settings(**{**DEEPGRAM_SETTINGS, "DEEPGRAM_ARABIC_MODEL": ""})
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.core.legacy_compat.transcribe_audio")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_missing_arabic_deepgram_configuration_returns_503_without_openrouter(
    mock_extract,
    mock_transcribe,
    mock_download,
    client,
    caplog,
):
    _arabic_session()
    config_sid = "MM0cc5a1d9e22bf9850ca24261ee23ce95"

    with caplog.at_level(logging.ERROR, logger="apps.qualification"):
        response = _post_extract(client, _voice_payload(message_sid=config_sid))

    assert response.status_code == 503
    assert response.json() == {"error": "Qualification service is unavailable."}
    mock_download.assert_not_called()
    mock_transcribe.assert_not_called()
    mock_extract.assert_not_called()
    assert "qualification_voice_deepgram_configuration_error" in caplog.text


@override_settings(**DEEPGRAM_SETTINGS)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.core.legacy_compat.transcribe_audio")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_arabic_deepgram_request_failure_returns_controlled_error_without_english_fallback(
    mock_extract,
    mock_transcribe,
    mock_download,
    client,
    caplog,
):
    from apps.qualification.deepgram_client import DeepgramRequestError

    mock_transcribe.side_effect = DeepgramRequestError("Deepgram request failed")
    _arabic_session()
    failure_sid = "MM0cc5a1d9e22bf9850ca24261ee23ce94"

    with caplog.at_level(logging.ERROR, logger="apps.qualification"):
        response = _post_extract(client, _voice_payload(message_sid=failure_sid))

    assert response.status_code == 502
    assert response.json() == {"error": "Voice transcription failed."}
    mock_transcribe.assert_called_once()
    arabic_config = get_deepgram_transcription_config(conversation_language=LANGUAGE_ARABIC)
    assert mock_transcribe.call_args.kwargs["transcription_config"] == arabic_config
    mock_extract.assert_not_called()
    assert "deepgram_transcription_failed" in caplog.text
