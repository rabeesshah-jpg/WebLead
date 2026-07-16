"""Deepgram pre-recorded speech-to-text client."""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from django.conf import settings

from apps.qualification.domain.deepgram_config import (
    DeepgramTranscriptionConfig,
    get_deepgram_transcription_config,
)

MIN_AUDIO_BYTES = 128


class DeepgramConfigurationError(Exception):
    """Raised when Deepgram client settings are incomplete."""


class DeepgramRequestError(Exception):
    """Raised when the Deepgram HTTP request fails."""


class DeepgramResponseError(Exception):
    """Raised when the Deepgram response cannot be used."""


class DeepgramTimeoutError(DeepgramRequestError):
    """Raised when the Deepgram HTTP request times out."""


def _validate_api_key() -> None:
    if not settings.DEEPGRAM_API_KEY:
        raise DeepgramConfigurationError("Deepgram API key is not configured")


def validate_audio_payload(audio_bytes: bytes, *, content_type: str | None) -> None:
    """Reject empty or clearly invalid audio before calling Deepgram."""
    if not audio_bytes:
        raise DeepgramRequestError("Audio payload is empty")
    if len(audio_bytes) < MIN_AUDIO_BYTES:
        raise DeepgramRequestError("Audio payload is too small")
    normalized_type = normalize_audio_content_type(content_type)
    if not normalized_type.startswith("audio/"):
        raise DeepgramRequestError("Invalid audio content type")


def normalize_audio_content_type(content_type: str | None) -> str:
    """Normalize an audio MIME type for direct Deepgram byte uploads."""
    if isinstance(content_type, str):
        normalized = content_type.split(";", 1)[0].strip().lower()
        if normalized.startswith("audio/"):
            return normalized
    return "audio/ogg"


def _build_listen_url(transcription_config: DeepgramTranscriptionConfig) -> str:
    query = urllib.parse.urlencode(
        {
            "model": transcription_config.model,
            "language": transcription_config.language,
            "punctuate": "true" if transcription_config.punctuate else "false",
            "smart_format": "true" if transcription_config.smart_format else "false",
        },
    )
    return f"{settings.DEEPGRAM_BASE_URL}/v1/listen?{query}"


def _extract_transcript(response_payload: dict[str, Any]) -> str:
    try:
        results = response_payload["results"]
        channels = results["channels"]
        alternatives = channels[0]["alternatives"]
        transcript = alternatives[0]["transcript"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DeepgramResponseError("Deepgram response is missing transcript") from exc

    if not isinstance(transcript, str) or not transcript.strip():
        raise DeepgramResponseError("Deepgram transcript is empty")

    return transcript.strip()


def _extract_audio_duration_seconds(response_payload: dict[str, Any]) -> float | None:
    metadata = response_payload.get("metadata")
    if not isinstance(metadata, dict):
        return None
    duration = metadata.get("duration")
    if isinstance(duration, int | float):
        return float(duration)
    return None


def _transcribe_once(
    audio_bytes: bytes,
    *,
    content_type: str,
    transcription_config: DeepgramTranscriptionConfig,
) -> str:
    normalized_content_type = normalize_audio_content_type(content_type)
    request = urllib.request.Request(
        _build_listen_url(transcription_config),
        data=audio_bytes,
        method="POST",
        headers={
            "Authorization": f"Token {settings.DEEPGRAM_API_KEY}",
            "Content-Type": normalized_content_type,
            "Connection": "keep-alive",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=transcription_config.timeout_seconds,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise DeepgramRequestError("Deepgram request failed") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError | socket.timeout):
            raise DeepgramTimeoutError("Deepgram request timed out") from exc
        raise DeepgramRequestError("Deepgram request failed") from exc
    except json.JSONDecodeError as exc:
        raise DeepgramResponseError("Deepgram response is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise DeepgramResponseError("Deepgram response is not a JSON object")

    transcribe_audio.last_audio_duration_seconds = _extract_audio_duration_seconds(payload)  # type: ignore[attr-defined]
    transcribe_audio.last_transcription_config = transcription_config  # type: ignore[attr-defined]
    return _extract_transcript(payload)


def transcribe_audio(
    audio_bytes: bytes,
    *,
    content_type: str,
    transcription_config: DeepgramTranscriptionConfig | None = None,
    conversation_language: str | None = None,
) -> str:
    """Transcribe pre-recorded audio bytes with Deepgram."""
    _validate_api_key()
    validate_audio_payload(audio_bytes, content_type=content_type)

    if transcription_config is None:
        language = conversation_language or "en"
        transcription_config = get_deepgram_transcription_config(
            conversation_language=language,
        )

    started = time.perf_counter()
    try:
        try:
            return _transcribe_once(
                audio_bytes,
                content_type=content_type,
                transcription_config=transcription_config,
            )
        except DeepgramTimeoutError:
            return _transcribe_once(
                audio_bytes,
                content_type=content_type,
                transcription_config=transcription_config,
            )
    finally:
        transcribe_audio.last_elapsed_ms = int((time.perf_counter() - started) * 1000)  # type: ignore[attr-defined]


transcribe_audio.last_elapsed_ms = 0
transcribe_audio.last_audio_duration_seconds = None
transcribe_audio.last_transcription_config = None

# Alias documenting the direct-bytes Deepgram upload path.
transcribe_with_deepgram = transcribe_audio
