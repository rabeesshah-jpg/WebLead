"""Tests for the OpenRouter HTTP transport layer."""

from __future__ import annotations

import io
import json
import socket
import urllib.error
from unittest.mock import patch

import pytest
from django.test import override_settings

from apps.qualification.integrations.openrouter import (
    OpenRouterConfigurationError,
    OpenRouterRequestError,
    OpenRouterResponseError,
    OpenRouterTimeoutError,
    request_openrouter_completion,
)
from apps.qualification.prompts import EXTRACTION_SYSTEM_PROMPT, build_extraction_user_message

TEST_API_KEY = "test-openrouter-api-key"
TEST_MODEL = "test/openrouter-model"
CUSTOMER_MESSAGE = "I need a new website for my bakery"
KNOWN_WHATSAPP_NUMBER = "+15551234567"
PROVIDER_ERROR_DETAIL = "provider secret failure details"
QUALIFICATION_JSON = '{"project_type":"new_website"}'

OPENROUTER_SETTINGS = {
    "OPENROUTER_API_KEY": TEST_API_KEY,
    "OPENROUTER_MODEL": TEST_MODEL,
    "OPENROUTER_BASE_URL": "https://openrouter.example/api/v1",
    "OPENROUTER_TIMEOUT_SECONDS": 20,
    "OPENROUTER_MAX_TOKENS": 768,
    "OPENROUTER_COMPLETION_MAX_TOKENS": 120,
}


def _openrouter_wrapper_bytes(content: str) -> bytes:
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")


def _assert_transport_error_is_safe(error_message: str) -> None:
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
@patch("apps.qualification.integrations.openrouter.urllib.request.urlopen")
def test_request_construction_unchanged(mock_urlopen):
    captured: dict[str, object] = {}

    def _capture_open(request, timeout=0):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(_openrouter_wrapper_bytes(QUALIFICATION_JSON))

    mock_urlopen.side_effect = _capture_open

    result = request_openrouter_completion(
        customer_message=CUSTOMER_MESSAGE,
        known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
    )

    assert result == QUALIFICATION_JSON
    assert captured["url"] == "https://openrouter.example/api/v1/chat/completions"
    assert captured["timeout"] == 20

    headers = captured["headers"]
    assert headers["Content-type"] == "application/json"
    assert headers["Authorization"] == f"Bearer {TEST_API_KEY}"

    body = captured["body"]
    assert body["model"] == TEST_MODEL
    assert body["stream"] is False
    assert body["max_tokens"] == 120
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
    assert "response_format" in body
    assert body["response_format"] == {"type": "json_object"}
    assert len(json.dumps(body).encode("utf-8")) <= 1500


@override_settings(**OPENROUTER_SETTINGS)
@patch("apps.qualification.integrations.openrouter.urllib.request.urlopen")
def test_transport_returns_raw_assistant_text_without_parsing_json(mock_urlopen):
    mock_urlopen.return_value = _FakeResponse(_openrouter_wrapper_bytes("not-valid-qualification-json"))

    result = request_openrouter_completion(
        customer_message=CUSTOMER_MESSAGE,
        known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
    )

    assert result == "not-valid-qualification-json"


@override_settings(OPENROUTER_API_KEY="", OPENROUTER_MODEL=TEST_MODEL)
def test_missing_api_key_raises_configuration_error_without_request():
    with patch("apps.qualification.integrations.openrouter.urllib.request.urlopen") as mock_urlopen:
        with pytest.raises(OpenRouterConfigurationError, match="API key"):
            request_openrouter_completion(
                customer_message=CUSTOMER_MESSAGE,
                known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
            )
        mock_urlopen.assert_not_called()


@override_settings(OPENROUTER_API_KEY=TEST_API_KEY, OPENROUTER_MODEL="")
def test_missing_model_raises_configuration_error_without_request():
    with patch("apps.qualification.integrations.openrouter.urllib.request.urlopen") as mock_urlopen:
        with pytest.raises(OpenRouterConfigurationError, match="model"):
            request_openrouter_completion(
                customer_message=CUSTOMER_MESSAGE,
                known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
            )
        mock_urlopen.assert_not_called()


@override_settings(**OPENROUTER_SETTINGS)
@patch("apps.qualification.integrations.openrouter.urllib.request.urlopen")
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
def test_timeout_failures_raise_openrouter_timeout_error(mock_urlopen, urlopen_side_effect):
    mock_urlopen.side_effect = urlopen_side_effect

    with pytest.raises(OpenRouterTimeoutError, match="OpenRouter request timed out") as exc_info:
        request_openrouter_completion(
            customer_message=CUSTOMER_MESSAGE,
            known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
        )

    _assert_transport_error_is_safe(str(exc_info.value))
    assert isinstance(exc_info.value, OpenRouterRequestError)


@override_settings(**OPENROUTER_SETTINGS)
@patch("apps.qualification.integrations.openrouter.urllib.request.urlopen")
def test_non_timeout_urlerror_maps_to_request_error(mock_urlopen):
    mock_urlopen.side_effect = urllib.error.URLError("connection refused")

    with pytest.raises(OpenRouterRequestError, match="OpenRouter request failed") as exc_info:
        request_openrouter_completion(
            customer_message=CUSTOMER_MESSAGE,
            known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
        )

    assert not isinstance(exc_info.value, OpenRouterTimeoutError)
    _assert_transport_error_is_safe(str(exc_info.value))


@override_settings(**OPENROUTER_SETTINGS)
@patch("apps.qualification.integrations.openrouter.urllib.request.urlopen")
def test_timeout_records_elapsed_ms(mock_urlopen):
    mock_urlopen.side_effect = urllib.error.URLError("timed out")

    with pytest.raises(OpenRouterTimeoutError):
        request_openrouter_completion(
            customer_message=CUSTOMER_MESSAGE,
            known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
        )

    assert request_openrouter_completion.last_elapsed_ms >= 0


@pytest.mark.parametrize("status_code", [429, 500, 502])
@override_settings(**OPENROUTER_SETTINGS)
@patch("apps.qualification.integrations.openrouter.urllib.request.urlopen")
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
        request_openrouter_completion(
            customer_message=CUSTOMER_MESSAGE,
            known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
        )

    _assert_transport_error_is_safe(str(exc_info.value))


@override_settings(**OPENROUTER_SETTINGS)
@patch("apps.qualification.integrations.openrouter.urllib.request.urlopen")
def test_invalid_provider_json_raises_response_error(mock_urlopen):
    mock_urlopen.return_value = _FakeResponse(b"not-json")

    with pytest.raises(OpenRouterResponseError, match="not valid JSON") as exc_info:
        request_openrouter_completion(
            customer_message=CUSTOMER_MESSAGE,
            known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
        )

    _assert_transport_error_is_safe(str(exc_info.value))
