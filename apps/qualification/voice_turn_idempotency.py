"""Idempotency and debounce for LiveKit / voice-agent utterance turns."""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from apps.qualification.api.logging import log_qualification_event
from apps.qualification.persistence.backends import get_persistence_backend

logger = logging.getLogger("apps.qualification")

VOICE_TURN_DEBOUNCE_SECONDS = 2.5
_VOICE_TURN_PREFIX = "voice-turn:"


def normalize_transcript_for_hash(transcript: str) -> str:
    """Normalize transcript text before hashing for duplicate detection."""
    return " ".join(transcript.lower().split()).strip()


def build_transcript_hash(transcript: str) -> str:
    """Return a stable hash for a final STT transcript."""
    normalized = normalize_transcript_for_hash(transcript)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def build_voice_turn_key(
    *,
    call_sid: str,
    utterance_id: str | None,
    transcript: str,
) -> str:
    """
    Build a unique voice-turn cache key.

    Prefer ``utterance_id`` when the STT layer provides one; otherwise hash the
    normalized final transcript under the call sid.
    """
    call_key = call_sid.strip()
    if utterance_id and utterance_id.strip():
        return f"{_VOICE_TURN_PREFIX}{call_key}:utt:{utterance_id.strip()}"
    return f"{_VOICE_TURN_PREFIX}{call_key}:hash:{build_transcript_hash(transcript)}"


def _debounce_key(*, call_sid: str, transcript_hash: str) -> str:
    return f"{_VOICE_TURN_PREFIX}debounce:{call_sid.strip()}:{transcript_hash}"


def begin_voice_utterance_turn(
    *,
    call_sid: str,
    utterance_id: str | None,
    transcript: str,
    debounce_seconds: float = VOICE_TURN_DEBOUNCE_SECONDS,
) -> dict[str, Any] | None:
    """
    Acquire processing for one final voice utterance.

    Returns a cached response when this utterance was already processed, or when
    the same normalized transcript arrives again within the debounce window.
    Returns None when this caller should process the utterance.
    """
    backend = get_persistence_backend()
    transcript_hash = build_transcript_hash(transcript)
    turn_key = build_voice_turn_key(
        call_sid=call_sid,
        utterance_id=utterance_id,
        transcript=transcript,
    )

    cached = backend.get_turn_response(turn_key)
    if cached is not None:
        log_qualification_event(
            "voice_turn_duplicate_detected",
            call_sid=call_sid,
            utterance_id=utterance_id,
            transcript_hash=transcript_hash,
            duplicate_detected=True,
            tts_enqueued=False,
            reason="cached_turn",
        )
        return dict(cached)

    debounce_key = _debounce_key(call_sid=call_sid, transcript_hash=transcript_hash)
    now = time.monotonic()
    last_seen = backend.get_turn_response(debounce_key)
    if isinstance(last_seen, dict):
        last_ts = last_seen.get("seen_at")
        cached_response = last_seen.get("response")
        if (
            isinstance(last_ts, (int, float))
            and isinstance(cached_response, dict)
            and (now - float(last_ts)) < debounce_seconds
        ):
            log_qualification_event(
                "voice_turn_duplicate_detected",
                call_sid=call_sid,
                utterance_id=utterance_id,
                transcript_hash=transcript_hash,
                duplicate_detected=True,
                tts_enqueued=False,
                reason="debounce_window",
            )
            return dict(cached_response)

    claimed = backend.begin_turn(turn_key)
    if claimed is not None:
        log_qualification_event(
            "voice_turn_duplicate_detected",
            call_sid=call_sid,
            utterance_id=utterance_id,
            transcript_hash=transcript_hash,
            duplicate_detected=True,
            tts_enqueued=False,
            reason="concurrent_claim",
        )
        return dict(claimed)

    log_qualification_event(
        "voice_turn_acquired",
        call_sid=call_sid,
        utterance_id=utterance_id,
        transcript_hash=transcript_hash,
        duplicate_detected=False,
        tts_enqueued=False,
    )
    return None


def cache_voice_utterance_response(
    *,
    call_sid: str,
    utterance_id: str | None,
    transcript: str,
    response: dict[str, Any],
) -> None:
    """Cache a processed voice utterance response and refresh the debounce window."""
    backend = get_persistence_backend()
    transcript_hash = build_transcript_hash(transcript)
    turn_key = build_voice_turn_key(
        call_sid=call_sid,
        utterance_id=utterance_id,
        transcript=transcript,
    )
    backend.set_turn_response(turn_key, response)
    backend.set_turn_response(
        _debounce_key(call_sid=call_sid, transcript_hash=transcript_hash),
        {
            "seen_at": time.monotonic(),
            "response": response,
        },
    )
    log_qualification_event(
        "voice_turn_cached",
        call_sid=call_sid,
        utterance_id=utterance_id,
        transcript_hash=transcript_hash,
        duplicate_detected=False,
        tts_enqueued=bool(response.get("spoken_text")),
    )
