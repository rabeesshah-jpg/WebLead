"""Shared safe logging helpers for qualification internal APIs."""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from django.http import HttpRequest
from django.utils import timezone

from apps.qualification.domain.logging_utils import message_sid_prefix

logger = logging.getLogger("apps.qualification")


class TurnRequestContext(Protocol):
    input_channel: str
    message_sid: str | None


def safe_failure_type(exc: BaseException) -> str:
    """Return a safe exception label for internal logs without sensitive details."""
    cause = exc.__cause__
    if cause is not None:
        return f"{type(exc).__name__}:{type(cause).__name__}"
    return type(exc).__name__


def log_qualification_event(event_name: str, *, level: int = logging.INFO, **context: Any) -> None:
    """Emit one qualification log event using the project's existing logger and JSON shape."""
    try:
        payload: dict[str, Any] = {"event": event_name, **context}
        if "timestamp" not in payload:
            payload["timestamp"] = timezone.now().isoformat()
        logger.log(level, json.dumps(payload, separators=(",", ":"), default=str))
    except Exception:
        logger.exception(
            "qualification_log_event_failed",
            extra={"event": event_name},
        )


def log_qualification_request_event(
    request: HttpRequest,
    event_name: str,
    *,
    level: int = logging.INFO,
    **extra: Any,
) -> None:
    """Emit a request-scoped qualification log event with the existing metadata keys."""
    log_qualification_event(event_name, level=level, request_path=request.path, **extra)


def _turn_request_context(turn_request: TurnRequestContext | None) -> dict[str, Any]:
    if turn_request is None:
        return {}

    context: dict[str, Any] = {"input_channel": turn_request.input_channel}
    sid_prefix = message_sid_prefix(turn_request.message_sid)
    if sid_prefix:
        context["message_sid_prefix"] = sid_prefix
    return context


def log_service_unavailable(
    request: HttpRequest,
    exc: BaseException,
    *,
    turn_request: TurnRequestContext | None = None,
) -> None:
    log_qualification_request_event(
        request,
        "qualification_internal_service_unavailable",
        level=logging.ERROR,
        failure_type=safe_failure_type(exc),
        **_turn_request_context(turn_request),
    )


def log_upstream_request_failed(
    request: HttpRequest,
    exc: BaseException,
    *,
    turn_request: TurnRequestContext | None = None,
) -> None:
    log_qualification_request_event(
        request,
        "qualification_internal_upstream_failed",
        level=logging.ERROR,
        failure_type=safe_failure_type(exc),
        **_turn_request_context(turn_request),
    )


def log_upstream_timeout(
    request: HttpRequest,
    *,
    turn_request: TurnRequestContext | None = None,
    provider: str = "openrouter",
    elapsed_ms: int | None = None,
) -> None:
    context: dict[str, Any] = {"provider": provider, **_turn_request_context(turn_request)}
    if elapsed_ms is not None:
        context["elapsed_ms"] = elapsed_ms
    log_qualification_request_event(
        request,
        "qualification_internal_upstream_timeout",
        level=logging.ERROR,
        **context,
    )


def log_unexpected_error(
    request: HttpRequest,
    exc: BaseException,
    *,
    turn_request: TurnRequestContext | None = None,
) -> None:
    """Log unexpected extract failures with full traceback for operators."""
    context = {
        "event": "qualification_internal_unexpected_error",
        "request_path": request.path,
        "failure_type": safe_failure_type(exc),
        "timestamp": timezone.now().isoformat(),
        **_turn_request_context(turn_request),
    }
    logger.exception(
        json.dumps(context, separators=(",", ":"), default=str),
    )
