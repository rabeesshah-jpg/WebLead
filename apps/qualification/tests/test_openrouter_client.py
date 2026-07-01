"""Tests for the OpenRouter qualification extraction client."""

from __future__ import annotations

import io
import json
import socket
import urllib.error
from unittest.mock import patch

import pytest
from django.test import override_settings

from apps.qualification.extractor import ExtractionParseError
from apps.qualification.openrouter_client import (
    OpenRouterConfigurationError,
    OpenRouterRequestError,
    OpenRouterResponseError,
    OpenRouterTimeoutError,
    extract_qualification_from_openrouter,
)
from apps.qualification.prompts import EXTRACTION_SYSTEM_PROMPT, build_extraction_user_message

TEST_API_KEY = "test-openrouter-api-key"
TEST_MODEL = "test/openrouter-model"
CUSTOMER_MESSAGE = "I need a new website for my bakery"
KNOWN_WHATSAPP_NUMBER = "+15551234567"
PROVIDER_ERROR_DETAIL = "provider secret failure details"
RAW_ASSISTANT_JSON = "not-json"

OPENROUTER_SETTINGS = {
    "OPENROUTER_API_KEY": TEST_API_KEY,
    "OPENROUTER_MODEL": TEST_MODEL,
    "OPENROUTER_BASE_URL": "https://openrouter.example/api/v1",
    "OPENROUTER_TIMEOUT_SECONDS": 20,
    "OPENROUTER_COMPLETION_MAX_TOKENS": 120,
}


def _valid_extraction_payload(
    *,
    referral_source: str | None = "Google",
    referral_source_confidence: float = 0.9,
    whatsapp_confirmed: bool | None = True,
    whatsapp_confirmed_confidence: float = 0.96,
    preferred_phone: str | None = "+15551234567",
    preferred_phone_confidence: float = 0.94,
) -> dict[str, object]:
    return {
        "project_type": "new_website",
        "requirements": "I need a new website for my bakery",
        "referral_source": referral_source,
        "whatsapp_confirmed": whatsapp_confirmed,
        "preferred_phone": preferred_phone,
        "human_handoff_requested": False,
        "confidence": {
            "project_type": 0.95,
            "requirements": 0.92,
            "referral_source": referral_source_confidence,
            "whatsapp_confirmed": whatsapp_confirmed_confidence,
            "preferred_phone": preferred_phone_confidence,
        },
    }


def _openrouter_wrapper_payload(content: object) -> dict[str, object]:
    return {"choices": [{"message": {"content": content}}]}


def _openrouter_wrapper_bytes(extraction_payload: dict[str, object]) -> bytes:
    return json.dumps(
        _openrouter_wrapper_payload(json.dumps(extraction_payload))
    ).encode("utf-8")


def _assert_client_error_is_safe(error_message: str) -> None:
    assert CUSTOMER_MESSAGE not in error_message
    assert KNOWN_WHATSAPP_NUMBER not in error_message
    assert TEST_API_KEY not in error_message
    assert PROVIDER_ERROR_DETAIL not in error_message
    assert "Authorization" not in error_message


class _FakeResponse:
    def __init__(self, body: bytes, *, status: int = 200) -> None:
        self._body = body
        self.status = status

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


@override_settings(**OPENROUTER_SETTINGS)
@patch("apps.qualification.openrouter_client.urllib.request.urlopen")
def test_successful_response_parses_and_filters_high_confidence_fields(mock_urlopen):
    captured: dict[str, object] = {}

    def _capture_open(request, timeout=0):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(_openrouter_wrapper_bytes(_valid_extraction_payload()))

    mock_urlopen.side_effect = _capture_open

    result = extract_qualification_from_openrouter(
        customer_message=CUSTOMER_MESSAGE,
        known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
    )

    assert captured["url"] == "https://openrouter.example/api/v1/chat/completions"
    assert captured["timeout"] == 20

    headers = captured["headers"]
    assert headers["Content-type"] == "application/json"
    assert headers["Authorization"] == f"Bearer {TEST_API_KEY}"

    body = captured["body"]
    assert body["model"] == TEST_MODEL
    assert body["stream"] is False
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][0]["content"] == EXTRACTION_SYSTEM_PROMPT
    assert body["messages"][1]["role"] == "user"
    assert body["messages"][1]["content"] == build_extraction_user_message(
        customer_message=CUSTOMER_MESSAGE,
        known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
        phone_confirmation_question_asked=False,
        collected_fields={},
        recent_history=[],
    )
    assert body["max_tokens"] == 120
    assert body["response_format"] == {"type": "json_object"}

    assert result.accepted_fields["project_type"] == "new_website"
    assert result.accepted_fields["requirements"] == "I need a new website for my bakery"
    assert result.accepted_fields["referral_source"] == "Google"
    assert "whatsapp_confirmed" not in result.accepted_fields
    assert "preferred_phone" not in result.accepted_fields
    assert result.human_handoff_requested is False


@override_settings(**OPENROUTER_SETTINGS)
@patch("apps.qualification.openrouter_client.urllib.request.urlopen")
def test_low_confidence_field_is_rejected_while_others_remain_accepted(mock_urlopen):
    mock_urlopen.return_value = _FakeResponse(
        _openrouter_wrapper_bytes(
            _valid_extraction_payload(referral_source="Instagram", referral_source_confidence=0.5)
        )
    )

    result = extract_qualification_from_openrouter(
        customer_message=CUSTOMER_MESSAGE,
        known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
    )

    assert result.accepted_fields["project_type"] == "new_website"
    assert result.accepted_fields["requirements"] == "I need a new website for my bakery"
    assert "referral_source" not in result.accepted_fields
    assert any(rejected.field_name == "referral_source" for rejected in result.rejected_fields)


@override_settings(**OPENROUTER_SETTINGS)
@patch("apps.qualification.openrouter_client.urllib.request.urlopen")
def test_whatsapp_confirmed_false_at_threshold_is_accepted(mock_urlopen):
    mock_urlopen.return_value = _FakeResponse(
        _openrouter_wrapper_bytes(
            _valid_extraction_payload(
                whatsapp_confirmed=False,
                preferred_phone="+15559876543",
                whatsapp_confirmed_confidence=0.75,
                preferred_phone_confidence=0.75,
            )
        )
    )

    result = extract_qualification_from_openrouter(
        customer_message="No, please contact me on +15559876543 instead.",
        known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
        phone_confirmation_question_asked=True,
    )

    assert result.accepted_fields["whatsapp_confirmed"] is False
    assert result.accepted_fields["preferred_phone"] == "+15559876543"


@override_settings(OPENROUTER_API_KEY="", OPENROUTER_MODEL=TEST_MODEL)
def test_missing_api_key_raises_configuration_error_without_request():
    with patch("apps.qualification.openrouter_client.urllib.request.urlopen") as mock_urlopen:
        with pytest.raises(OpenRouterConfigurationError, match="API key"):
            extract_qualification_from_openrouter(
                customer_message=CUSTOMER_MESSAGE,
                known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
            )
        mock_urlopen.assert_not_called()


@override_settings(OPENROUTER_API_KEY=TEST_API_KEY, OPENROUTER_MODEL="")
def test_missing_model_raises_configuration_error_without_request():
    with patch("apps.qualification.openrouter_client.urllib.request.urlopen") as mock_urlopen:
        with pytest.raises(OpenRouterConfigurationError, match="model"):
            extract_qualification_from_openrouter(
                customer_message=CUSTOMER_MESSAGE,
                known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
            )
        mock_urlopen.assert_not_called()


@override_settings(**OPENROUTER_SETTINGS)
@patch("apps.qualification.openrouter_client.urllib.request.urlopen")
@pytest.mark.parametrize(
    "urlopen_side_effect",
    [
        pytest.param(urllib.error.URLError("timed out"), id="urlerror-string-timed-out"),
        pytest.param(urllib.error.URLError(socket.timeout("timed out")), id="urlerror-socket-timeout"),
        pytest.param(urllib.error.URLError(TimeoutError("timed out")), id="urlerror-timeout-error"),
        pytest.param(socket.timeout("timed out"), id="socket-timeout"),
        pytest.param(TimeoutError("timed out"), id="timeout-error"),
    ],
)
def test_timeout_failures_raise_openrouter_timeout_error(
    mock_urlopen,
    urlopen_side_effect,
):
    mock_urlopen.side_effect = urlopen_side_effect

    with pytest.raises(OpenRouterTimeoutError, match="OpenRouter request timed out") as exc_info:
        extract_qualification_from_openrouter(
            customer_message=CUSTOMER_MESSAGE,
            known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
        )

    error_message = str(exc_info.value)
    _assert_client_error_is_safe(error_message)
    assert isinstance(exc_info.value, OpenRouterRequestError)


@override_settings(**OPENROUTER_SETTINGS)
@patch("apps.qualification.openrouter_client.urllib.request.urlopen")
def test_non_timeout_urlerror_remains_generic_request_error(mock_urlopen):
    mock_urlopen.side_effect = urllib.error.URLError("connection refused")

    with pytest.raises(OpenRouterRequestError, match="OpenRouter request failed") as exc_info:
        extract_qualification_from_openrouter(
            customer_message=CUSTOMER_MESSAGE,
            known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
        )

    assert not isinstance(exc_info.value, OpenRouterTimeoutError)
    _assert_client_error_is_safe(str(exc_info.value))


@override_settings(**OPENROUTER_SETTINGS)
@patch("apps.qualification.openrouter_client.urllib.request.urlopen")
def test_timeout_records_elapsed_ms(mock_urlopen):
    mock_urlopen.side_effect = urllib.error.URLError("timed out")

    with pytest.raises(OpenRouterTimeoutError):
        extract_qualification_from_openrouter(
            customer_message=CUSTOMER_MESSAGE,
            known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
        )

    assert extract_qualification_from_openrouter.last_elapsed_ms >= 0


@pytest.mark.parametrize("status_code", [429, 500, 502])
@override_settings(**OPENROUTER_SETTINGS)
@patch("apps.qualification.openrouter_client.urllib.request.urlopen")
def test_non_2xx_status_codes_raise_safe_request_error(mock_urlopen, status_code):
    provider_body = json.dumps({"error": {"message": PROVIDER_ERROR_DETAIL}}).encode("utf-8")
    mock_urlopen.side_effect = urllib.error.HTTPError(
        url="https://openrouter.example/api/v1/chat/completions",
        code=status_code,
        msg="Provider Error",
        hdrs={},
        fp=io.BytesIO(provider_body),
    )

    with pytest.raises(OpenRouterRequestError, match="OpenRouter request failed") as exc_info:
        extract_qualification_from_openrouter(
            customer_message=CUSTOMER_MESSAGE,
            known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
        )

    _assert_client_error_is_safe(str(exc_info.value))
    assert str(status_code) not in str(exc_info.value)


@pytest.mark.parametrize(
    ("wrapper_payload", "expected_match"),
    [
        ({}, "missing choices"),
        ({"choices": []}, "missing choices"),
        ({"choices": ["not-a-dict"]}, "missing message content"),
        ({"choices": [{}]}, "missing message content"),
        ({"choices": [{"message": {}}]}, "missing message content"),
        ({"choices": [{"message": {"content": ""}}]}, "missing message content"),
        ({"choices": [{"message": {"content": "   "}}]}, "missing message content"),
        ({"choices": [{"message": {"content": 123}}]}, "missing message content"),
        ({"choices": [{"message": {"content": None}}]}, "missing message content"),
    ],
)
@override_settings(**OPENROUTER_SETTINGS)
@patch("apps.qualification.openrouter_client.urllib.request.urlopen")
def test_invalid_openrouter_wrapper_payloads_fail_safely(
    mock_urlopen,
    wrapper_payload: dict[str, object],
    expected_match: str,
):
    mock_urlopen.return_value = _FakeResponse(json.dumps(wrapper_payload).encode("utf-8"))

    with pytest.raises(OpenRouterResponseError, match=expected_match) as exc_info:
        extract_qualification_from_openrouter(
            customer_message=CUSTOMER_MESSAGE,
            known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
        )

    _assert_client_error_is_safe(str(exc_info.value))


@override_settings(**OPENROUTER_SETTINGS)
@patch("apps.qualification.openrouter_client.urllib.request.urlopen")
def test_invalid_provider_json_wrapper_raises_response_error(mock_urlopen):
    mock_urlopen.return_value = _FakeResponse(b"not-json")

    with pytest.raises(OpenRouterResponseError, match="not valid JSON") as exc_info:
        extract_qualification_from_openrouter(
            customer_message=CUSTOMER_MESSAGE,
            known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
        )

    _assert_client_error_is_safe(str(exc_info.value))


@override_settings(**OPENROUTER_SETTINGS)
@patch("apps.qualification.openrouter_client.urllib.request.urlopen")
def test_missing_assistant_content_raises_response_error(mock_urlopen):
    mock_urlopen.return_value = _FakeResponse(json.dumps({"choices": []}).encode("utf-8"))

    with pytest.raises(OpenRouterResponseError, match="missing choices"):
        extract_qualification_from_openrouter(
            customer_message=CUSTOMER_MESSAGE,
            known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
        )


@override_settings(**OPENROUTER_SETTINGS)
@patch("apps.qualification.openrouter_client.urllib.request.urlopen")
def test_malformed_assistant_json_propagates_parser_error_safely(mock_urlopen):
    mock_urlopen.return_value = _FakeResponse(
        json.dumps(_openrouter_wrapper_payload(RAW_ASSISTANT_JSON)).encode("utf-8")
    )

    with pytest.raises(ExtractionParseError, match="Invalid JSON") as exc_info:
        extract_qualification_from_openrouter(
            customer_message=CUSTOMER_MESSAGE,
            known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
        )

    _assert_client_error_is_safe(str(exc_info.value))
    assert RAW_ASSISTANT_JSON not in str(exc_info.value)


@override_settings(**OPENROUTER_SETTINGS)
@patch("django.db.connection.cursor")
@patch("apps.qualification.openrouter_client.urllib.request.urlopen")
def test_no_database_write_occurs(mock_urlopen, mock_cursor):
    mock_urlopen.return_value = _FakeResponse(
        _openrouter_wrapper_bytes(_valid_extraction_payload())
    )

    extract_qualification_from_openrouter(
        customer_message=CUSTOMER_MESSAGE,
        known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
    )

    mock_cursor.assert_not_called()
