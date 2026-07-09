"""Tests for ExtractAPIView."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client, override_settings
from django.urls import reverse

from apps.qualification.conversation_state import clear_conversations
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.models import WhatsAppConversationSession
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.models import QualificationFieldFilterResult, RejectedQualificationField
from apps.qualification.openrouter_client import OpenRouterConfigurationError

pytestmark = pytest.mark.django_db
from apps.qualification.qualification_turn import (
    QualificationServiceRequestError,
    QualificationServiceUnavailableError,
)
from apps.qualification.tests.internal_api_test_helpers import (
    API_SECRET,
    EXTRACT_SUCCESS_FIELD_NAMES,
    MOCK_VOICE_AUDIO_BYTES,
    MOCK_VOICE_AUDIO_DOWNLOAD,
    OPENROUTER_FALLBACK_MESSAGE,
    RENDER_AUDIO_SUCCESS_FIELD_NAMES,
    assert_public_error_contract,
    internal_api_auth_headers,
)

ENDPOINT_PATH = "/api/internal/qualification/extract/"
ROUTE_NAME = "internal-qualification-extract"
VALID_MESSAGE = "I need a new website for a restaurant"
VALID_WHATSAPP_NUMBER = "+923001234567"
TWILIO_MEDIA_URL = "https://api.twilio.com/2010-04-01/Accounts/ACtest/Media/MEtestvoice001"
VOICE_TRANSCRIPT = "I need a website for my bakery"
_RICH_REPLY_BODY = "Thank you, I've noted that. Thank you. How did you hear about us?"
_ONBOARDING_PREFIXED_REPLY = (
    f"{get_customer_message(language='en', key='onboarding_intro')}\n\n{_RICH_REPLY_BODY}"
)

SAMPLE_FILTER_RESULT = QualificationFieldFilterResult(
    accepted_fields={
        "project_type": "new_website",
        "requirements": "website for a restaurant",
    },
    rejected_fields=(
        RejectedQualificationField(field_name="referral_source", reason="null value"),
    ),
    human_handoff_requested=False,
)

EXPECTED_TEXT_RESPONSE = {
    "accepted_fields": {
        "project_type": "new_website",
        "requirements": VALID_MESSAGE,
        "services_required": ["new_website"],
    },
    "rejected_fields": {},
    "human_handoff_requested": False,
    "next_field": "referral_source",
    "reply_text": _ONBOARDING_PREFIXED_REPLY,
    "qualification_status": "in_progress",
    "conversation_language": "en",
    "preferred_phone": None,
    "reply_mode": "text",
    "spoken_text": _ONBOARDING_PREFIXED_REPLY,
    "whatsapp_text": _ONBOARDING_PREFIXED_REPLY,
    "actions": [],
    "send_booking_link": False,
    "booking_link_sent": False,
    "booking_link": None,
    "classification": ["service_request", "requirement_detail"],
    "saved_services": ["new_website"],
    "saved_requirements": [VALID_MESSAGE],
    "next_required_field": "referral_source",
    "complete": False,
}


@pytest.fixture
def client() -> Client:
    clear_conversations()
    clear_message_sid_cache()
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


def _post_extract(
    client: Client,
    payload: object,
    *,
    secret: str | None = API_SECRET,
) -> object:
    headers: dict[str, str] = {"content_type": "application/json", **internal_api_auth_headers(secret=secret)}
    body = json.dumps(payload) if not isinstance(payload, (bytes, str)) else payload
    if isinstance(body, str):
        body = body.encode("utf-8")
    return client.post(ENDPOINT_PATH, data=body, **headers)


def test_extract_url_and_route_name_resolve():
    assert reverse(ROUTE_NAME) == ENDPOINT_PATH


@override_settings(N8N_QUALIFICATION_API_SECRET="")
def test_missing_configuration_returns_503_before_auth_check(client):
    response = _post_extract(
        client,
        {"message": VALID_MESSAGE, "whatsapp_number": VALID_WHATSAPP_NUMBER},
        secret=None,
    )

    assert response.status_code == 503
    assert response.json() == {"error": "Qualification service is unavailable."}


@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_missing_secret_returns_403(mock_extract, client):
    response = _post_extract(
        client,
        {"message": VALID_MESSAGE, "whatsapp_number": VALID_WHATSAPP_NUMBER},
        secret=None,
    )

    assert response.status_code == 403
    assert response.json() == {"error": "Forbidden."}
    mock_extract.assert_not_called()


@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_invalid_secret_returns_403(mock_extract, client):
    response = _post_extract(
        client,
        {"message": VALID_MESSAGE, "whatsapp_number": VALID_WHATSAPP_NUMBER},
        secret="wrong-secret",
    )

    assert response.status_code == 403
    assert response.json() == {"error": "Forbidden."}
    mock_extract.assert_not_called()


@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_malformed_json_returns_400(mock_extract, client):
    response = _post_extract(client, b"not-json")

    assert response.status_code == 400
    assert response.json() == {"error": "Invalid request."}
    mock_extract.assert_not_called()


@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_invalid_request_returns_400(mock_extract, client):
    response = _post_extract(client, {"whatsapp_number": VALID_WHATSAPP_NUMBER})

    assert_public_error_contract(response, status_code=400, body={"error": "Invalid request."})
    mock_extract.assert_not_called()


@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_valid_text_request_returns_200_with_contract_body(mock_extract, client):
    mock_extract.return_value = SAMPLE_FILTER_RESULT

    response = _post_extract(
        client,
        {
            "message": VALID_MESSAGE,
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_text",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == EXTRACT_SUCCESS_FIELD_NAMES
    assert body == EXPECTED_TEXT_RESPONSE
    assert "transcript" not in body
    assert "detail" not in body
    mock_extract.assert_not_called()


@pytest.mark.parametrize("payload", [[], "string-root", 123])
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_non_object_json_root_returns_400(mock_extract, client, payload):
    response = _post_extract(client, payload)

    assert_public_error_contract(response, status_code=400, body={"error": "Invalid request."})
    mock_extract.assert_not_called()


@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_message_sid_idempotency_returns_cached_response_without_second_turn(mock_extract, client):
    mock_extract.return_value = SAMPLE_FILTER_RESULT
    payload = {
        "message": VALID_MESSAGE,
        "whatsapp_number": VALID_WHATSAPP_NUMBER,
        "input_channel": "whatsapp_text",
        "message_sid": "SM0cc5a1d9e22bf9850ca24261ee23ce90",
    }

    first = _post_extract(client, payload)
    second = _post_extract(client, payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    mock_extract.assert_not_called()


@patch("apps.qualification.core.legacy_compat.transcribe_audio", return_value=VOICE_TRANSCRIPT)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_valid_voice_request_returns_200_with_transcript(
    mock_extract,
    mock_download,
    mock_transcribe,
    client,
):
    mock_extract.return_value = SAMPLE_FILTER_RESULT

    response = _post_extract(
        client,
        {
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_voice_note",
            "message_sid": "MM0cc5a1d9e22bf9850ca24261ee23ce90",
            "media_url": TWILIO_MEDIA_URL,
            "media_content_type": "audio/ogg",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reply_mode"] == "voice"
    assert body["transcript"] == VOICE_TRANSCRIPT


@patch(
    "apps.qualification.qualification_turn.extract_qualification_from_openrouter",
    side_effect=OpenRouterConfigurationError("missing config"),
)
def test_configuration_failure_returns_503(mock_extract, client):
    response = _post_extract(
        client,
        {"message": OPENROUTER_FALLBACK_MESSAGE, "whatsapp_number": VALID_WHATSAPP_NUMBER},
    )

    assert response.status_code == 503
    assert response.json() == {"error": "Qualification service is unavailable."}
    mock_extract.assert_called_once()


@patch(
    "apps.qualification.services.extract_service.handle_qualification_turn",
    side_effect=QualificationServiceRequestError(),
)
def test_service_request_failure_returns_502(mock_turn_handler, client):
    response = _post_extract(
        client,
        {"message": VALID_MESSAGE, "whatsapp_number": VALID_WHATSAPP_NUMBER},
    )

    assert response.status_code == 502
    assert response.json() == {"error": "Qualification LLM request failed."}


@patch(
    "apps.qualification.services.extract_service.handle_qualification_turn",
    side_effect=QualificationServiceUnavailableError(),
)
def test_service_unavailable_failure_returns_503(mock_turn_handler, client):
    response = _post_extract(
        client,
        {"message": VALID_MESSAGE, "whatsapp_number": VALID_WHATSAPP_NUMBER},
    )

    assert response.status_code == 503
    assert response.json() == {"error": "Qualification service is unavailable."}


@patch(
    "apps.qualification.api.views.ExtractAPIView.get_service",
)
def test_unexpected_exception_returns_500(mock_get_service, client):
    service = MagicMock()
    service.run_turn.side_effect = RuntimeError("unexpected")
    mock_get_service.return_value = service

    response = _post_extract(
        client,
        {"message": VALID_MESSAGE, "whatsapp_number": VALID_WHATSAPP_NUMBER},
    )

    assert response.status_code == 500
    assert response.json() == {"error": "Internal server error."}
