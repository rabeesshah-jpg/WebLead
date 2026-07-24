"""Tests for RenderAudioAPIView."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client, override_settings
from django.urls import reverse

from apps.qualification.tests.internal_api_test_helpers import (
    API_SECRET,
    RENDER_AUDIO_SUCCESS_FIELD_NAMES,
    assert_public_error_contract,
    internal_api_auth_headers,
)
from apps.qualification.whatsapp_audio import (
    FfmpegConversionError,
)

RENDER_ENDPOINT = "/api/internal/qualification/render-audio/"
ROUTE_NAME = "internal-qualification-render-audio"
PUBLIC_MEDIA_BASE_URL = "https://tunnel.example.com"
VALID_PAYLOAD = {
    "text": "Thank you. How did you hear about us?",
    "voice": "F1",
    "lang": "en",
    "request_id": "SM_TEST_001"}
EXPECTED_RESPONSE = {
    "status": "rendered",
    "fallback_to_text": False,
    "conversation_language": "en",
    "media_url": f"{PUBLIC_MEDIA_BASE_URL}/media/whatsapp_voice_replies/test-audio-id/",
    "content_type": "audio/ogg",
    "audio_url": f"{PUBLIC_MEDIA_BASE_URL}/media/whatsapp_voice_replies/test-audio-id/",
    "audio_content_type": "audio/ogg",
    "request_id": "SM_TEST_001"}


@pytest.fixture
def client() -> Client:
    return Client()


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


def test_render_audio_url_and_route_name_resolve():
    assert reverse(ROUTE_NAME) == RENDER_ENDPOINT


@override_settings(N8N_QUALIFICATION_API_SECRET="")
def test_missing_configuration_returns_503_before_auth_check(client):
    response = _post_render(client, VALID_PAYLOAD, secret=None)

    assert response.status_code == 503
    assert response.json() == {"error": "Qualification service is unavailable."}


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL)
def test_missing_secret_returns_403(client):
    response = _post_render(client, VALID_PAYLOAD, secret=None)

    assert response.status_code == 403
    assert response.json() == {"error": "Forbidden."}


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL)
def test_invalid_secret_returns_403(client):
    response = _post_render(client, VALID_PAYLOAD, secret="wrong-secret")

    assert response.status_code == 403
    assert response.json() == {"error": "Forbidden."}


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL)
def test_malformed_json_returns_400(client):
    response = _post_render(client, b"not-json")

    assert response.status_code == 400
    assert response.json() == {"error": "Invalid request."}


@pytest.mark.parametrize("payload", [[VALID_PAYLOAD["text"]], "string-root", 123])
@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL)
def test_non_object_json_root_returns_400(client, payload):
    response = _post_render(client, payload)

    assert response.status_code == 400
    assert response.json() == {"error": "Invalid request."}


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL)
def test_invalid_request_returns_400(client):
    response = _post_render(client, {"voice": "F1", "lang": "en"})

    assert response.status_code == 400
    assert response.json() == {"error": "Invalid request."}


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL, MAX_TTS_TEXT_LENGTH=800)
@patch("apps.qualification.api.views.RenderAudioAPIView.get_service")
def test_valid_request_returns_200_with_contract_body(mock_get_service, client):
    service = MagicMock()
    service.render.return_value = EXPECTED_RESPONSE
    mock_get_service.return_value = service

    response = _post_render(client, VALID_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == RENDER_AUDIO_SUCCESS_FIELD_NAMES
    assert body == EXPECTED_RESPONSE
    assert "detail" not in body
    service.render.assert_called_once()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL)
def test_invalid_secret_error_has_no_detail_key(client):
    response = _post_render(client, VALID_PAYLOAD, secret="wrong-secret")
    assert_public_error_contract(response, status_code=403, body={"error": "Forbidden."})


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL)
@patch("apps.qualification.api.views.RenderAudioAPIView.get_service")
def test_provider_unavailable_returns_text_fallback(mock_get_service, client):
    service = MagicMock()
    service.render.return_value = {
        "status": "text_fallback",
        "fallback_to_text": True,
        "conversation_language": "en",
        "fallback_reason": "english_tts_unavailable",
        "media_url": None,
        "content_type": None,
        "audio_url": None,
        "audio_content_type": None,
        "request_id": "SM_TEST_001"}
    mock_get_service.return_value = service

    response = _post_render(client, VALID_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert body["fallback_to_text"] is True
    assert body["fallback_reason"] == "english_tts_unavailable"


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL)
@patch("apps.qualification.api.views.RenderAudioAPIView.get_service")
def test_processing_failure_returns_text_fallback(mock_get_service, client):
    service = MagicMock()
    service.render.return_value = {
        "status": "text_fallback",
        "fallback_to_text": True,
        "conversation_language": "en",
        "fallback_reason": "english_tts_unavailable",
        "media_url": None,
        "content_type": None,
        "audio_url": None,
        "audio_content_type": None,
        "request_id": "SM_TEST_001"}
    mock_get_service.return_value = service

    response = _post_render(client, VALID_PAYLOAD)

    assert response.status_code == 200
    assert response.json()["fallback_to_text"] is True


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL, MAX_TTS_TEXT_LENGTH=800)
@patch("apps.qualification.api.views.RenderAudioAPIView.get_service")
def test_unexpected_exception_returns_500(mock_get_service, client):
    service = MagicMock()
    service.render.side_effect = RuntimeError("unexpected")
    mock_get_service.return_value = service

    response = _post_render(client, VALID_PAYLOAD)

    assert response.status_code == 500
    assert response.json() == {"error": "Internal server error."}


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL, MAX_TTS_TEXT_LENGTH=10)
def test_excessive_text_returns_400(client):
    response = _post_render(
        client,
        {"text": "this text is definitely too long", "request_id": "SM_TEST_004"},
    )

    assert response.status_code == 400
    assert response.json() == {"error": "Invalid request."}
