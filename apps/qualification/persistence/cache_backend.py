"""Shared qualification cache backend (Redis with in-memory fallback)."""

from __future__ import annotations

import base64
import threading
from typing import Any, Protocol

from django.conf import settings


class QualificationCacheBackend(Protocol):
    """Cross-worker cache for non-authoritative performance data only."""

    @property
    def backend_name(self) -> str:
        ...

    def get(self, key: str) -> Any | None:
        ...

    def set(self, key: str, value: Any, ttl: int) -> None:
        ...

    def delete(self, key: str) -> None:
        ...

    def delete_by_prefix(self, prefix: str) -> None:
        ...


def _encode_cache_value(value: Any) -> str:
    if isinstance(value, bytes):
        return f"b64:{base64.b64encode(value).decode('ascii')}"
    if isinstance(value, str):
        return f"str:{value}"
    raise TypeError("Cache values must be bytes or str")


def _decode_cache_value(raw: str) -> Any:
    if raw.startswith("b64:"):
        return base64.b64decode(raw[4:])
    if raw.startswith("str:"):
        return raw[4:]
    return raw


class InMemoryQualificationCacheBackend:
    """Process-local cache for development and tests."""

    backend_name = "memory"

    def __init__(self) -> None:
        self._entries: dict[str, tuple[Any, float | None]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        import time

        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at is not None and time.time() >= expires_at:
                del self._entries[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl: int) -> None:
        import time

        expires_at = time.time() + ttl if ttl > 0 else None
        with self._lock:
            self._entries[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def delete_by_prefix(self, prefix: str) -> None:
        with self._lock:
            keys = [key for key in self._entries if key.startswith(prefix)]
            for key in keys:
                del self._entries[key]


class RedisQualificationCacheBackend:
    """Redis-backed cache shared across workers."""

    backend_name = "redis"

    def __init__(self, *, redis_url: str) -> None:
        import redis

        self._client = redis.Redis.from_url(redis_url, decode_responses=True)

    def get(self, key: str) -> Any | None:
        raw = self._client.get(key)
        if raw is None:
            return None
        if not isinstance(raw, str):
            return None
        return _decode_cache_value(raw)

    def set(self, key: str, value: Any, ttl: int) -> None:
        self._client.set(key, _encode_cache_value(value), ex=ttl)

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def delete_by_prefix(self, prefix: str) -> None:
        for key in self._client.scan_iter(match=f"{prefix}*"):
            self._client.delete(key)


_cache_backend: QualificationCacheBackend | None = None


def get_qualification_cache_backend() -> QualificationCacheBackend:
    global _cache_backend
    if _cache_backend is not None:
        return _cache_backend

    redis_url = getattr(settings, "QUALIFICATION_REDIS_URL", "")
    if redis_url:
        _cache_backend = RedisQualificationCacheBackend(redis_url=redis_url)
    else:
        _cache_backend = InMemoryQualificationCacheBackend()
    return _cache_backend


def reset_qualification_cache_backend_for_tests() -> None:
    """Reset cache backend singleton. Intended for tests only."""
    global _cache_backend
    _cache_backend = None


def twilio_media_cache_key(*, message_sid: str | None, media_url: str) -> str:
    identifier = message_sid or media_url
    return f"twilio_media:{identifier}"


def openrouter_cache_key(cache_digest: str) -> str:
    return f"openrouter:{cache_digest}"


def voice_turn_latency_cache_key(message_sid: str) -> str:
    return f"voice_latency:{message_sid}"


def default_cache_ttl_seconds() -> int:
    return int(getattr(settings, "QUALIFICATION_CACHE_TTL_SECONDS", 86400))
