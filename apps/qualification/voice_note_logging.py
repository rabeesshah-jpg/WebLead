"""Safe structured logging for WhatsApp voice-note processing."""

from __future__ import annotations

import json
import logging
from typing import Any

from apps.qualification.domain.logging_utils import message_sid_prefix

logger = logging.getLogger("apps.qualification")


def log_voice_note_event(
    event: str,
    *,
    message_sid: str | None = None,
    media_content_type: str | None = None,
    conversation_language: str | None = None,
    deepgram_model: str | None = None,
    deepgram_language: str | None = None,
    error_type: str | None = None,
    http_status: int | None = None,
    elapsed_ms: int | None = None,
    level: int = logging.ERROR,
) -> None:
    """Emit a JSON log line without secrets, URLs, audio, or transcript content."""
    payload: dict[str, Any] = {"event": event}
    sid_prefix = message_sid_prefix(message_sid)
    if sid_prefix:
        payload["message_sid_prefix"] = sid_prefix
    if media_content_type:
        payload["media_content_type"] = media_content_type
    if conversation_language:
        payload["conversation_language"] = conversation_language
    if deepgram_model:
        payload["deepgram_model"] = deepgram_model
    if deepgram_language:
        payload["deepgram_language"] = deepgram_language
    if error_type:
        payload["error_type"] = error_type
    if http_status is not None:
        payload["http_status"] = http_status
    if elapsed_ms is not None:
        payload["elapsed_ms"] = elapsed_ms
    logger.log(level, json.dumps(payload, separators=(",", ":")))
