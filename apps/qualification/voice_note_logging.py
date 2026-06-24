"""Safe structured logging for WhatsApp voice-note processing."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("apps.qualification")


def _message_sid_prefix(message_sid: str | None) -> str | None:
    if not message_sid:
        return None
    return message_sid[:8]


def log_voice_note_event(
    event: str,
    *,
    message_sid: str | None = None,
    media_content_type: str | None = None,
    http_status: int | None = None,
    elapsed_ms: int | None = None,
    level: int = logging.ERROR,
) -> None:
    """Emit a JSON log line without secrets, URLs, audio, or transcript content."""
    payload: dict[str, Any] = {"event": event}
    sid_prefix = _message_sid_prefix(message_sid)
    if sid_prefix:
        payload["message_sid_prefix"] = sid_prefix
    if media_content_type:
        payload["media_content_type"] = media_content_type
    if http_status is not None:
        payload["http_status"] = http_status
    if elapsed_ms is not None:
        payload["elapsed_ms"] = elapsed_ms
    logger.log(level, json.dumps(payload, separators=(",", ":")))
