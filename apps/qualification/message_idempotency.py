"""MessageSid idempotency cache for qualification turns."""

from __future__ import annotations

from typing import Any

from apps.qualification.persistence.backends import get_persistence_backend


def get_cached_turn_response(message_sid: str) -> dict[str, Any] | None:
    """Return a cached turn response for a processed Twilio MessageSid."""
    return get_persistence_backend().get_turn_response(message_sid)


def begin_idempotent_turn(message_sid: str) -> dict[str, Any] | None:
    """
    Return a cached response when the MessageSid was already processed.

    Return None when this caller acquired the exclusive processing slot.

    Production uses Redis SET NX via ``RedisPersistenceBackend.begin_turn()`` so
    only one worker processes a MessageSid at a time. Concurrent workers wait
    for the cached response instead of duplicating work. In-memory fallback is
    intended for development and tests only.
    """
    return get_persistence_backend().begin_turn(message_sid)


def cache_turn_response(message_sid: str, response: dict[str, Any]) -> None:
    """Store a turn response so duplicate MessageSid replays are idempotent."""
    get_persistence_backend().set_turn_response(message_sid, response)


def clear_message_sid_cache() -> None:
    """Clear cached MessageSid responses. Intended for tests."""
    get_persistence_backend().clear_message_sid_cache()
