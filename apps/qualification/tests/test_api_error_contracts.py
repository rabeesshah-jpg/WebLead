"""Cross-endpoint public error contract guarantees for internal qualification APIs."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client, override_settings

from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.render_audio_idempotency import clear_render_audio_cache
from apps.qualification.models import QualificationFieldFilterResult, RejectedQualificationField
from apps.qualification.openrouter_client import OpenRouterConfigurationError
from apps.qualification.qualification_turn import (
    QualificationServiceRequestError,
    QualificationServiceUnavailableError,
)
from apps.qualification.tests.internal_api_test_helpers import (
    API_SECRET,
    ERROR_CONTRACT_400,
    ERROR_CONTRACT_403,
    ERROR_CONTRACT_500,
    ERROR_CONTRACT_502,
    ERROR_CONTRACT_502_LLM,
    ERROR_CONTRACT_503,
    MOCK_VOICE_AUDIO_BYTES,
    MOCK_VOICE_AUDIO_DOWNLOAD,
    OPENROUTER_FALLBACK_MESSAGE,
    assert_public_error_contract,
    internal_api_auth_headers,
)
from apps.qualification.tests.test_extract_serializers import N8N_TEXT_PAYLOAD, N8N_VOICE_PAYLOAD
from apps.qualification.whatsapp_audio import (
    RenderAudioProcessingError,
    RenderAudioServiceUnavailableError,
)

pytestmark = pytest.mark.django_db

EXTRACT_ENDPOINT = "/api/internal/qualification/extract/"
RENDER_ENDPOINT = "/api/internal/qualification/render-audio/"
RENDER_PAYLOAD = {
    "text": "Thank you. How did you hear about us?",
    "voice": "F1",
    "lang": "en",
    "request_id": "SM_TEST_001",
}

SAMPLE_FILTER_RESULT = QualificationFieldFilterResult(
    accepted_fields={"project_type": "new_website", "requirements": "website for a restaurant"},
    rejected_fields=(RejectedQualificationField(field_name="referral_source", reason="null value"),),
    human_handoff_requested=False,
)


@pytest.fixture
def client() -> Client:
    clear_message_sid_cache()
    return Client()


@pytest.fixture(autouse=True)
def _reset_idempotency_cache():
    clear_message_sid_cache()
    clear_render_audio_cache()
    yield
    clear_message_sid_cache()
    clear_render_audio_cache()


def _post_json(client: Client, path: str, payload: object, *, secret: str | None = API_SECRET):
    headers: dict[str, str] = {"content_type": "application/json", **internal_api_auth_headers(secret=secret)}
    body = json.dumps(payload) if not isinstance(payload, (bytes, str)) else payload
    if isinstance(body, str):
        body = body.encode("utf-8")
    return client.post(path, data=body, **headers)


@pytest.mark.parametrize(
    ("path", "payload_factory"),
    [
        (EXTRACT_ENDPOINT, lambda: {"message": "hello", "whatsapp_number": "+923001234567"}),
        (RENDER_ENDPOINT, lambda: dict(RENDER_PAYLOAD)),
    ],
)
@override_settings(N8N_QUALIFICATION_API_SECRET="")
def test_blank_configured_secret_returns_503_before_permission_check(client, path, payload_factory):
    response = _post_json(client, path, payload_factory(), secret=None)
    assert_public_error_contract(response, status_code=503, body=ERROR_CONTRACT_503)


@pytest.mark.parametrize(
    ("path", "payload_factory"),
    [
        (EXTRACT_ENDPOINT, lambda: {"message": "hello", "whatsapp_number": "+923001234567"}),
        (RENDER_ENDPOINT, lambda: dict(RENDER_PAYLOAD)),
    ],
)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_configured_secret_with_missing_header_returns_403(mock_extract, client, path, payload_factory):
    response = _post_json(client, path, payload_factory(), secret=None)
    assert_public_error_contract(response, status_code=403, body=ERROR_CONTRACT_403)
    if path == EXTRACT_ENDPOINT:
        mock_extract.assert_not_called()


@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_extract_n8n_text_payload_returns_200_without_detail_key(mock_extract, client):
    mock_extract.return_value = SAMPLE_FILTER_RESULT
    response = _post_json(client, EXTRACT_ENDPOINT, dict(N8N_TEXT_PAYLOAD))
    assert response.status_code == 200
    body = response.json()
    assert "detail" not in body
    assert body["reply_mode"] == "text"
    assert "transcript" not in body


@patch("apps.qualification.core.legacy_compat.transcribe_audio", return_value="I need a website for my bakery")
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_extract_n8n_voice_payload_returns_200_with_transcript(
    mock_extract,
    mock_download,
    mock_transcribe,
    client,
):
    mock_extract.return_value = SAMPLE_FILTER_RESULT
    response = _post_json(client, EXTRACT_ENDPOINT, dict(N8N_VOICE_PAYLOAD))
    assert response.status_code == 200
    body = response.json()
    assert "detail" not in body
    assert body["reply_mode"] == "voice"
    assert body["transcript"] == "I need a website for my bakery"


@patch(
    "apps.qualification.qualification_turn.extract_qualification_from_openrouter",
    side_effect=OpenRouterConfigurationError("missing"),
)
def test_extract_openrouter_configuration_failure_maps_to_503_contract(mock_extract, client):
    from apps.qualification.models import WhatsAppConversationSession
    from django.utils import timezone

    from apps.qualification.domain.language_selection import LANGUAGE_ENGLISH

    WhatsAppConversationSession.objects.create(
        whatsapp_number="+923001234567",
        language=LANGUAGE_ENGLISH,
        language_selected_at=timezone.now(),
    )
    response = _post_json(
        client,
        EXTRACT_ENDPOINT,
        {"message": OPENROUTER_FALLBACK_MESSAGE, "whatsapp_number": "+923001234567"},
    )
    assert_public_error_contract(response, status_code=503, body=ERROR_CONTRACT_503)
    mock_extract.assert_called_once()


@patch(
    "apps.qualification.services.extract_service.handle_qualification_turn",
    side_effect=QualificationServiceRequestError(),
)
def test_extract_service_request_failure_maps_to_502_contract(mock_turn, client):
    from apps.qualification.models import WhatsAppConversationSession
    from django.utils import timezone

    from apps.qualification.domain.language_selection import LANGUAGE_ENGLISH

    WhatsAppConversationSession.objects.create(
        whatsapp_number="+923001234567",
        language=LANGUAGE_ENGLISH,
        language_selected_at=timezone.now(),
    )
    response = _post_json(
        client,
        EXTRACT_ENDPOINT,
        {"message": OPENROUTER_FALLBACK_MESSAGE, "whatsapp_number": "+923001234567"},
    )
    assert_public_error_contract(response, status_code=502, body=ERROR_CONTRACT_502_LLM)


@patch("apps.qualification.api.views.ExtractAPIView.get_service")
def test_extract_unexpected_failure_maps_to_500_contract(mock_get_service, client):
    service = MagicMock()
    service.run_turn.side_effect = RuntimeError("unexpected")
    mock_get_service.return_value = service
    response = _post_json(
        client,
        EXTRACT_ENDPOINT,
        {"message": "hello", "whatsapp_number": "+923001234567"},
    )
    assert_public_error_contract(response, status_code=500, body=ERROR_CONTRACT_500)


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, PUBLIC_MEDIA_BASE_URL="https://tunnel.example.com")
@patch(
    "apps.qualification.services.render_audio_service.render_whatsapp_voice_reply_safe",
    side_effect=RenderAudioProcessingError(),
)
def test_render_audio_processing_failure_maps_to_text_fallback_contract(mock_render, client):
    response = _post_json(client, RENDER_ENDPOINT, dict(RENDER_PAYLOAD))
    assert response.status_code == 200
    body = response.json()
    assert body["fallback_to_text"] is True
    assert body["fallback_reason"] == "english_tts_unavailable"


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, PUBLIC_MEDIA_BASE_URL="https://tunnel.example.com")
@patch(
    "apps.qualification.services.render_audio_service.render_whatsapp_voice_reply_safe",
    side_effect=RenderAudioServiceUnavailableError(),
)
def test_render_audio_unavailable_failure_maps_to_text_fallback_contract(mock_render, client):
    response = _post_json(client, RENDER_ENDPOINT, dict(RENDER_PAYLOAD))
    assert response.status_code == 200
    body = response.json()
    assert body["fallback_to_text"] is True
    assert body["fallback_reason"] == "english_tts_unavailable"


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, PUBLIC_MEDIA_BASE_URL="https://tunnel.example.com", MAX_TTS_TEXT_LENGTH=800)
def test_render_audio_malformed_json_maps_to_400_contract(client):
    response = _post_json(client, RENDER_ENDPOINT, b"not-json")
    assert_public_error_contract(response, status_code=400, body=ERROR_CONTRACT_400)


@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_extract_malformed_json_maps_to_400_contract(mock_extract, client):
    response = _post_json(client, EXTRACT_ENDPOINT, b"not-json")
    assert_public_error_contract(response, status_code=400, body=ERROR_CONTRACT_400)
    mock_extract.assert_not_called()
