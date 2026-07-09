"""Tests for the internal qualification extract API endpoint."""

from __future__ import annotations

import json
import logging
import urllib.error
from unittest.mock import ANY, patch

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from apps.qualification.conversation_state import clear_conversations
from apps.qualification.integrations.openrouter import clear_openrouter_completion_cache
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.persistence.cache_backend import reset_qualification_cache_backend_for_tests
from apps.qualification.services.transcription_service import clear_transcription_media_cache
from apps.qualification.models import (
    QualificationFieldFilterResult,
    RejectedQualificationField,
    WhatsAppConversationSession,
)
from apps.qualification.openrouter_client import (
    OpenRouterConfigurationError,
    OpenRouterRequestError,
    OpenRouterResponseError,
    OpenRouterTimeoutError,
)

from apps.qualification.tests.internal_api_test_helpers import (
    API_SECRET,
    MOCK_VOICE_AUDIO_BYTES,
    MOCK_VOICE_AUDIO_DOWNLOAD,
    OPENROUTER_FALLBACK_MESSAGE,
    internal_api_auth_headers,
)

pytestmark = pytest.mark.django_db

ENDPOINT_PATH = "/api/internal/qualification/extract/"
VALID_MESSAGE = "I need a new website for a restaurant"
VALID_WHATSAPP_NUMBER = "+923001234567"
PROVIDER_ERROR_DETAIL = "provider secret failure details"
TEST_MESSAGE_SID = "SM0cc5a1d9e22bf9850ca24261ee23ce90"

OPENROUTER_ENDPOINT_SETTINGS = {
    "N8N_QUALIFICATION_API_SECRET": API_SECRET,
    "OPENROUTER_API_KEY": "test-openrouter-api-key",
    "OPENROUTER_MODEL": "test/openrouter-model",
    "OPENROUTER_BASE_URL": "https://openrouter.example/api/v1",
    "OPENROUTER_TIMEOUT_SECONDS": 20,
}

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


@pytest.fixture
def client() -> Client:
    clear_conversations()
    return Client()


@pytest.fixture(autouse=True)
def _reset_conversation_state():
    clear_conversations()
    clear_message_sid_cache()
    clear_openrouter_completion_cache()
    clear_transcription_media_cache()
    reset_qualification_cache_backend_for_tests()
    yield
    clear_conversations()
    clear_message_sid_cache()
    clear_openrouter_completion_cache()
    clear_transcription_media_cache()
    reset_qualification_cache_backend_for_tests()


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


def _assert_safe_endpoint_error_response(response: object) -> None:
    assert response.status_code in {400, 403, 500, 502, 503}
    body = response.json()
    assert set(body) == {"error"}
    response_text = response.content.decode("utf-8")
    assert VALID_MESSAGE not in response_text
    assert VALID_WHATSAPP_NUMBER not in response_text
    assert API_SECRET not in response_text
    assert PROVIDER_ERROR_DETAIL not in response_text
    assert "Authorization" not in response_text


@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_valid_request_returns_filtered_result_and_calls_client(mock_extract, client):
    mock_extract.return_value = SAMPLE_FILTER_RESULT

    response = _post_extract(
        client,
        {
            "message": OPENROUTER_FALLBACK_MESSAGE,
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_text",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted_fields"] == {
        "project_type": "new_website",
        "requirements": "website for a restaurant",
    }
    assert body["rejected_fields"] == {"referral_source": "value_missing"}
    assert body["human_handoff_requested"] is False
    assert body["next_field"] == "referral_source"
    assert body["reply_text"].endswith("Thank you. How did you hear about us?")
    assert "*Hi, welcome!*" in body["reply_text"]
    assert "Send *M* to open the menu" in body["reply_text"]
    assert body["qualification_status"] == "in_progress"
    assert body["reply_mode"] == "text"
    assert body["send_booking_link"] is False
    assert body["booking_link"] is None
    mock_extract.assert_called_once_with(
        customer_message=OPENROUTER_FALLBACK_MESSAGE,
        known_whatsapp_number=VALID_WHATSAPP_NUMBER,
        phone_confirmation_question_asked=False,
        message_sid=None,
        collected_fields={},
        conversation_history=[],
        conversation_language="en",
    )


@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_missing_secret_returns_403_without_calling_client(mock_extract, client):
    response = _post_extract(
        client,
        {"message": OPENROUTER_FALLBACK_MESSAGE, "whatsapp_number": VALID_WHATSAPP_NUMBER},
        secret=None,
    )

    assert response.status_code == 403
    assert response.json() == {"error": "Forbidden."}
    mock_extract.assert_not_called()


@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_invalid_secret_returns_403_without_calling_client(mock_extract, client):
    response = _post_extract(
        client,
        {"message": OPENROUTER_FALLBACK_MESSAGE, "whatsapp_number": VALID_WHATSAPP_NUMBER},
        secret="wrong-secret",
    )

    assert response.status_code == 403
    assert response.json() == {"error": "Forbidden."}
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET="")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_blank_django_secret_returns_503_without_calling_client(mock_extract, client):
    response = _post_extract(
        client,
        {"message": OPENROUTER_FALLBACK_MESSAGE, "whatsapp_number": VALID_WHATSAPP_NUMBER},
    )

    assert response.status_code == 503
    assert response.json() == {"error": "Qualification service is unavailable."}
    mock_extract.assert_not_called()


@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_get_method_is_rejected(mock_extract, client):
    response = client.get(
        ENDPOINT_PATH,
        HTTP_X_INTERNAL_WEBHOOK_SECRET=API_SECRET,
    )

    assert response.status_code == 405
    mock_extract.assert_not_called()


@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_malformed_json_returns_400(mock_extract, client):
    response = _post_extract(client, b"not-json")

    assert response.status_code == 400
    assert response.json() == {"error": "Invalid request."}
    mock_extract.assert_not_called()


@pytest.mark.parametrize("payload", [[VALID_MESSAGE], "string-root", 123])
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_non_object_json_root_returns_400(mock_extract, client, payload):
    response = _post_extract(client, payload)

    assert response.status_code == 400
    assert response.json() == {"error": "Invalid request."}
    mock_extract.assert_not_called()


@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_missing_message_returns_400(mock_extract, client):
    response = _post_extract(client, {"whatsapp_number": VALID_WHATSAPP_NUMBER})

    assert response.status_code == 400
    assert response.json() == {"error": "Invalid request."}
    mock_extract.assert_not_called()


@pytest.mark.parametrize("message", ["", "   ", "\n\t"])
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_blank_message_returns_400(mock_extract, client, message):
    response = _post_extract(
        client,
        {"message": message, "whatsapp_number": VALID_WHATSAPP_NUMBER},
    )

    assert response.status_code == 400
    assert response.json() == {"error": "Invalid request."}
    mock_extract.assert_not_called()


@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_missing_whatsapp_number_returns_400(mock_extract, client):
    response = _post_extract(client, {"message": VALID_MESSAGE})

    assert response.status_code == 400
    assert response.json() == {"error": "Invalid request."}
    mock_extract.assert_not_called()


@pytest.mark.parametrize(
    "whatsapp_number",
    ["923001234567", "+0123456789", "+92300", "not-a-phone", 923001234567],
)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_invalid_whatsapp_number_returns_400(mock_extract, client, whatsapp_number):
    response = _post_extract(
        client,
        {"message": VALID_MESSAGE, "whatsapp_number": whatsapp_number},
    )

    assert response.status_code == 400
    assert response.json() == {"error": "Invalid request."}
    mock_extract.assert_not_called()


@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_extra_request_field_returns_400(mock_extract, client):
    response = _post_extract(
        client,
        {
            "message": OPENROUTER_FALLBACK_MESSAGE,
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "extra": "field",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"error": "Invalid request."}
    mock_extract.assert_not_called()


@patch(
    "apps.qualification.qualification_turn.extract_qualification_from_openrouter",
    side_effect=OpenRouterConfigurationError("OpenRouter model is not configured"),
)
def test_openrouter_configuration_error_returns_503(mock_extract, client):
    response = _post_extract(
        client,
        {"message": OPENROUTER_FALLBACK_MESSAGE, "whatsapp_number": VALID_WHATSAPP_NUMBER},
    )

    assert response.status_code == 503
    assert response.json() == {"error": "Qualification service is unavailable."}
    mock_extract.assert_called_once()


@pytest.mark.parametrize(
    "error",
    [
        OpenRouterRequestError("OpenRouter request failed"),
        OpenRouterResponseError("OpenRouter response is not valid JSON"),
    ],
)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_openrouter_transport_errors_return_502(mock_extract, client, error):
    mock_extract.side_effect = error

    response = _post_extract(
        client,
        {"message": OPENROUTER_FALLBACK_MESSAGE, "whatsapp_number": VALID_WHATSAPP_NUMBER},
    )

    assert response.status_code == 502
    assert response.json() == {"error": "Qualification LLM request failed."}
    mock_extract.assert_called_once()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch(
    "apps.qualification.openrouter_client.request_openrouter_completion",
    return_value="{not valid json",
)
def test_malformed_assistant_json_returns_safe_200_fallback(mock_urlopen, client):
    WhatsAppConversationSession.objects.create(
        whatsapp_number=VALID_WHATSAPP_NUMBER,
        language="en",
        language_selected_at=timezone.now(),
    )
    response = _post_extract(
        client,
        {"message": OPENROUTER_FALLBACK_MESSAGE, "whatsapp_number": VALID_WHATSAPP_NUMBER},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["llm_parse_failed"] is True
    assert body["complete"] is False
    assert "team will guide you properly in the meeting" in body["reply_text"]
    assert VALID_MESSAGE not in response.content.decode("utf-8")


@patch(
    "apps.qualification.qualification_turn.extract_qualification_from_openrouter",
    side_effect=OpenRouterTimeoutError("OpenRouter request timed out"),
)
def test_timeout_returns_safe_502_without_sensitive_data(mock_extract, client):
    response = _post_extract(
        client,
        {"message": OPENROUTER_FALLBACK_MESSAGE, "whatsapp_number": VALID_WHATSAPP_NUMBER},
    )

    assert response.status_code == 502
    assert response.json() == {"error": "Qualification LLM request failed."}
    _assert_safe_endpoint_error_response(response)
    mock_extract.assert_called_once()


@override_settings(**OPENROUTER_ENDPOINT_SETTINGS)
@patch("apps.qualification.openrouter_client.urllib.request.urlopen")
def test_openrouter_timeout_logs_safe_structured_event(mock_urlopen, client, caplog):
    mock_urlopen.side_effect = urllib.error.URLError("timed out")
    caplog.set_level(logging.ERROR, logger="apps.qualification")

    response = _post_extract(
        client,
        {
            "message": OPENROUTER_FALLBACK_MESSAGE,
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_text",
            "message_sid": TEST_MESSAGE_SID,
        },
    )

    assert response.status_code == 502
    assert response.json() == {"error": "Qualification LLM request failed."}
    _assert_safe_endpoint_error_response(response)

    failure_records = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "apps.qualification"
        and '"step":"openrouter_call_failed"' in record.message.replace(" ", "")
    ]
    assert len(failure_records) == 1
    payload = failure_records[0]
    assert payload["step"] == "openrouter_call_failed"
    assert payload["message_sid"] == TEST_MESSAGE_SID
    assert payload["error_type"] == "OpenRouterTimeoutError"
    assert payload["details"] == "OpenRouter request timed out"
    assert VALID_MESSAGE not in caplog.text
    assert VALID_WHATSAPP_NUMBER not in caplog.text
    assert API_SECRET not in caplog.text


@override_settings(**OPENROUTER_ENDPOINT_SETTINGS)
@patch("apps.qualification.openrouter_client.urllib.request.urlopen")
def test_openrouter_non_timeout_failure_logs_generic_upstream_event(mock_urlopen, client, caplog):
    mock_urlopen.side_effect = urllib.error.URLError("connection refused")
    caplog.set_level(logging.ERROR, logger="apps.qualification")

    response = _post_extract(
        client,
        {
            "message": OPENROUTER_FALLBACK_MESSAGE,
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_text",
            "message_sid": TEST_MESSAGE_SID,
        },
    )

    assert response.status_code == 502
    assert response.json() == {"error": "Qualification LLM request failed."}

    failed_records = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "apps.qualification"
        and '"step":"openrouter_call_failed"' in record.message.replace(" ", "")
    ]
    assert len(failed_records) == 1
    assert failed_records[0]["step"] == "openrouter_call_failed"
    assert failed_records[0]["message_sid"] == TEST_MESSAGE_SID
    assert failed_records[0]["error_type"] == "OpenRouterRequestError"
    assert VALID_MESSAGE not in caplog.text
    assert VALID_WHATSAPP_NUMBER not in caplog.text
    assert API_SECRET not in caplog.text
    assert "connection refused" not in caplog.text


@patch(
    "apps.qualification.qualification_turn.extract_qualification_from_openrouter",
    side_effect=OpenRouterRequestError(PROVIDER_ERROR_DETAIL),
)
def test_http_failure_returns_safe_502_without_provider_body_or_database_write(
    mock_extract,
    client,
):
    response = _post_extract(
        client,
        {"message": OPENROUTER_FALLBACK_MESSAGE, "whatsapp_number": VALID_WHATSAPP_NUMBER},
    )

    assert response.status_code == 502
    assert response.json() == {"error": "Qualification LLM request failed."}
    _assert_safe_endpoint_error_response(response)
    mock_extract.assert_called_once()


@patch(
    "apps.qualification.qualification_turn.extract_qualification_from_openrouter",
    side_effect=RuntimeError("unexpected failure"),
)
def test_unexpected_exception_returns_500(mock_extract, client):
    response = _post_extract(
        client,
        {"message": OPENROUTER_FALLBACK_MESSAGE, "whatsapp_number": VALID_WHATSAPP_NUMBER},
    )

    assert response.status_code == 500
    assert response.json() == {"error": "Internal server error."}
    mock_extract.assert_called_once()


@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_no_database_write_occurs(mock_extract, client):
    mock_extract.return_value = SAMPLE_FILTER_RESULT

    response = _post_extract(
        client,
        {"message": OPENROUTER_FALLBACK_MESSAGE, "whatsapp_number": VALID_WHATSAPP_NUMBER},
    )

    assert response.status_code == 200
    mock_extract.assert_called_once()


@override_settings(
    N8N_QUALIFICATION_API_SECRET=API_SECRET,
    OPENROUTER_API_KEY="test-openrouter-api-key",
    OPENROUTER_MODEL="test/openrouter-model",
    OPENROUTER_BASE_URL="https://openrouter.example/api/v1",
    OPENROUTER_TIMEOUT_SECONDS=20,
)
@patch("apps.qualification.openrouter_client.urllib.request.urlopen")
def test_endpoint_default_strips_unasked_phone_fields_for_restaurant_regression(mock_urlopen, client):
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(unsafe_payload),
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    unsafe_payload = {
        "project_type": "new_website",
        "requirements": "I need a new website for my restaurant",
        "referral_source": "Facebook",
        "whatsapp_confirmed": True,
        "preferred_phone": VALID_WHATSAPP_NUMBER,
        "human_handoff_requested": False,
        "confidence": {
            "project_type": 0.95,
            "requirements": 0.92,
            "referral_source": 0.9,
            "whatsapp_confirmed": 0.96,
            "preferred_phone": 0.94,
        },
    }
    mock_urlopen.return_value = FakeResponse()
    WhatsAppConversationSession.objects.create(
        whatsapp_number=VALID_WHATSAPP_NUMBER,
        language="en",
        language_selected_at=timezone.now(),
    )

    response = _post_extract(
        client,
        {"message": OPENROUTER_FALLBACK_MESSAGE, "whatsapp_number": VALID_WHATSAPP_NUMBER},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted_fields"]["project_type"] == "new_website"
    assert body["accepted_fields"]["requirements"] == "I need a new website for my restaurant"
    assert body["accepted_fields"]["referral_source"] == "Facebook"
    assert "whatsapp_confirmed" not in body["accepted_fields"]
    assert "preferred_phone" not in body["accepted_fields"]
    assert body["rejected_fields"]["whatsapp_confirmed"] == "value_missing"
    assert body["rejected_fields"]["preferred_phone"] == "value_missing"
    assert body["next_field"] == "whatsapp_confirmed"
    assert body["reply_text"] == "Thank you. Is this WhatsApp number the best number to reach you?"
    assert body["qualification_status"] == "in_progress"


N8N_TEXT_PAYLOAD = {
    "message": "I need a website for my bakery",
    "whatsapp_number": "+923246271149",
    "input_channel": "whatsapp_text",
    "message_sid": "SM0cc5a1d9e22bf9850ca24261ee23ce90",
    "media_url": None,
    "media_content_type": None,
}
TWILIO_MEDIA_URL = "https://api.twilio.com/2010-04-01/Accounts/ACtest/Media/MEtestvoice001"


@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_text_request_with_media_fields_omitted_returns_200(mock_extract, client):
    mock_extract.return_value = SAMPLE_FILTER_RESULT

    response = _post_extract(
        client,
        {
            "message": OPENROUTER_FALLBACK_MESSAGE,
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_text",
        },
    )

    assert response.status_code == 200


@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_text_request_with_null_media_fields_returns_200(mock_extract, client):
    mock_extract.return_value = SAMPLE_FILTER_RESULT

    response = _post_extract(client, dict(N8N_TEXT_PAYLOAD))

    assert response.status_code == 200
    mock_extract.assert_not_called()


@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_exact_n8n_text_payload_is_accepted(mock_extract, client):
    mock_extract.return_value = SAMPLE_FILTER_RESULT

    response = _post_extract(client, dict(N8N_TEXT_PAYLOAD))

    assert response.status_code == 200
    assert response.json()["reply_mode"] == "text"


@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_text_request_with_non_empty_media_url_ignores_media_and_returns_200(mock_extract, client):
    mock_extract.return_value = SAMPLE_FILTER_RESULT

    response = _post_extract(
        client,
        {
            "message": VALID_MESSAGE,
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_text",
            "media_url": TWILIO_MEDIA_URL,
            "media_content_type": "audio/ogg",
        },
    )

    assert response.status_code == 200
    mock_extract.assert_not_called()


@patch("apps.qualification.core.legacy_compat.transcribe_audio", return_value="I need a website for my bakery")
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_voice_note_request_with_valid_audio_fields_is_accepted(
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
    assert response.json()["reply_mode"] == "voice"
    mock_download.assert_called_once_with(TWILIO_MEDIA_URL)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_voice_note",
            "media_url": None,
            "media_content_type": "audio/ogg",
        },
        {
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_voice_note",
            "media_url": TWILIO_MEDIA_URL,
            "media_content_type": "audio/ogg",
        },
        {
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_voice_note",
            "message_sid": "MM0cc5a1d9e22bf9850ca24261ee23ce90",
            "media_url": TWILIO_MEDIA_URL,
            "media_content_type": "video/mp4",
        },
    ],
)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_voice_note_request_with_invalid_media_fields_returns_400(mock_extract, client, payload):
    response = _post_extract(client, payload)

    assert response.status_code == 400
    assert response.json() == {"error": "Invalid request."}
    mock_extract.assert_not_called()


N8N_VOICE_PAYLOAD = {
    "message": "",
    "whatsapp_number": "+923246271149",
    "input_channel": "whatsapp_voice_note",
    "message_sid": "MM0cc5a1d9e22bf9850ca24261ee23ce90",
    "media_url": (
        "https://api.twilio.com/2010-04-01/Accounts/ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx/"
        "Messages/MM0cc5a1d9e22bf9850ca24261ee23ce90/Media/MEyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy"
    ),
    "media_content_type": "audio/ogg",
}
VOICE_TRANSCRIPT = "I need a website for my bakery"


def _voice_payload(**overrides: object) -> dict[str, object]:
    payload = dict(N8N_VOICE_PAYLOAD)
    payload.update(overrides)
    return payload


@patch("apps.qualification.core.legacy_compat.transcribe_audio", return_value=VOICE_TRANSCRIPT)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_live_n8n_voice_payload_with_empty_message_and_mm_sid_is_accepted(
    mock_extract,
    mock_download,
    mock_transcribe,
    client,
):
    mock_extract.return_value = SAMPLE_FILTER_RESULT

    response = _post_extract(client, dict(N8N_VOICE_PAYLOAD))

    assert response.status_code == 200
    body = response.json()
    assert body["reply_mode"] == "voice"
    assert body["transcript"] == VOICE_TRANSCRIPT
    mock_download.assert_called_once_with(N8N_VOICE_PAYLOAD["media_url"])
    mock_transcribe.assert_called_once_with(
        MOCK_VOICE_AUDIO_BYTES,
        content_type="audio/ogg",
        transcription_config=ANY,
    )
    mock_extract.assert_not_called()


@patch("apps.qualification.core.legacy_compat.transcribe_audio", return_value=VOICE_TRANSCRIPT)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@pytest.mark.parametrize(
    "message_value",
    [
        pytest.param({"message": ""}, id="empty-string"),
        pytest.param({}, id="omitted"),
        pytest.param({"message": None}, id="null"),
        pytest.param({"message": "   "}, id="whitespace"),
    ],
)
def test_voice_payload_accepts_blank_or_missing_message_variants(
    mock_extract,
    mock_download,
    mock_transcribe,
    client,
    message_value,
):
    mock_extract.return_value = SAMPLE_FILTER_RESULT
    payload = _voice_payload()
    if "message" in message_value:
        if message_value["message"] is None:
            payload["message"] = None
        else:
            payload["message"] = message_value["message"]
    else:
        payload.pop("message", None)

    response = _post_extract(client, payload)

    assert response.status_code == 200
    mock_download.assert_called_once()
    mock_transcribe.assert_called_once()


@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_text_payload_with_blank_message_returns_400(mock_extract, client):
    response = _post_extract(
        client,
        {
            "message": "",
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_text",
        },
    )

    assert response.status_code == 400
    mock_extract.assert_not_called()


@patch("apps.qualification.core.legacy_compat.transcribe_audio", return_value=VOICE_TRANSCRIPT)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@pytest.mark.parametrize(
    "message_sid",
    [
        "SM0cc5a1d9e22bf9850ca24261ee23ce90",
        "MM0cc5a1d9e22bf9850ca24261ee23ce90",
    ],
)
def test_sm_and_mm_message_sids_are_accepted(
    mock_extract,
    mock_download,
    mock_transcribe,
    client,
    message_sid,
):
    mock_extract.return_value = SAMPLE_FILTER_RESULT

    response = _post_extract(client, _voice_payload(message_sid=message_sid))

    assert response.status_code == 200


@pytest.mark.parametrize(
    "message_sid",
    [
        "MM0cc5a1d9e22bf9850ca24261ee23ce90/../../../etc/passwd",
        "MM<script>alert(1)</script>xxxxxxxxxxxxxx",
        "MMtooshort",
        "XX0cc5a1d9e22bf9850ca24261ee23ce90",
    ],
)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_invalid_message_sids_with_unsafe_characters_are_rejected(
    mock_extract,
    client,
    message_sid,
):
    response = _post_extract(client, _voice_payload(message_sid=message_sid))

    assert response.status_code == 400
    mock_extract.assert_not_called()
