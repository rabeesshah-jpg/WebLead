"""Tests for Arabic Supertonic TTS routing and text fallback."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client, override_settings

from apps.qualification.models import WhatsAppConversationSession
from apps.qualification.render_audio_idempotency import clear_render_audio_cache
from apps.qualification.tests.internal_api_test_helpers import (
    API_SECRET,
    internal_api_auth_headers,
)
from apps.qualification.supertonic_client import SupertonicRequestError
from apps.qualification.whatsapp_audio import (
    FfmpegConversionError,
)

pytestmark = pytest.mark.django_db

RENDER_ENDPOINT = "/api/internal/qualification/render-audio/"
PUBLIC_MEDIA_BASE_URL = "https://tunnel.example.com"
ARABIC_WHATSAPP_NUMBER = "+923001234567"
ARABIC_REPLY_TEXT = "شكرًا لك. كيف سمعت عنا؟"
SAMPLE_WAV = b"RIFF\x24\x08\x00\x00WAVEfmt " + b"\x00" * 16
SAMPLE_OGG = b"OggS" + b"\x00" * 64


@pytest.fixture
def media_root(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture(autouse=True)
def _reset_render_cache():
    clear_render_audio_cache()
    yield
    clear_render_audio_cache()


@pytest.fixture(autouse=True)
def _reset_sessions():
    WhatsAppConversationSession.objects.all().delete()
    yield
    WhatsAppConversationSession.objects.all().delete()


def _post_render(
    client: Client,
    payload: object,
    *,
    secret: str | None = API_SECRET,
):
    headers = {"content_type": "application/json", **internal_api_auth_headers(secret=secret)}
    body = json.dumps(payload) if not isinstance(payload, (bytes, str)) else payload
    if isinstance(body, str):
        body = body.encode("utf-8")
    return client.post(RENDER_ENDPOINT, data=body, **headers)


def _arabic_session() -> WhatsAppConversationSession:
    return WhatsAppConversationSession.objects.create(
        whatsapp_number=ARABIC_WHATSAPP_NUMBER,
        language=WhatsAppConversationSession.Language.ARABIC,
    )


@override_settings(
    N8N_QUALIFICATION_API_SECRET=API_SECRET,
    PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL,
    MAX_TTS_TEXT_LENGTH=800,
    SUPERTONIC_ARABIC_ENABLED=True,
    SUPERTONIC_ARABIC_VOICE="M1",
)
@patch("apps.qualification.whatsapp_audio.subprocess.run")
@patch("apps.qualification.whatsapp_audio.synthesize_wav", return_value=SAMPLE_WAV)
def test_arabic_render_succeeds_when_enabled(mock_synthesize, mock_ffmpeg, client, media_root, settings):
    from pathlib import Path
    import subprocess

    def _fake_ffmpeg(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(SAMPLE_OGG)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    mock_ffmpeg.side_effect = _fake_ffmpeg
    _arabic_session()

    response = _post_render(
        client,
        {
            "text": ARABIC_REPLY_TEXT,
            "request_id": "SM_ARABIC_001",
            "whatsapp_number": ARABIC_WHATSAPP_NUMBER,
            "lang": "en"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rendered"
    assert body["fallback_to_text"] is False
    assert body["conversation_language"] == "ar"
    assert body["media_url"] == body["audio_url"]
    assert body["content_type"] == "audio/ogg"
    mock_synthesize.assert_called_once_with(
        text=ARABIC_REPLY_TEXT,
        voice="M1",
        lang="ar",
    )


@override_settings(
    N8N_QUALIFICATION_API_SECRET=API_SECRET,
    PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL,
    MAX_TTS_TEXT_LENGTH=800,
    SUPERTONIC_ARABIC_ENABLED=False,
    SUPERTONIC_ARABIC_VOICE="M1",
)
@patch("apps.qualification.whatsapp_audio.synthesize_wav")
def test_arabic_disabled_returns_text_fallback(mock_synthesize, client, media_root):
    _arabic_session()

    response = _post_render(
        client,
        {
            "text": ARABIC_REPLY_TEXT,
            "request_id": "SM_ARABIC_002",
            "whatsapp_number": ARABIC_WHATSAPP_NUMBER},
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "text_fallback",
        "fallback_to_text": True,
        "conversation_language": "ar",
        "fallback_reason": "arabic_tts_unavailable",
        "media_url": None,
        "content_type": None,
        "audio_url": None,
        "audio_content_type": None,
        "request_id": "SM_ARABIC_002"}
    mock_synthesize.assert_not_called()


@override_settings(
    N8N_QUALIFICATION_API_SECRET=API_SECRET,
    PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL,
    MAX_TTS_TEXT_LENGTH=800,
    SUPERTONIC_ARABIC_ENABLED=True,
    SUPERTONIC_ARABIC_VOICE="",
)
@patch("apps.qualification.whatsapp_audio.synthesize_wav")
def test_missing_arabic_voice_returns_text_fallback(mock_synthesize, client, media_root):
    _arabic_session()

    response = _post_render(
        client,
        {
            "text": ARABIC_REPLY_TEXT,
            "request_id": "SM_ARABIC_003",
            "whatsapp_number": ARABIC_WHATSAPP_NUMBER},
    )

    assert response.status_code == 200
    assert response.json()["fallback_to_text"] is True
    assert response.json()["fallback_reason"] == "arabic_tts_unavailable"
    mock_synthesize.assert_not_called()


@override_settings(
    N8N_QUALIFICATION_API_SECRET=API_SECRET,
    PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL,
    MAX_TTS_TEXT_LENGTH=800,
    SUPERTONIC_ARABIC_ENABLED=True,
    SUPERTONIC_ARABIC_VOICE="M1",
)
@patch(
    "apps.qualification.whatsapp_audio.synthesize_wav",
    side_effect=SupertonicRequestError("Supertonic request failed"),
)
def test_arabic_upstream_failure_returns_text_fallback(mock_synthesize, client, media_root):
    _arabic_session()

    response = _post_render(
        client,
        {
            "text": ARABIC_REPLY_TEXT,
            "request_id": "SM_ARABIC_004",
            "whatsapp_number": ARABIC_WHATSAPP_NUMBER},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["fallback_to_text"] is True
    assert body["fallback_reason"] == "arabic_tts_unavailable"
    assert "Supertonic" not in response.content.decode("utf-8")


@override_settings(
    N8N_QUALIFICATION_API_SECRET=API_SECRET,
    PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL,
    MAX_TTS_TEXT_LENGTH=800,
    SUPERTONIC_ARABIC_ENABLED=True,
    SUPERTONIC_ARABIC_VOICE="M1",
)
@patch(
    "apps.qualification.whatsapp_audio.convert_wav_to_ogg",
    side_effect=FfmpegConversionError("ffmpeg conversion failed"),
)
@patch("apps.qualification.whatsapp_audio.synthesize_wav", return_value=SAMPLE_WAV)
def test_arabic_audio_validation_failure_returns_text_fallback(
    mock_synthesize,
    mock_convert,
    client,
    media_root,
):
    _arabic_session()

    response = _post_render(
        client,
        {
            "text": ARABIC_REPLY_TEXT,
            "request_id": "SM_ARABIC_005",
            "whatsapp_number": ARABIC_WHATSAPP_NUMBER},
    )

    assert response.status_code == 200
    assert response.json()["fallback_to_text"] is True
    assert response.json()["fallback_reason"] == "arabic_tts_unavailable"


@override_settings(
    N8N_QUALIFICATION_API_SECRET=API_SECRET,
    PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL,
    MAX_TTS_TEXT_LENGTH=800,
)
@patch("apps.qualification.api.views.RenderAudioAPIView.get_service")
def test_legacy_english_request_without_whatsapp_number_still_renders(mock_get_service, client):
    service = MagicMock()
    service.render.return_value = {
        "status": "rendered",
        "fallback_to_text": False,
        "conversation_language": "en",
        "media_url": f"{PUBLIC_MEDIA_BASE_URL}/media/whatsapp_voice_replies/test/",
        "content_type": "audio/ogg",
        "audio_url": f"{PUBLIC_MEDIA_BASE_URL}/media/whatsapp_voice_replies/test/",
        "audio_content_type": "audio/ogg",
        "request_id": "SM_TEST_001"}
    mock_get_service.return_value = service

    response = _post_render(
        client,
        {
            "text": "Thank you. How did you hear about us?",
            "voice": "F1",
            "lang": "en",
            "request_id": "SM_TEST_001"},
    )

    assert response.status_code == 200
    service.render.assert_called_once()


@override_settings(
    N8N_QUALIFICATION_API_SECRET=API_SECRET,
    PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL,
    MAX_TTS_TEXT_LENGTH=800,
    SUPERTONIC_ARABIC_ENABLED=True,
    SUPERTONIC_ARABIC_VOICE="M1",
)
@patch("apps.qualification.whatsapp_audio.subprocess.run")
@patch("apps.qualification.whatsapp_audio.synthesize_wav", return_value=SAMPLE_WAV)
def test_duplicate_request_id_does_not_render_twice(mock_synthesize, mock_ffmpeg, client, media_root):
    from pathlib import Path
    import subprocess

    def _fake_ffmpeg(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(SAMPLE_OGG)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    mock_ffmpeg.side_effect = _fake_ffmpeg
    _arabic_session()
    payload = {
        "text": ARABIC_REPLY_TEXT,
        "request_id": "SM_ARABIC_006",
        "whatsapp_number": ARABIC_WHATSAPP_NUMBER}

    first = _post_render(client, payload)
    second = _post_render(client, payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    mock_synthesize.assert_called_once()
