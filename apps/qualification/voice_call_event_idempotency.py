"""Event-id idempotency cache for voice-call completion webhooks."""

from __future__ import annotations

from typing import Any

from apps.qualification.message_idempotency import (
    begin_idempotent_turn,
    cache_turn_response,
    get_cached_turn_response,
)

VOICE_CALL_EVENT_KEY_PREFIX = "voice-call-event:"


def _cache_key(event_id: str) -> str:
    return f"{VOICE_CALL_EVENT_KEY_PREFIX}{event_id}"


def get_cached_voice_call_response(event_id: str) -> dict[str, Any] | None:
    """Return a cached response for a processed voice-call completion event."""
    return get_cached_turn_response(_cache_key(event_id))


def begin_voice_call_event(event_id: str) -> dict[str, Any] | None:
    """
    Return a cached response when the event was already processed.

    Return None when this caller should process the event.
    """
    return begin_idempotent_turn(_cache_key(event_id))


def cache_voice_call_response(event_id: str, response: dict[str, Any]) -> None:
    """Store a response so duplicate event_id replays are idempotent."""
    cache_turn_response(_cache_key(event_id), response)
