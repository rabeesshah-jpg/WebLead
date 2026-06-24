"""MessageSid idempotency cache for qualification turns."""

from __future__ import annotations

from typing import Any

_turn_responses_by_message_sid: dict[str, dict[str, Any]] = {}


def get_cached_turn_response(message_sid: str) -> dict[str, Any] | None:
    """Return a cached turn response for a processed Twilio MessageSid."""
    cached = _turn_responses_by_message_sid.get(message_sid)
    if cached is None:
        return None
    return dict(cached)


def cache_turn_response(message_sid: str, response: dict[str, Any]) -> None:
    """Store a turn response so duplicate MessageSid replays are idempotent."""
    _turn_responses_by_message_sid[message_sid] = dict(response)


def clear_message_sid_cache() -> None:
    """Clear cached MessageSid responses. Intended for tests."""
    _turn_responses_by_message_sid.clear()
