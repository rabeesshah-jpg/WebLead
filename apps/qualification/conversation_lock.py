"""Per-user conversation turn locks for qualification extract processing."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Protocol

from django.conf import settings
from django.db import connection

from apps.qualification.domain.latency_profiling import elapsed_ms_since

logger = logging.getLogger("apps.qualification")

DEFAULT_LOCK_WAIT_TIMEOUT_SECONDS = 6.0
DEFAULT_LOCK_TTL_SECONDS = 60
_LOCK_POLL_INTERVAL_SECONDS = 0.05


@dataclass(frozen=True)
class ConversationLockAcquireResult:
    acquired: bool
    timed_out: bool
    wait_ms: int
    token: str | None = None


class ConversationLockBackend(Protocol):
    def acquire(
        self,
        lock_key: str,
        *,
        wait_timeout_seconds: float,
        lock_ttl_seconds: int,
    ) -> ConversationLockAcquireResult:
        ...

    def release(self, lock_key: str, token: str | None) -> None:
        ...


@dataclass
class ConversationTurnLockHandle:
    lock_key: str
    token: str | None
    acquired: bool
    timed_out: bool
    wait_ms: int
    _backend: ConversationLockBackend
    _released: bool = False

    def release(self) -> None:
        if self._released or not self.acquired:
            return
        self._backend.release(self.lock_key, self.token)
        self._released = True


class InMemoryConversationLockBackend:
    """Process-local per-user locks for tests and single-worker development."""

    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._registry_lock = threading.Lock()

    def _lock_for_key(self, lock_key: str) -> threading.Lock:
        with self._registry_lock:
            lock = self._locks.get(lock_key)
            if lock is None:
                lock = threading.Lock()
                self._locks[lock_key] = lock
            return lock

    def acquire(
        self,
        lock_key: str,
        *,
        wait_timeout_seconds: float,
        lock_ttl_seconds: int,
    ) -> ConversationLockAcquireResult:
        del lock_ttl_seconds
        started = time.perf_counter()
        acquired = self._lock_for_key(lock_key).acquire(
            blocking=True,
            timeout=wait_timeout_seconds,
        )
        wait_ms = elapsed_ms_since(started)
        if acquired:
            return ConversationLockAcquireResult(
                acquired=True,
                timed_out=False,
                wait_ms=wait_ms,
                token="memory",
            )
        return ConversationLockAcquireResult(
            acquired=False,
            timed_out=True,
            wait_ms=wait_ms,
        )

    def release(self, lock_key: str, token: str | None) -> None:
        del token
        lock = self._locks.get(lock_key)
        if lock is not None and lock.locked():
            lock.release()

    def clear_locks_for_tests(self) -> None:
        with self._registry_lock:
            self._locks.clear()


class RedisConversationLockBackend:
    """Redis-backed per-user locks shared across workers."""

    _RELEASE_SCRIPT = """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("del", KEYS[1])
    end
    return 0
    """

    def __init__(self, *, redis_url: str) -> None:
        import redis

        self._client = redis.Redis.from_url(redis_url, decode_responses=True)
        self._release_script = self._client.register_script(self._RELEASE_SCRIPT)

    def acquire(
        self,
        lock_key: str,
        *,
        wait_timeout_seconds: float,
        lock_ttl_seconds: int,
    ) -> ConversationLockAcquireResult:
        started = time.perf_counter()
        deadline = started + wait_timeout_seconds
        token = str(uuid.uuid4())
        while time.perf_counter() < deadline:
            if self._client.set(lock_key, token, nx=True, ex=lock_ttl_seconds):
                return ConversationLockAcquireResult(
                    acquired=True,
                    timed_out=False,
                    wait_ms=elapsed_ms_since(started),
                    token=token,
                )
            time.sleep(_LOCK_POLL_INTERVAL_SECONDS)
        return ConversationLockAcquireResult(
            acquired=False,
            timed_out=True,
            wait_ms=elapsed_ms_since(started),
        )

    def release(self, lock_key: str, token: str | None) -> None:
        if not token:
            return
        self._release_script(keys=[lock_key], args=[token])


class PostgresAdvisoryConversationLockBackend:
    """PostgreSQL advisory locks for multi-worker deployments without Redis."""

    @staticmethod
    def _advisory_key(lock_key: str) -> int:
        digest = hashlib.sha256(lock_key.encode("utf-8")).digest()[:8]
        value = int.from_bytes(digest, byteorder="big", signed=False)
        return value % (2**63)

    def acquire(
        self,
        lock_key: str,
        *,
        wait_timeout_seconds: float,
        lock_ttl_seconds: int,
    ) -> ConversationLockAcquireResult:
        del lock_ttl_seconds
        started = time.perf_counter()
        advisory_key = self._advisory_key(lock_key)
        deadline = started + wait_timeout_seconds
        while time.perf_counter() < deadline:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", [advisory_key])
                row = cursor.fetchone()
                if row and row[0]:
                    return ConversationLockAcquireResult(
                        acquired=True,
                        timed_out=False,
                        wait_ms=elapsed_ms_since(started),
                        token=str(advisory_key),
                    )
            time.sleep(_LOCK_POLL_INTERVAL_SECONDS)
        return ConversationLockAcquireResult(
            acquired=False,
            timed_out=True,
            wait_ms=elapsed_ms_since(started),
        )

    def release(self, lock_key: str, token: str | None) -> None:
        del lock_key
        if token is None:
            return
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [int(token)])


_backend: ConversationLockBackend | None = None


def _lock_wait_timeout_seconds() -> float:
    raw = getattr(settings, "QUALIFICATION_CONVERSATION_LOCK_WAIT_SECONDS", 6)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return DEFAULT_LOCK_WAIT_TIMEOUT_SECONDS


def _lock_ttl_seconds() -> int:
    raw = getattr(settings, "QUALIFICATION_CONVERSATION_LOCK_TTL_SECONDS", 60)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return DEFAULT_LOCK_TTL_SECONDS


def get_conversation_lock_backend() -> ConversationLockBackend:
    global _backend
    if _backend is not None:
        return _backend

    redis_url = getattr(settings, "QUALIFICATION_REDIS_URL", "")
    if redis_url:
        _backend = RedisConversationLockBackend(redis_url=redis_url)
        return _backend

    if connection.vendor == "postgresql":
        _backend = PostgresAdvisoryConversationLockBackend()
        return _backend

    _backend = InMemoryConversationLockBackend()
    return _backend


def reset_conversation_lock_backend_for_tests() -> None:
    """Reset lock backend singleton. Intended for tests only."""
    global _backend
    if isinstance(_backend, InMemoryConversationLockBackend):
        _backend.clear_locks_for_tests()
    _backend = None


def acquire_conversation_turn_lock(lock_key: str) -> ConversationTurnLockHandle:
    """Acquire an exclusive per-user qualification turn lock."""
    backend = get_conversation_lock_backend()
    result = backend.acquire(
        lock_key,
        wait_timeout_seconds=_lock_wait_timeout_seconds(),
        lock_ttl_seconds=_lock_ttl_seconds(),
    )
    return ConversationTurnLockHandle(
        lock_key=lock_key,
        token=result.token,
        acquired=result.acquired,
        timed_out=result.timed_out,
        wait_ms=result.wait_ms,
        _backend=backend,
    )


def build_conversation_lock_timeout_response(
    *,
    whatsapp_number: str,
    input_channel: str,
) -> dict[str, object]:
    """Return a silent HTTP-200 response when a per-user lock cannot be acquired."""
    from apps.qualification.conversation_state import get_accepted_fields
    from apps.qualification.domain.language import get_conversation_language

    return {
        "accepted_fields": get_accepted_fields(whatsapp_number),
        "rejected_fields": {},
        "human_handoff_requested": False,
        "next_field": None,
        "reply_text": "",
        "spoken_text": "",
        "whatsapp_text": "",
        "actions": [],
        "qualification_status": "in_progress",
        "conversation_language": get_conversation_language(whatsapp_number),
        "preferred_phone": None,
        "reply_mode": "voice" if input_channel == "whatsapp_voice_note" else "text",
        "send_booking_link": False,
        "booking_link_sent": False,
        "booking_link": None,
        "tts_enqueued": False,
        "duplicate_detected": False,
        "duplicate_or_locked": True,
        "lock_timeout": True,
        "complete": False,
    }
