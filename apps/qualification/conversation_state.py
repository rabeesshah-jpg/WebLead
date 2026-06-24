"""In-memory qualification conversation state keyed by WhatsApp number."""

from __future__ import annotations

from typing import Any

_conversations: dict[str, dict[str, Any]] = {}


def get_accepted_fields(whatsapp_number: str) -> dict[str, Any]:
    """Return a copy of persisted accepted fields for a conversation."""
    return dict(_conversations.get(whatsapp_number, {}))


def save_accepted_fields(whatsapp_number: str, accepted_fields: dict[str, Any]) -> None:
    """Persist accepted fields for a conversation."""
    _conversations[whatsapp_number] = dict(accepted_fields)


def clear_conversations() -> None:
    """Clear all in-memory conversation state. Intended for tests."""
    _conversations.clear()
