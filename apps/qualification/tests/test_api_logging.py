"""Tests for shared qualification API logging helpers."""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

from django.test import RequestFactory

from apps.qualification.api import logging as api_logging
from apps.qualification.domain import logging_utils
from apps.qualification.views import _log_event, _message_sid_prefix


def test_message_sid_prefix_returns_first_eight_characters():
    assert logging_utils.message_sid_prefix("SM0cc5a1d9e22bf9850ca24261ee23ce90") == "SM0cc5a1"


def test_message_sid_prefix_none_returns_none():
    assert logging_utils.message_sid_prefix(None) is None


@patch("apps.qualification.api.logging.logger")
def test_log_qualification_event_uses_expected_shape(mock_logger):
    api_logging.log_qualification_event(
        "qualification_internal_auth_failed",
        level=logging.WARNING,
        request_path="/api/internal/qualification/extract/",
    )

    mock_logger.log.assert_called_once()
    level, message = mock_logger.log.call_args.args
    assert level == logging.WARNING
    payload = json.loads(message)
    assert payload["event"] == "qualification_internal_auth_failed"
    assert payload["request_path"] == "/api/internal/qualification/extract/"
    assert "timestamp" in payload
    assert "secret" not in message
    assert "Authorization" not in message


@patch("apps.qualification.api.logging.logger")
def test_log_upstream_timeout_includes_safe_turn_metadata(mock_logger):
    request = RequestFactory().post("/api/internal/qualification/extract/")
    turn_request = MagicMock()
    turn_request.input_channel = "whatsapp_text"
    turn_request.message_sid = "SM0cc5a1d9e22bf9850ca24261ee23ce90"

    api_logging.log_upstream_timeout(
        request,
        turn_request=turn_request,
        elapsed_ms=1234,
    )

    payload = json.loads(mock_logger.log.call_args.args[1])
    assert payload == {
        "event": "qualification_internal_upstream_timeout",
        "request_path": "/api/internal/qualification/extract/",
        "provider": "openrouter",
        "elapsed_ms": 1234,
        "input_channel": "whatsapp_text",
        "message_sid_prefix": "SM0cc5a1",
        "timestamp": payload["timestamp"]}
    assert "SM0cc5a1d9e22bf9850ca24261ee23ce90" not in mock_logger.log.call_args.args[1]


@patch("apps.qualification.views.log_qualification_request_event")
def test_views_log_event_wrapper_delegates(mock_log_request_event):
    request = RequestFactory().post("/api/internal/qualification/extract/")

    _log_event(request, "qualification_internal_invalid_request", level=logging.WARNING)

    mock_log_request_event.assert_called_once_with(
        request,
        "qualification_internal_invalid_request",
        level=logging.WARNING,
    )


def test_views_message_sid_prefix_wrapper_delegates():
    assert _message_sid_prefix("MM0cc5a1d9e22bf9850ca24261ee23ce90") == "MM0cc5a1"
