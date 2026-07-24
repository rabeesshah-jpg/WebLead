"""Tests for shared internal qualification API authentication."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from django.test import Client, RequestFactory, override_settings

from apps.qualification.internal_auth import (
    QUALIFICATION_SECRET_HEADER_NAME,
    is_internal_qualification_authorized,
)
from apps.qualification.tests.internal_api_test_helpers import (
    API_SECRET,
    INTERNAL_API_SECRET_META_KEY,
    internal_api_auth_headers,
)

pytestmark = pytest.mark.django_db

EXTRACT_ENDPOINT = "/api/internal/qualification/extract/"
RENDER_ENDPOINT = "/api/internal/qualification/render-audio/"
VALID_EXTRACT_PAYLOAD = {
    "message": "I need a new website for a restaurant",
    "whatsapp_number": "+923001234567",
    "input_channel": "whatsapp_text"}
VALID_RENDER_PAYLOAD = {
    "text": "Thank you. How did you hear about us?",
    "voice": "F1",
    "lang": "en",
    "request_id": "SM_TEST_001"}


@pytest.fixture
def client() -> Client:
    return Client()


def _post_json(client: Client, path: str, payload: dict, *, secret: str | None = API_SECRET) -> object:
    return client.post(
        path,
        data=json.dumps(payload),
        content_type="application/json",
        **internal_api_auth_headers(secret=secret),
    )


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_extract_endpoint_accepts_internal_webhook_secret_header(mock_extract, client):
    response = _post_json(client, EXTRACT_ENDPOINT, VALID_EXTRACT_PAYLOAD)

    assert response.status_code == 200
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, PUBLIC_MEDIA_BASE_URL="https://tunnel.example.com")
@patch("apps.qualification.whatsapp_audio.synthesize_wav", return_value=b"RIFF" + b"\x00" * 20)
@patch("apps.qualification.whatsapp_audio.subprocess.run")
def test_render_audio_endpoint_accepts_internal_webhook_secret_header(mock_run, mock_synth, client, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    from pathlib import Path

    def _write_ogg(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"OggS")
        import subprocess

        return subprocess.CompletedProcess(cmd, 0, "", "")

    mock_run.side_effect = _write_ogg

    response = _post_json(client, RENDER_ENDPOINT, VALID_RENDER_PAYLOAD)

    assert response.status_code == 200
    assert response.json()["content_type"] == "audio/ogg"


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_extract_endpoint_rejects_invalid_secret(mock_extract, client):
    response = _post_json(client, EXTRACT_ENDPOINT, VALID_EXTRACT_PAYLOAD, secret="wrong-secret")

    assert response.status_code == 403
    assert response.json() == {"error": "Forbidden."}
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, PUBLIC_MEDIA_BASE_URL="https://tunnel.example.com")
@patch("apps.qualification.whatsapp_audio.synthesize_wav")
def test_render_audio_endpoint_rejects_invalid_secret(mock_synth, client):
    response = _post_json(client, RENDER_ENDPOINT, VALID_RENDER_PAYLOAD, secret="wrong-secret")

    assert response.status_code == 403
    assert response.json() == {"error": "Forbidden."}
    mock_synth.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_extract_endpoint_rejects_missing_secret(mock_extract, client):
    response = _post_json(client, EXTRACT_ENDPOINT, VALID_EXTRACT_PAYLOAD, secret=None)

    assert response.status_code == 403
    assert response.json() == {"error": "Forbidden."}
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, PUBLIC_MEDIA_BASE_URL="https://tunnel.example.com")
@patch("apps.qualification.whatsapp_audio.synthesize_wav")
def test_render_audio_endpoint_rejects_missing_secret(mock_synth, client):
    response = _post_json(client, RENDER_ENDPOINT, VALID_RENDER_PAYLOAD, secret=None)

    assert response.status_code == 403
    assert response.json() == {"error": "Forbidden."}
    mock_synth.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
def test_header_case_variations_are_accepted():
    factory = RequestFactory()
    request = factory.post("/", HTTP_X_INTERNAL_WEBHOOK_SECRET=API_SECRET)

    for header_name in (
        "X-Internal-Webhook-Secret",
        "x-internal-webhook-secret",
        "X-INTERNAL-WEBHOOK-SECRET",
    ):
        assert request.headers.get(header_name) == API_SECRET

    assert is_internal_qualification_authorized(request) is True


def test_auth_helper_uses_standard_meta_key():
    assert INTERNAL_API_SECRET_META_KEY == "HTTP_X_INTERNAL_WEBHOOK_SECRET"
    assert QUALIFICATION_SECRET_HEADER_NAME == "X-Internal-Webhook-Secret"
