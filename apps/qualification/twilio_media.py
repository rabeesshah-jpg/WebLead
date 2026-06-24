"""Secure Twilio media download helpers."""

from __future__ import annotations

import base64
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from django.conf import settings

TWILIO_MEDIA_URL_PREFIX = "https://api.twilio.com/"


class TwilioMediaConfigurationError(Exception):
    """Raised when Twilio media download settings are incomplete."""


class TwilioMediaRequestError(Exception):
    """Raised when Twilio media download fails."""


class TwilioMediaUnauthorizedError(TwilioMediaRequestError):
    """Raised when Twilio media download authentication fails."""


class TwilioMediaTimeoutError(TwilioMediaRequestError):
    """Raised when Twilio media download times out."""


def _validate_configuration() -> None:
    if not settings.TWILIO_ACCOUNT_SID:
        raise TwilioMediaConfigurationError("Twilio account SID is not configured")
    if not settings.TWILIO_AUTH_TOKEN:
        raise TwilioMediaConfigurationError("Twilio auth token is not configured")


def _validate_media_url(media_url: str) -> None:
    parsed = urlparse(media_url)
    if parsed.scheme != "https" or not media_url.startswith(TWILIO_MEDIA_URL_PREFIX):
        raise TwilioMediaRequestError("Invalid Twilio media URL")


def _read_limited_response(response: object, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise TwilioMediaRequestError("Twilio media download exceeded size limit")
        chunks.append(chunk)
    return b"".join(chunks)


def download_twilio_media(media_url: str) -> bytes:
    """Download protected Twilio media using account credentials."""
    _validate_configuration()
    _validate_media_url(media_url)

    request = urllib.request.Request(media_url, method="GET")
    credentials = base64.b64encode(
        f"{settings.TWILIO_ACCOUNT_SID}:{settings.TWILIO_AUTH_TOKEN}".encode("utf-8"),
    ).decode("ascii")
    request.add_header("Authorization", f"Basic {credentials}")

    started = time.perf_counter()
    try:
        with urllib.request.urlopen(
            request,
            timeout=settings.TWILIO_MEDIA_DOWNLOAD_TIMEOUT_SECONDS,
        ) as response:
            return _read_limited_response(
                response,
                max_bytes=settings.TWILIO_MEDIA_MAX_BYTES,
            )
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise TwilioMediaUnauthorizedError("Twilio media download unauthorized") from exc
        raise TwilioMediaRequestError("Twilio media download failed") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError | socket.timeout):
            raise TwilioMediaTimeoutError("Twilio media download timed out") from exc
        raise TwilioMediaRequestError("Twilio media download failed") from exc
    finally:
        download_twilio_media.last_elapsed_ms = int((time.perf_counter() - started) * 1000)  # type: ignore[attr-defined]


download_twilio_media.last_elapsed_ms = 0
