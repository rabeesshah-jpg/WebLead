"""Tests for optimized OpenRouter prompt construction."""

from __future__ import annotations

import json
from unittest.mock import patch

from django.test import override_settings

from apps.qualification.integrations.openrouter import request_openrouter_completion
from apps.qualification.prompts import build_extraction_user_message

OPENROUTER_SETTINGS = {
    "OPENROUTER_API_KEY": "test-openrouter-api-key",
    "OPENROUTER_MODEL": "test/openrouter-model",
    "OPENROUTER_BASE_URL": "https://openrouter.example/api/v1",
    "OPENROUTER_TIMEOUT_SECONDS": 20,
    "OPENROUTER_COMPLETION_MAX_TOKENS": 120,
}

CUSTOMER_MESSAGE = "I need a website for my bakery"
KNOWN_WHATSAPP_NUMBER = "+15551234567"


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


def _openrouter_wrapper_bytes(content: str) -> bytes:
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")


@override_settings(**OPENROUTER_SETTINGS)
@patch("apps.qualification.integrations.openrouter.urllib.request.urlopen")
@patch("apps.qualification.integrations.openrouter.log_latency_step")
def test_openrouter_prompt_optimized_log_emitted_with_compact_payload(mock_log_step, mock_urlopen):
    captured: dict[str, object] = {}

    def _capture_open(request, timeout=0):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(_openrouter_wrapper_bytes('{"project_type":"new_website"}'))

    mock_urlopen.side_effect = _capture_open

    history = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Are you looking for a new website or an upgrade?"},
        {"role": "user", "content": "New website"},
        {"role": "assistant", "content": "What are you specifically looking for?"},
        {"role": "user", "content": "A bakery site"},
        {"role": "assistant", "content": "How did you hear about us?"},
        {"role": "user", "content": "Instagram"},
        {"role": "assistant", "content": "Is this WhatsApp number the best number to reach you?"},
    ]

    request_openrouter_completion(
        CUSTOMER_MESSAGE,
        KNOWN_WHATSAPP_NUMBER,
        phone_confirmation_question_asked=True,
        message_sid="MM0cc5a1d9e22bf9850ca24261ee23ce90",
        collected_fields={"project_type": "new_website", "requirements": "bakery site"},
        conversation_history=history,
    )

    body = captured["body"]
    user_payload = json.loads(body["messages"][1]["content"])
    assert user_payload["current_message"] == CUSTOMER_MESSAGE
    assert user_payload["collected_fields"] == {
        "project_type": "new_website",
        "requirements": "bakery site",
    }
    assert len(user_payload["recent_history"]) == 6
    assert user_payload["recent_history"] == history[-6:]
    assert body["max_tokens"] == 120

    prompt_length = len(json.dumps(body).encode("utf-8"))
    assert 1000 <= prompt_length <= 1700

    optimized_log = next(
        call
        for call in mock_log_step.call_args_list
        if call.args and call.args[0] == "openrouter_prompt_optimized"
    )
    assert optimized_log.kwargs["message_sid"] == "MM0cc5a1d9e22bf9850ca24261ee23ce90"
    assert optimized_log.kwargs["history_messages_count"] == 8
    assert optimized_log.kwargs["recent_history_messages_count"] == 6
    assert optimized_log.kwargs["max_tokens"] == 120
    assert optimized_log.kwargs["prompt_length"] == prompt_length
    assert optimized_log.kwargs["system_prompt_length"] > 0


def test_build_extraction_user_message_uses_json_payload_shape():
    content = build_extraction_user_message(
        customer_message="Need a redesign",
        known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
        phone_confirmation_question_asked=False,
        collected_fields={"project_type": "website_upgrade"},
        recent_history=[{"role": "user", "content": "Hello"}],
    )
    payload = json.loads(content)
    assert payload["current_message"] == "Need a redesign"
    assert payload["collected_fields"] == {"project_type": "website_upgrade"}
    assert payload["recent_history"] == [{"role": "user", "content": "Hello"}]
