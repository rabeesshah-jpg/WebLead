"""Persistence backend selection and shared protocol."""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Protocol

from django.conf import settings

from apps.qualification.domain.latency_profiling import elapsed_ms_since, log_latency_step

PROCESSING_SENTINEL = "__processing__"
DEFAULT_IDEMPOTENCY_POLL_ATTEMPTS = 50
DEFAULT_IDEMPOTENCY_POLL_INTERVAL_SECONDS = 0.1


class PersistenceBackend(Protocol):
    def get_conversation_fields(self, whatsapp_number: str) -> dict[str, Any]:
        ...

    def save_conversation_fields(self, whatsapp_number: str, accepted_fields: dict[str, Any]) -> None:
        ...

    def get_conversation_history(self, whatsapp_number: str) -> list[dict[str, str]]:
        ...

    def append_conversation_turn(
        self,
        whatsapp_number: str,
        *,
        user_message: str,
        assistant_reply: str,
    ) -> None:
        ...

    def clear_conversations(self) -> None:
        ...

    def clear_conversation_for_customer(self, whatsapp_number: str) -> None:
        ...

    def get_turn_response(self, message_sid: str) -> dict[str, Any] | None:
        ...

    def begin_turn(self, message_sid: str) -> dict[str, Any] | None:
        """
        Return a cached turn response when already complete.

        Return None when this caller should process the turn (exclusive slot acquired).
        """

    def set_turn_response(self, message_sid: str, response: dict[str, Any]) -> None:
        ...

    def clear_message_sid_cache(self) -> None:
        ...


class InMemoryPersistenceBackend:
    """Process-local persistence for development and tests."""

    def __init__(self) -> None:
        self._conversations: dict[str, dict[str, Any]] = {}
        self._conversation_history: dict[str, list[dict[str, str]]] = {}
        self._turn_responses: dict[str, dict[str, Any]] = {}
        self._processing_sids: set[str] = set()
        self._lock = threading.Lock()

    def get_conversation_fields(self, whatsapp_number: str) -> dict[str, Any]:
        started = time.perf_counter()
        with self._lock:
            result = dict(self._conversations.get(whatsapp_number, {}))
        log_latency_step(
            "persistence_conversation_get",
            elapsed_ms_since(started),
            cache_hit=bool(result),
            backend="memory",
        )
        return result

    def save_conversation_fields(self, whatsapp_number: str, accepted_fields: dict[str, Any]) -> None:
        started = time.perf_counter()
        with self._lock:
            self._conversations[whatsapp_number] = dict(accepted_fields)
        log_latency_step(
            "persistence_conversation_set",
            elapsed_ms_since(started),
            backend="memory",
        )

    def clear_conversations(self) -> None:
        with self._lock:
            self._conversations.clear()
            self._conversation_history.clear()

    def clear_conversation_for_customer(self, whatsapp_number: str) -> None:
        started = time.perf_counter()
        with self._lock:
            self._conversations.pop(whatsapp_number, None)
            self._conversation_history.pop(whatsapp_number, None)
        log_latency_step(
            "persistence_conversation_clear_customer",
            elapsed_ms_since(started),
            backend="memory",
        )

    def get_conversation_history(self, whatsapp_number: str) -> list[dict[str, str]]:
        with self._lock:
            history = self._conversation_history.get(whatsapp_number, [])
            return [dict(item) for item in history]

    def append_conversation_turn(
        self,
        whatsapp_number: str,
        *,
        user_message: str,
        assistant_reply: str,
    ) -> None:
        with self._lock:
            history = list(self._conversation_history.get(whatsapp_number, []))
            if user_message:
                history.append({"role": "user", "content": user_message})
            if assistant_reply:
                history.append({"role": "assistant", "content": assistant_reply})
            self._conversation_history[whatsapp_number] = history

    def get_turn_response(self, message_sid: str) -> dict[str, Any] | None:
        started = time.perf_counter()
        with self._lock:
            cached = self._turn_responses.get(message_sid)
            result = dict(cached) if cached is not None else None
        log_latency_step(
            "persistence_idempotency_get",
            elapsed_ms_since(started),
            message_sid=message_sid,
            cache_hit=result is not None,
            backend="memory",
        )
        return result

    def begin_turn(self, message_sid: str) -> dict[str, Any] | None:
        started = time.perf_counter()
        with self._lock:
            cached = self._turn_responses.get(message_sid)
            if cached is not None:
                result = dict(cached)
                log_latency_step(
                    "persistence_idempotency_begin_turn",
                    elapsed_ms_since(started),
                    message_sid=message_sid,
                    cache_hit=True,
                    backend="memory",
                )
                return result
            acquired = message_sid not in self._processing_sids
            if acquired:
                self._processing_sids.add(message_sid)
                log_latency_step(
                    "persistence_idempotency_begin_turn",
                    elapsed_ms_since(started),
                    message_sid=message_sid,
                    cache_hit=False,
                    backend="memory",
                )
                return None

        for _ in range(DEFAULT_IDEMPOTENCY_POLL_ATTEMPTS):
            time.sleep(DEFAULT_IDEMPOTENCY_POLL_INTERVAL_SECONDS)
            with self._lock:
                cached = self._turn_responses.get(message_sid)
                if cached is not None:
                    result = dict(cached)
                    log_latency_step(
                        "persistence_idempotency_begin_turn",
                        elapsed_ms_since(started),
                        message_sid=message_sid,
                        cache_hit=True,
                        backend="memory",
                    )
                    return result
        log_latency_step(
            "persistence_idempotency_begin_turn",
            elapsed_ms_since(started),
            message_sid=message_sid,
            cache_hit=False,
            backend="memory",
        )
        return None

    def set_turn_response(self, message_sid: str, response: dict[str, Any]) -> None:
        started = time.perf_counter()
        with self._lock:
            self._turn_responses[message_sid] = dict(response)
            self._processing_sids.discard(message_sid)
        log_latency_step(
            "persistence_idempotency_set",
            elapsed_ms_since(started),
            message_sid=message_sid,
            backend="memory",
        )

    def clear_message_sid_cache(self) -> None:
        with self._lock:
            self._turn_responses.clear()
            self._processing_sids.clear()


class RedisPersistenceBackend:
    """Redis-backed persistence shared across workers."""

    def __init__(
        self,
        *,
        redis_url: str,
        conversation_ttl_seconds: int,
        idempotency_ttl_seconds: int,
        processing_ttl_seconds: int,
    ) -> None:
        import redis

        self._client = redis.Redis.from_url(redis_url, decode_responses=True)
        self._conversation_ttl_seconds = conversation_ttl_seconds
        self._idempotency_ttl_seconds = idempotency_ttl_seconds
        self._processing_ttl_seconds = processing_ttl_seconds

    @staticmethod
    def _conversation_key(whatsapp_number: str) -> str:
        return f"qualification:conversation:{whatsapp_number}"

    @staticmethod
    def _idempotency_key(message_sid: str) -> str:
        return f"qualification:idempotency:{message_sid}"

    @staticmethod
    def _conversation_history_key(whatsapp_number: str) -> str:
        return f"qualification:history:{whatsapp_number}"

    def get_conversation_fields(self, whatsapp_number: str) -> dict[str, Any]:
        started = time.perf_counter()
        raw = self._client.get(self._conversation_key(whatsapp_number))
        if not raw:
            log_latency_step(
                "persistence_conversation_get",
                elapsed_ms_since(started),
                cache_hit=False,
                backend="redis",
            )
            return {}
        payload = json.loads(raw)
        result = dict(payload) if isinstance(payload, dict) else {}
        log_latency_step(
            "persistence_conversation_get",
            elapsed_ms_since(started),
            cache_hit=bool(result),
            backend="redis",
        )
        return result

    def save_conversation_fields(self, whatsapp_number: str, accepted_fields: dict[str, Any]) -> None:
        started = time.perf_counter()
        self._client.set(
            self._conversation_key(whatsapp_number),
            json.dumps(dict(accepted_fields), separators=(",", ":")),
            ex=self._conversation_ttl_seconds,
        )
        log_latency_step(
            "persistence_conversation_set",
            elapsed_ms_since(started),
            backend="redis",
        )

    def clear_conversations(self) -> None:
        for key in self._client.scan_iter(match="qualification:conversation:*"):
            self._client.delete(key)
        for key in self._client.scan_iter(match="qualification:history:*"):
            self._client.delete(key)

    def clear_conversation_for_customer(self, whatsapp_number: str) -> None:
        started = time.perf_counter()
        self._client.delete(self._conversation_key(whatsapp_number))
        self._client.delete(self._conversation_history_key(whatsapp_number))
        log_latency_step(
            "persistence_conversation_clear_customer",
            elapsed_ms_since(started),
            backend="redis",
        )

    def get_conversation_history(self, whatsapp_number: str) -> list[dict[str, str]]:
        raw = self._client.get(self._conversation_history_key(whatsapp_number))
        if not raw:
            return []
        payload = json.loads(raw)
        if not isinstance(payload, list):
            return []
        return [dict(item) for item in payload if isinstance(item, dict)]

    def append_conversation_turn(
        self,
        whatsapp_number: str,
        *,
        user_message: str,
        assistant_reply: str,
    ) -> None:
        history = self.get_conversation_history(whatsapp_number)
        if user_message:
            history.append({"role": "user", "content": user_message})
        if assistant_reply:
            history.append({"role": "assistant", "content": assistant_reply})
        self._client.set(
            self._conversation_history_key(whatsapp_number),
            json.dumps(history, separators=(",", ":")),
            ex=self._conversation_ttl_seconds,
        )

    def get_turn_response(self, message_sid: str) -> dict[str, Any] | None:
        started = time.perf_counter()
        raw = self._client.get(self._idempotency_key(message_sid))
        if not raw or raw == PROCESSING_SENTINEL:
            log_latency_step(
                "persistence_idempotency_get",
                elapsed_ms_since(started),
                message_sid=message_sid,
                cache_hit=False,
                backend="redis",
            )
            return None
        payload = json.loads(raw)
        result = dict(payload) if isinstance(payload, dict) else None
        log_latency_step(
            "persistence_idempotency_get",
            elapsed_ms_since(started),
            message_sid=message_sid,
            cache_hit=result is not None,
            backend="redis",
        )
        return result

    def begin_turn(self, message_sid: str) -> dict[str, Any] | None:
        begin_started = time.perf_counter()
        key = self._idempotency_key(message_sid)
        cached = self.get_turn_response(message_sid)
        if cached is not None:
            log_latency_step(
                "persistence_idempotency_begin_turn",
                elapsed_ms_since(begin_started),
                message_sid=message_sid,
                cache_hit=True,
                backend="redis",
            )
            return cached

        set_started = time.perf_counter()
        acquired = self._client.set(
            key,
            PROCESSING_SENTINEL,
            nx=True,
            ex=self._processing_ttl_seconds,
        )
        log_latency_step(
            "persistence_idempotency_begin_turn_set",
            elapsed_ms_since(set_started),
            message_sid=message_sid,
            cache_hit=False,
            backend="redis",
        )
        if acquired:
            log_latency_step(
                "persistence_idempotency_begin_turn",
                elapsed_ms_since(begin_started),
                message_sid=message_sid,
                cache_hit=False,
                backend="redis",
            )
            return None

        wait_attempts = max(
            DEFAULT_IDEMPOTENCY_POLL_ATTEMPTS,
            int(self._processing_ttl_seconds / DEFAULT_IDEMPOTENCY_POLL_INTERVAL_SECONDS),
        )
        for _ in range(wait_attempts):
            cached = self.get_turn_response(message_sid)
            if cached is not None:
                log_latency_step(
                    "persistence_idempotency_begin_turn",
                    elapsed_ms_since(begin_started),
                    message_sid=message_sid,
                    cache_hit=True,
                    backend="redis",
                )
                return cached
            time.sleep(DEFAULT_IDEMPOTENCY_POLL_INTERVAL_SECONDS)

        result = self.get_turn_response(message_sid)
        log_latency_step(
            "persistence_idempotency_begin_turn",
            elapsed_ms_since(begin_started),
            message_sid=message_sid,
            cache_hit=result is not None,
            backend="redis",
        )
        return result

    def set_turn_response(self, message_sid: str, response: dict[str, Any]) -> None:
        started = time.perf_counter()
        self._client.set(
            self._idempotency_key(message_sid),
            json.dumps(dict(response), separators=(",", ":")),
            ex=self._idempotency_ttl_seconds,
        )
        log_latency_step(
            "persistence_idempotency_set",
            elapsed_ms_since(started),
            message_sid=message_sid,
            backend="redis",
        )

    def clear_message_sid_cache(self) -> None:
        for key in self._client.scan_iter(match="qualification:idempotency:*"):
            self._client.delete(key)


_backend: PersistenceBackend | None = None


def get_persistence_backend() -> PersistenceBackend:
    global _backend
    if _backend is not None:
        return _backend

    redis_url = getattr(settings, "QUALIFICATION_REDIS_URL", "")
    if redis_url:
        _backend = RedisPersistenceBackend(
            redis_url=redis_url,
            conversation_ttl_seconds=settings.QUALIFICATION_CONVERSATION_TTL_SECONDS,
            idempotency_ttl_seconds=settings.QUALIFICATION_IDEMPOTENCY_TTL_SECONDS,
            processing_ttl_seconds=settings.QUALIFICATION_IDEMPOTENCY_PROCESSING_TTL_SECONDS,
        )
    else:
        _backend = InMemoryPersistenceBackend()
    return _backend


def reset_persistence_backend_for_tests() -> None:
    """Reset backend singleton. Intended for tests only."""
    global _backend
    _backend = None
