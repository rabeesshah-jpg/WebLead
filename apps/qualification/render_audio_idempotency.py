"""Idempotency cache for render-audio responses keyed by request_id."""

from __future__ import annotations

import json
import threading
from typing import Any

from django.conf import settings

_lock = threading.Lock()
_memory_cache: dict[str, dict[str, Any]] = {}
_redis_client = None


def _get_redis_client():
    global _redis_client
    redis_url = getattr(settings, "QUALIFICATION_REDIS_URL", "")
    if not redis_url:
        return None
    if _redis_client is None:
        import redis

        _redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
    return _redis_client


def _render_cache_key(request_id: str) -> str:
    return f"qualification:render_audio:{request_id}"


def get_cached_render_response(request_id: str) -> dict[str, Any] | None:
    """Return a cached render-audio response for a processed request_id."""
    client = _get_redis_client()
    if client is not None:
        raw = client.get(_render_cache_key(request_id))
        if not raw:
            return None
        payload = json.loads(raw)
        return dict(payload) if isinstance(payload, dict) else None

    with _lock:
        cached = _memory_cache.get(request_id)
        return dict(cached) if cached is not None else None


def cache_render_response(request_id: str, response: dict[str, Any]) -> None:
    """Store a render-audio response so duplicate request_id replays are idempotent."""
    payload = dict(response)
    client = _get_redis_client()
    if client is not None:
        client.set(
            _render_cache_key(request_id),
            json.dumps(payload, separators=(",", ":")),
            ex=settings.QUALIFICATION_IDEMPOTENCY_TTL_SECONDS,
        )
        return

    with _lock:
        _memory_cache[request_id] = payload


def clear_render_audio_cache() -> None:
    """Clear cached render-audio responses. Intended for tests."""
    client = _get_redis_client()
    if client is not None:
        for key in client.scan_iter(match="qualification:render_audio:*"):
            client.delete(key)
        return

    with _lock:
        _memory_cache.clear()
