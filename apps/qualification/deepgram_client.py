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


class DeepgramConfigurationError(Exception):
    """Raised when Deepgram client settings are incomplete."""


class DeepgramRequestError(Exception):
    """Raised when the Deepgram HTTP request fails."""


class DeepgramResponseError(Exception):
    """Raised when the Deepgram response cannot be used."""


class DeepgramTimeoutError(DeepgramRequestError):
    """Raised when the Deepgram HTTP request times out."""


def _validate_configuration() -> None:
    if not settings.DEEPGRAM_API_KEY:
        raise DeepgramConfigurationError("Deepgram API key is not configured")


def _build_listen_url() -> str:
    query = urllib.parse.urlencode(
        {
            "model": settings.DEEPGRAM_MODEL,
            "smart_format": "true",
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


def transcribe_audio(audio_bytes: bytes, *, content_type: str) -> str:
    """Transcribe pre-recorded audio bytes with Deepgram."""
    _validate_configuration()

    if not audio_bytes:
        raise DeepgramRequestError("Audio payload is empty")

    request = urllib.request.Request(
        _build_listen_url(),
        data=audio_bytes,
        method="POST",
        headers={
            "Authorization": f"Token {settings.DEEPGRAM_API_KEY}",
            "Content-Type": content_type,
        },
    )

    started = time.perf_counter()
    payload: dict[str, Any] | None = None
    try:
        with urllib.request.urlopen(
            request,
            timeout=settings.DEEPGRAM_TIMEOUT_SECONDS,
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
    finally:
        transcribe_audio.last_elapsed_ms = int((time.perf_counter() - started) * 1000)  # type: ignore[attr-defined]

    if not isinstance(payload, dict):
        raise DeepgramResponseError("Deepgram response is not a JSON object")

    return _extract_transcript(payload)


transcribe_audio.last_elapsed_ms = 0
