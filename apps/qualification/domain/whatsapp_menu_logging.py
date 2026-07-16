"""Structured logging helpers for WhatsApp main menu routing."""

from __future__ import annotations

import json
import logging
from typing import Any

from apps.qualification.domain.logging_utils import message_sid_prefix

logger = logging.getLogger("apps.qualification")


def _safe_user_id(whatsapp_number: str | None) -> str | None:
    """Return a non-sensitive user identifier for structured logs."""
    if not whatsapp_number:
        return None
    stripped = whatsapp_number.strip()
    if not stripped:
        return None
    return stripped[:6]


def log_whatsapp_menu_event(
    event: str,
    *,
    message_sid: str | None = None,
    user_id: str | None = None,
    selected_menu_id: str | None = None,
    **context: Any,
) -> None:
    """Emit a structured WhatsApp menu log without secrets or full phone numbers."""
    payload: dict[str, Any] = {"event": event}
    sid_prefix = message_sid_prefix(message_sid)
    if sid_prefix is not None:
        payload["message_sid"] = sid_prefix
    safe_user_id = _safe_user_id(user_id)
    if safe_user_id is not None:
        payload["user_id"] = safe_user_id
    if selected_menu_id is not None:
        payload["selected_menu_id"] = selected_menu_id
    payload.update(context)
    logger.info(json.dumps(payload, separators=(",", ":")))
