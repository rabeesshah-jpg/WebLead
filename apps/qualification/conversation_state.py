"""Qualification conversation state keyed by WhatsApp number."""

from __future__ import annotations

from typing import Any

from apps.qualification.persistence.backends import get_persistence_backend

RECENT_HISTORY_MESSAGE_LIMIT = 6


def get_accepted_fields(whatsapp_number: str) -> dict[str, Any]:
    """Return a copy of persisted accepted fields for a conversation."""
    return get_persistence_backend().get_conversation_fields(whatsapp_number)


def save_accepted_fields(whatsapp_number: str, accepted_fields: dict[str, Any]) -> None:
    """Persist accepted fields for a conversation."""
    get_persistence_backend().save_conversation_fields(whatsapp_number, accepted_fields)


def get_conversation_history(whatsapp_number: str) -> list[dict[str, str]]:
    """Return stored conversation turns for a WhatsApp number."""
    return get_persistence_backend().get_conversation_history(whatsapp_number)


def get_recent_conversation_history(
    whatsapp_number: str,
    *,
    limit: int = RECENT_HISTORY_MESSAGE_LIMIT,
) -> list[dict[str, str]]:
    """Return only the most recent conversation turns for prompt context."""
    history = get_conversation_history(whatsapp_number)
    if limit <= 0:
        return []
    return history[-limit:]


def append_conversation_turn(
    whatsapp_number: str,
    *,
    user_message: str,
    assistant_reply: str,
) -> None:
    """Persist one user/assistant exchange for later prompt context."""
    normalized_user = " ".join(user_message.split())
    normalized_reply = " ".join(assistant_reply.split())
    if not normalized_user and not normalized_reply:
        return
    get_persistence_backend().append_conversation_turn(
        whatsapp_number,
        user_message=normalized_user,
        assistant_reply=normalized_reply,
    )


def clear_conversations() -> None:
    """Clear all conversation state. Intended for tests."""
    get_persistence_backend().clear_conversations()
