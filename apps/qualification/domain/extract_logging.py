"""Structured failure logging for the qualification extract pipeline."""

from __future__ import annotations

import json
import logging
from typing import Any

from apps.qualification.domain.extract_errors import ExtractFailureInfo

logger = logging.getLogger("apps.qualification")


def log_extract_step_failed(
    info: ExtractFailureInfo,
    *,
    message_sid: str | None = None,
) -> None:
    """Emit one safe structured failure log for an extract pipeline step."""
    payload: dict[str, Any] = {
        "step": info.failure_step,
        "error_type": info.error_type,
        "details": info.details or info.public_message,
    }
    if message_sid:
        payload["message_sid"] = message_sid
    if info.status_code is not None:
        payload["status_code"] = info.status_code
    if info.duration_ms is not None:
        payload["duration_ms"] = info.duration_ms
    logger.error(json.dumps(payload, separators=(",", ":")))
