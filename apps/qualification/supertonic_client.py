"""Supertonic local HTTP TTS client."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from django.conf import settings

DEFAULT_SUPERTONIC_VOICE = "F1"
DEFAULT_SUPERTONIC_LANG = "en"
DEFAULT_SUPERTONIC_RESPONSE_FORMAT = "wav"


class SupertonicConfigurationError(Exception):
    """Raised when Supertonic client settings are incomplete."""


class SupertonicRequestError(Exception):
    """Raised when the Supertonic HTTP request fails."""


class SupertonicResponseError(Exception):
    """Raised when the Supertonic response cannot be used."""


def build_supertonic_tts_payload(*, text: str, voice: str, lang: str) -> dict[str, Any]:
    """Build the preset-voice Supertonic /v1/tts request body."""
    return {
        "text": text,
        "lang": lang,
        "response_format": DEFAULT_SUPERTONIC_RESPONSE_FORMAT,
        "voice": voice,
    }


def _validate_wav_bytes(audio_bytes: bytes) -> None:
    if len(audio_bytes) < 12:
        raise SupertonicResponseError("Supertonic audio response is too short")
    if audio_bytes[:4] != b"RIFF" or audio_bytes[8:12] != b"WAVE":
        raise SupertonicResponseError("Supertonic audio response is not a WAV file")


def synthesize_wav(*, text: str, voice: str, lang: str) -> bytes:
    """Call local Supertonic and return WAV audio bytes."""
    base_url = settings.SUPERTONIC_BASE_URL.rstrip("/")
    if not base_url:
        raise SupertonicConfigurationError("Supertonic base URL is not configured")

    payload = build_supertonic_tts_payload(text=text, voice=voice, lang=lang)
    request = urllib.request.Request(
        f"{base_url}/v1/tts",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=settings.SUPERTONIC_TTS_TIMEOUT_SECONDS,
        ) as response:
            audio_bytes = response.read()
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        raise SupertonicRequestError("Supertonic request failed") from exc
    except urllib.error.URLError as exc:
        raise SupertonicRequestError("Supertonic request failed") from exc

    if not audio_bytes:
        raise SupertonicResponseError("Supertonic audio response is empty")

    if "json" in content_type.lower() or audio_bytes[:1] == b"{":
        raise SupertonicResponseError("Supertonic returned JSON instead of WAV")

    _validate_wav_bytes(audio_bytes)
    return audio_bytes
