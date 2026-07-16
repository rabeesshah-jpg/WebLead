"""Non-invasive latency profiling for qualification flows."""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

logger = logging.getLogger("apps.qualification")

_EXTERNAL_API_STEPS = frozenset(
    {
        "twilio_media_download",
        "deepgram_transcription",
        "openrouter_call",
    },
)
_SUMMARY_STEPS = frozenset(
    {
        "twilio_media_download",
        "deepgram_transcription",
        "openrouter_call",
        "tts_generation",
    },
)
_external_api_total_ms: ContextVar[int] = ContextVar("external_api_total_ms", default=0)
_step_durations_ms: ContextVar[dict[str, int]] = ContextVar("step_durations_ms", default={})


def elapsed_ms_since(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def reset_external_api_accumulator() -> None:
    _external_api_total_ms.set(0)


def reset_step_duration_tracker() -> None:
    _step_durations_ms.set({})


def get_tracked_step_durations() -> dict[str, int]:
    return dict(_step_durations_ms.get())


def _accumulate_external_api_duration(step: str, duration_ms: int) -> None:
    if step in _EXTERNAL_API_STEPS:
        _external_api_total_ms.set(_external_api_total_ms.get() + duration_ms)


def _track_summary_step_duration(step: str, duration_ms: int) -> None:
    if step in _SUMMARY_STEPS:
        durations = dict(_step_durations_ms.get())
        durations[step] = duration_ms
        _step_durations_ms.set(durations)


def log_external_api_total(*, message_sid: str | None = None) -> None:
    """Emit consolidated external API latency for the current request context."""
    total_ms = _external_api_total_ms.get()
    log_latency_step("external_api_total", total_ms, message_sid=message_sid)
    reset_external_api_accumulator()


def log_latency_step(
    step: str,
    duration_ms: int,
    *,
    message_sid: str | None = None,
    **extra: Any,
) -> None:
    """Emit one structured latency log line without secrets or payloads."""
    _accumulate_external_api_duration(step, duration_ms)
    _track_summary_step_duration(step, duration_ms)
    payload: dict[str, Any] = {"step": step, "duration_ms": duration_ms}
    if message_sid:
        payload["message_sid"] = message_sid
    for key, value in extra.items():
        if value is not None:
            payload[key] = value
    logger.info(json.dumps(payload, separators=(",", ":")))


@contextmanager
def profile_step(
    step: str,
    *,
    message_sid: str | None = None,
    **extra: Any,
) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        log_latency_step(
            step,
            elapsed_ms_since(started),
            message_sid=message_sid,
            **extra,
        )


def store_pending_voice_turn_summary(
    message_sid: str,
    *,
    step_durations: dict[str, int],
    extract_api_total_ms: int,
) -> None:
    """Persist extract-phase latency for a later render-audio summary log."""
    from apps.qualification.persistence.cache_backend import (
        default_cache_ttl_seconds,
        get_qualification_cache_backend,
        voice_turn_latency_cache_key,
    )

    payload = json.dumps(
        {
            "step_durations": step_durations,
            "extract_api_total_ms": extract_api_total_ms,
        },
        separators=(",", ":"),
    )
    get_qualification_cache_backend().set(
        voice_turn_latency_cache_key(message_sid),
        payload,
        default_cache_ttl_seconds(),
    )


def log_voice_turn_latency_summary(
    message_sid: str,
    *,
    tts_generation_ms: int,
    render_api_total_ms: int,
) -> None:
    """Emit the end-to-end voice turn latency summary when render-audio completes."""
    from apps.qualification.persistence.cache_backend import (
        get_qualification_cache_backend,
        voice_turn_latency_cache_key,
    )

    cache = get_qualification_cache_backend()
    cache_key = voice_turn_latency_cache_key(message_sid)
    raw_payload = cache.get(cache_key)
    cache.delete(cache_key)

    step_durations: dict[str, int] = {}
    extract_api_total_ms = 0
    if isinstance(raw_payload, str):
        try:
            stored = json.loads(raw_payload)
        except json.JSONDecodeError:
            stored = {}
        if isinstance(stored, dict):
            durations = stored.get("step_durations")
            if isinstance(durations, dict):
                step_durations = {
                    key: int(value)
                    for key, value in durations.items()
                    if key in _SUMMARY_STEPS and isinstance(value, int | float)
                }
            extract_total = stored.get("extract_api_total_ms")
            if isinstance(extract_total, int | float):
                extract_api_total_ms = int(extract_total)

    step_durations["tts_generation"] = tts_generation_ms
    summary = {
        "step": "voice_turn_latency_summary",
        "message_sid": message_sid,
        "twilio_media_download_ms": step_durations.get("twilio_media_download"),
        "deepgram_transcription_ms": step_durations.get("deepgram_transcription"),
        "openrouter_call_ms": step_durations.get("openrouter_call"),
        "tts_generation_ms": step_durations.get("tts_generation"),
        "api_total_ms": extract_api_total_ms + render_api_total_ms,
    }
    logger.info(json.dumps(summary, separators=(",", ":")))
