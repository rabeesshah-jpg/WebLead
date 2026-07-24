"""WAHA media download helpers (voice notes and attachments)."""

from __future__ import annotations

import time
from urllib.parse import urlparse

from django.conf import settings

from apps.whatsapp.config import WahaConfigurationError, get_waha_api_key, get_waha_base_url
from apps.whatsapp.waha_client import WahaApiError, download_media_bytes

DEFAULT_AUDIO_CONTENT_TYPE = "audio/ogg"


class WahaMediaConfigurationError(WahaConfigurationError):
    """Raised when WAHA media download settings are incomplete."""


class WahaMediaRequestError(WahaApiError):
    """Raised when WAHA media download fails."""


class WahaMediaUnauthorizedError(WahaMediaRequestError):
    """Raised when WAHA media download authentication fails."""


class WahaMediaTimeoutError(WahaMediaRequestError):
    """Raised when WAHA media download times out."""


def _validate_configuration() -> None:
    if not get_waha_api_key():
        raise WahaMediaConfigurationError("WAHA_API_KEY is not configured")


def _validate_media_url(media_url: str) -> None:
    parsed = urlparse(media_url)
    if parsed.scheme not in {"http", "https"}:
        raise WahaMediaRequestError("Invalid WAHA media URL")
    base = get_waha_base_url()
    if base:
        if media_url.startswith(base) or media_url.startswith(
            base.replace("https://", "http://"),
        ):
            return
        if "/api/files/" in parsed.path:
            return
        raise WahaMediaRequestError("Invalid WAHA media URL")
    if "/api/files/" not in parsed.path:
        raise WahaMediaRequestError("Invalid WAHA media URL")


def download_media(media_url: str) -> tuple[bytes, str]:
    """
    Download protected WAHA media and return raw bytes with content type.

    Compatibility alias used by qualification transcription.
    """
    _validate_configuration()
    _validate_media_url(media_url)
    started = time.perf_counter()
    try:
        audio_bytes, content_type = download_media_bytes(
            media_url,
            timeout_seconds=float(
                getattr(settings, "WAHA_MEDIA_DOWNLOAD_TIMEOUT_SECONDS", 30) or 30
            ),
            max_bytes=int(getattr(settings, "WAHA_MEDIA_MAX_BYTES", 10485760) or 10485760),
        )
        return audio_bytes, content_type or DEFAULT_AUDIO_CONTENT_TYPE
    except WahaApiError as exc:
        status = getattr(exc, "status_code", None)
        message = str(exc).lower()
        if status in {401, 403} or "unauthorized" in message:
            raise WahaMediaUnauthorizedError("WhatsApp media download unauthorized") from exc
        if "timed out" in message or "timeout" in message:
            raise WahaMediaTimeoutError("WhatsApp media download timed out") from exc
        raise WahaMediaRequestError("WhatsApp media download failed") from exc
    finally:
        download_media.last_elapsed_ms = int((time.perf_counter() - started) * 1000)  # type: ignore[attr-defined]


download_media.last_elapsed_ms = 0
