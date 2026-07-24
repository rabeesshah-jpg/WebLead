"""Tests for internal render-audio and public WhatsApp voice media endpoints."""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from django.test import Client, override_settings

from apps.qualification.supertonic_client import (
    SupertonicRequestError,
    SupertonicResponseError,
)
from apps.qualification.whatsapp_audio import (
    FfmpegConversionError,
    cleanup_expired_audio_files,
    convert_wav_to_ogg,
    find_audio_file,
    render_whatsapp_voice_reply,
    whatsapp_voice_replies_root,
)

from apps.qualification.render_audio_idempotency import clear_render_audio_cache
from apps.qualification.tests.internal_api_test_helpers import (
    API_SECRET,
    internal_api_auth_headers,
)

RENDER_ENDPOINT = "/api/internal/qualification/render-audio/"
PUBLIC_MEDIA_BASE_URL = "https://tunnel.example.com"
SAMPLE_WAV = b"RIFF\x24\x08\x00\x00WAVEfmt " + b"\x00" * 16
SAMPLE_OGG = b"OggS" + b"\x00" * 64


@pytest.fixture
def client() -> Client:
    clear_render_audio_cache()
    return Client()


@pytest.fixture(autouse=True)
def _reset_render_cache():
    clear_render_audio_cache()
    yield
    clear_render_audio_cache()


@pytest.fixture
def media_root(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def _post_render(
    client: Client,
    payload: object,
    *,
    secret: str | None = API_SECRET,
) -> object:
    headers: dict[str, str] = {"content_type": "application/json", **internal_api_auth_headers(secret=secret)}
    body = json.dumps(payload) if not isinstance(payload, (bytes, str)) else payload
    if isinstance(body, str):
        body = body.encode("utf-8")
    return client.post(RENDER_ENDPOINT, data=body, **headers)


def _fake_ffmpeg_success(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    output_path = Path(cmd[-1])
    output_path.write_bytes(SAMPLE_OGG)
    return subprocess.CompletedProcess(cmd, 0, "", "")


@override_settings(
    N8N_QUALIFICATION_API_SECRET=API_SECRET,
    PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL,
    MAX_TTS_TEXT_LENGTH=800,
)
@patch("apps.qualification.whatsapp_audio.subprocess.run", side_effect=_fake_ffmpeg_success)
@patch("apps.qualification.whatsapp_audio.synthesize_wav", return_value=SAMPLE_WAV)
def test_valid_request_produces_media_url_with_audio_ogg(
    mock_synthesize,
    mock_ffmpeg,
    client,
    media_root,
):
    response = _post_render(
        client,
        {
            "text": "Thank you. How did you hear about us?",
            "voice": "F1",
            "lang": "en",
            "request_id": "SM_TEST_001"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rendered"
    assert body["fallback_to_text"] is False
    assert body["conversation_language"] == "en"
    assert body["content_type"] == "audio/ogg"
    assert body["request_id"] == "SM_TEST_001"
    assert body["media_url"].startswith(
        f"{PUBLIC_MEDIA_BASE_URL}/media/whatsapp_voice_replies/",
    )
    assert body["media_url"].endswith("/")

    audio_id = body["media_url"].rstrip("/").split("/")[-1]
    uuid.UUID(audio_id)
    stored_path = find_audio_file(audio_id)
    assert stored_path is not None
    assert stored_path.name == f"{audio_id}.ogg"
    assert "SM_TEST_001" not in stored_path.name
    assert stored_path.read_bytes() == SAMPLE_OGG
    mock_synthesize.assert_called_once_with(
        text="Thank you. How did you hear about us?",
        voice="F1",
        lang="en",
    )
    mock_ffmpeg.assert_called_once()
    ffmpeg_cmd = mock_ffmpeg.call_args.args[0]
    assert ffmpeg_cmd[0] == "ffmpeg"
    assert "-c:a" in ffmpeg_cmd and "libopus" in ffmpeg_cmd
    assert "shell" not in mock_ffmpeg.call_args.kwargs


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL)
@patch("apps.qualification.whatsapp_audio.synthesize_wav", return_value=SAMPLE_WAV)
def test_invalid_internal_secret_is_rejected(mock_synthesize, client, media_root):
    response = _post_render(
        client,
        {"text": "Hello there", "request_id": "SM_TEST_002"},
        secret="wrong-secret",
    )

    assert response.status_code == 403
    assert response.json() == {"error": "Forbidden."}
    mock_synthesize.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL)
@patch("apps.qualification.whatsapp_audio.synthesize_wav", return_value=SAMPLE_WAV)
def test_blank_text_returns_skipped_empty_without_audio(mock_synthesize, client, media_root):
    response = _post_render(client, {"text": "   ", "request_id": "SM_TEST_003"})

    assert response.status_code == 200
    assert response.json()["status"] == "skipped_empty"
    assert response.json()["media_url"] is None
    mock_synthesize.assert_not_called()


@override_settings(
    N8N_QUALIFICATION_API_SECRET=API_SECRET,
    PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL,
    MAX_TTS_TEXT_LENGTH=10,
)
@patch("apps.qualification.whatsapp_audio.synthesize_wav", return_value=SAMPLE_WAV)
def test_excessive_text_is_rejected(mock_synthesize, client, media_root):
    response = _post_render(
        client,
        {"text": "this text is definitely too long", "request_id": "SM_TEST_004"},
    )

    assert response.status_code == 400
    assert response.json() == {"error": "Invalid request."}
    mock_synthesize.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL)
@patch(
    "apps.qualification.whatsapp_audio.synthesize_wav",
    side_effect=SupertonicRequestError("Supertonic request failed"),
)
def test_supertonic_failure_returns_safe_text_fallback(mock_synthesize, client, media_root):
    response = _post_render(client, {"text": "Hello", "request_id": "SM_TEST_005"})

    assert response.status_code == 200
    body = response.json()
    assert body["fallback_to_text"] is True
    assert body["fallback_reason"] == "english_tts_unavailable"
    response_text = response.content.decode("utf-8")
    assert "Supertonic" not in response_text


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL)
@patch(
    "apps.qualification.whatsapp_audio.synthesize_wav",
    side_effect=SupertonicResponseError("Supertonic audio response is empty"),
)
def test_supertonic_empty_audio_returns_safe_text_fallback(mock_synthesize, client, media_root):
    response = _post_render(client, {"text": "Hello", "request_id": "SM_TEST_006"})

    assert response.status_code == 200
    assert response.json()["fallback_to_text"] is True


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL)
@patch(
    "apps.qualification.whatsapp_audio.convert_wav_to_ogg",
    side_effect=FfmpegConversionError("ffmpeg conversion failed"),
)
@patch("apps.qualification.whatsapp_audio.synthesize_wav", return_value=SAMPLE_WAV)
def test_ffmpeg_failure_returns_safe_text_fallback(mock_synthesize, mock_convert, client, media_root):
    response = _post_render(client, {"text": "Hello", "request_id": "SM_TEST_007"})

    assert response.status_code == 200
    body = response.json()
    assert body["fallback_to_text"] is True
    assert body["fallback_reason"] == "english_tts_unavailable"
    response_text = response.content.decode("utf-8")
    assert "ffmpeg" not in response_text


@override_settings(
    N8N_QUALIFICATION_API_SECRET=API_SECRET,
    PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL,
)
@patch("apps.qualification.whatsapp_audio.subprocess.run", side_effect=_fake_ffmpeg_success)
@patch("apps.qualification.whatsapp_audio.synthesize_wav", return_value=SAMPLE_WAV)
def test_public_get_returns_audio_ogg(mock_synthesize, mock_ffmpeg, client, media_root):
    render_response = _post_render(client, {"text": "Hello", "request_id": "SM_TEST_008"})
    media_url = render_response.json()["media_url"]
    public_path = media_url.replace(PUBLIC_MEDIA_BASE_URL, "")

    response = client.get(public_path)

    assert response.status_code == 200
    assert response["Content-Type"] == "audio/ogg"
    assert b"".join(response.streaming_content) == SAMPLE_OGG


@override_settings(
    N8N_QUALIFICATION_API_SECRET=API_SECRET,
    PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL,
)
@patch("apps.qualification.whatsapp_audio.subprocess.run", side_effect=_fake_ffmpeg_success)
@patch("apps.qualification.whatsapp_audio.synthesize_wav", return_value=SAMPLE_WAV)
def test_public_head_returns_audio_ogg_and_content_length(
    mock_synthesize,
    mock_ffmpeg,
    client,
    media_root,
):
    render_response = _post_render(client, {"text": "Hello", "request_id": "SM_TEST_009"})
    media_url = render_response.json()["media_url"]
    public_path = media_url.replace(PUBLIC_MEDIA_BASE_URL, "")

    response = client.head(public_path)

    assert response.status_code == 200
    assert response["Content-Type"] == "audio/ogg"
    assert response["Content-Length"] == str(len(SAMPLE_OGG))
    assert not response.content


@override_settings(
    N8N_QUALIFICATION_API_SECRET=API_SECRET,
    PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL,
)
@patch("apps.qualification.whatsapp_audio.subprocess.run", side_effect=_fake_ffmpeg_success)
@patch("apps.qualification.whatsapp_audio.synthesize_wav", return_value=SAMPLE_WAV)
def test_public_endpoint_does_not_require_internal_secret(
    mock_synthesize,
    mock_ffmpeg,
    client,
    media_root,
):
    render_response = _post_render(client, {"text": "Hello", "request_id": "SM_TEST_010"})
    media_url = render_response.json()["media_url"]
    public_path = media_url.replace(PUBLIC_MEDIA_BASE_URL, "")

    response = client.get(public_path)

    assert response.status_code == 200
    assert "HTTP_X_INTERNAL_WEBHOOK_SECRET" not in response


@override_settings(
    N8N_QUALIFICATION_API_SECRET=API_SECRET,
    PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL,
    WHATSAPP_AUDIO_TTL_SECONDS=3600,
)
@patch("apps.qualification.whatsapp_audio.subprocess.run", side_effect=_fake_ffmpeg_success)
@patch("apps.qualification.whatsapp_audio.synthesize_wav", return_value=SAMPLE_WAV)
def test_generated_filenames_are_uuid_based_not_request_id(
    mock_synthesize,
    mock_ffmpeg,
    client,
    media_root,
):
    response = _post_render(
        client,
        {
            "text": "Hello",
            "request_id": "SM_TEST_011"},
    )

    audio_id = response.json()["media_url"].rstrip("/").split("/")[-1]
    assert audio_id != "SM_TEST_011"
    uuid.UUID(audio_id)

    for path in whatsapp_voice_replies_root().glob("**/*"):
        assert "SM_TEST_011" not in path.name


@override_settings(WHATSAPP_AUDIO_TTL_SECONDS=60)
def test_expired_files_are_removed(media_root):
    output_dir = whatsapp_voice_replies_root() / "2020" / "01" / "01"
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_id = str(uuid.uuid4())
    stale_file = output_dir / f"{audio_id}.ogg"
    stale_file.write_bytes(SAMPLE_OGG)

    expired_time = time.time() - 120
    os.utime(stale_file, (expired_time, expired_time))

    removed = cleanup_expired_audio_files()

    assert removed == 1
    assert not stale_file.exists()


@override_settings(WHATSAPP_AUDIO_TTL_SECONDS=3600)
@patch("apps.qualification.whatsapp_audio.subprocess.run", side_effect=_fake_ffmpeg_success)
@patch("apps.qualification.whatsapp_audio.synthesize_wav", return_value=SAMPLE_WAV)
def test_expired_public_media_returns_not_found(mock_synthesize, mock_ffmpeg, client, media_root):
    audio_id, stored_path = render_whatsapp_voice_reply(text="Hello", voice="F1", lang="en")

    expired_time = time.time() - 7200
    os.utime(stored_path, (expired_time, expired_time))

    response = client.get(f"/media/whatsapp_voice_replies/{audio_id}/")

    assert response.status_code == 404
    assert not stored_path.exists()


def test_convert_wav_to_ogg_uses_argument_list_only(tmp_path):
    wav_path = tmp_path / "input.wav"
    ogg_path = tmp_path / "output.ogg"
    wav_path.write_bytes(SAMPLE_WAV)

    with patch("apps.qualification.whatsapp_audio.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")
        ogg_path.write_bytes(SAMPLE_OGG)
        convert_wav_to_ogg(wav_path=wav_path, ogg_path=ogg_path)

    mock_run.assert_called_once()
    assert mock_run.call_args.kwargs.get("shell") is not True
    cmd = mock_run.call_args.args[0]
    assert cmd[0] == "ffmpeg"
    assert str(wav_path) in cmd
    assert str(ogg_path) in cmd
