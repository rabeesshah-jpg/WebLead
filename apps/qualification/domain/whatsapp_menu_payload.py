"""Extract canonical WhatsApp main-menu selections from Twilio inbound payloads."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from apps.qualification.domain.whatsapp_menu_config import resolve_menu_item_id

_INTERACTIVE_PAYLOAD_FIELD_NAMES: tuple[str, ...] = (
    "button_payload",
    "ButtonPayload",
    "buttonPayload",
    "postbackData",
    "postback_data",
    "ListId",
    "listId",
    "list_item_id",
    "id",
)

_JSON_PAYLOAD_PATHS: tuple[tuple[str, ...], ...] = (
    ("buttonPayload",),
    ("ButtonPayload",),
    ("data", "context", "buttonPayload"),
    ("data", "context", "suggestionResponse", "postbackData"),
    ("list_reply", "id"),
    ("interactive", "list_reply", "id"),
    ("interactive", "button_reply", "id"),
)


def normalize_menu_selection_token(value: str | None) -> str:
    """Backward-compatible alias for menu payload normalization."""
    from apps.qualification.domain.whatsapp_menu_config import normalize_menu_payload

    return normalize_menu_payload(value)


def _coerce_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _resolve_raw_menu_token(raw: str, *, source: str, debug: dict[str, Any]) -> str | None:
    menu_id = resolve_menu_item_id(button_payload=raw)
    if menu_id is not None:
        debug["resolved_menu_item_id"] = menu_id
        debug["resolution_source"] = source
        return menu_id
    return None


def _walk_json_payload_paths(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return []

    found: list[str] = []
    for path in _JSON_PAYLOAD_PATHS:
        current: Any = data
        for key in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if isinstance(current, str) and current.strip():
            found.append(current.strip())

    for key in _INTERACTIVE_PAYLOAD_FIELD_NAMES:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            found.append(value.strip())

    return found


def _payloads_from_interactive_blob(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        return _walk_json_payload_paths(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return _walk_json_payload_paths(parsed)
    return []


def _body_candidates(body: str | None) -> list[str]:
    normalized = _coerce_optional_string(body)
    if normalized is None:
        return []

    candidates = [normalized]
    if ":" in normalized:
        tail = normalized.rsplit(":", 1)[-1].strip()
        if tail and tail not in candidates:
            candidates.append(tail)
    return candidates


def extract_menu_selection_payload(
    request_data: Mapping[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    """
    Extract the canonical interactive WhatsApp menu payload.

    Priority:
    1. ``ButtonPayload`` / ``button_payload``
    2. ``InteractiveData`` / ``ChannelMetadata``
    3. ``Body`` / ``message`` fallback when it matches a known menu keyword

    Returns ``(menu_id, debug_context)`` where debug_context preserves raw values.
    """
    raw_button_payload = _coerce_optional_string(request_data.get("button_payload")) or _coerce_optional_string(
        request_data.get("ButtonPayload")
    )
    raw_body = _coerce_optional_string(request_data.get("message")) or _coerce_optional_string(
        request_data.get("Body")
    )

    debug: dict[str, Any] = {
        "raw_button_payload": raw_button_payload,
        "raw_button_text": _coerce_optional_string(request_data.get("button_text"))
        or _coerce_optional_string(request_data.get("ButtonText")),
        "raw_body": raw_body,
        "raw_message": raw_body,
        "raw_interactive_data": request_data.get("interactive_data")
        if request_data.get("interactive_data") is not None
        else request_data.get("InteractiveData"),
        "raw_channel_metadata": request_data.get("channel_metadata")
        if request_data.get("channel_metadata") is not None
        else request_data.get("ChannelMetadata"),
        "fallback_used": False,
    }

    for field_name in ("button_payload", "ButtonPayload"):
        raw = _coerce_optional_string(request_data.get(field_name))
        if raw is None:
            continue
        debug["candidate_field"] = field_name
        menu_id = _resolve_raw_menu_token(raw, source=field_name, debug=debug)
        if menu_id is not None:
            return menu_id, debug

    for blob_field in (
        "interactive_data",
        "InteractiveData",
        "channel_metadata",
        "ChannelMetadata",
    ):
        for raw in _payloads_from_interactive_blob(request_data.get(blob_field)):
            debug["candidate_field"] = blob_field
            menu_id = _resolve_raw_menu_token(raw, source=blob_field, debug=debug)
            if menu_id is not None:
                return menu_id, debug

    if raw_body is not None:
        for candidate in _body_candidates(raw_body):
            debug["candidate_field"] = "message"
            debug["body_candidate"] = candidate
            menu_id = resolve_menu_item_id(button_payload=candidate)
            if menu_id is not None:
                debug["resolved_menu_item_id"] = menu_id
                debug["resolution_source"] = "message"
                debug["fallback_used"] = True
                return menu_id, debug

    debug["resolved_menu_item_id"] = None
    return None, debug
