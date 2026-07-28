"""WhatsApp media download helpers (Twilio voice notes and attachments)."""

from __future__ import annotations

import time

from apps.qualification.twilio_media import (
    TwilioMediaRequestError,
    TwilioMediaTimeoutError,
    TwilioMediaUnauthorizedError,
    download_twilio_media,
)

DEFAULT_AUDIO_CONTENT_TYPE = "audio/ogg"


class WhatsAppMediaRequestError(Exception):
    """Raised when WhatsApp media download fails."""


class WhatsAppMediaUnauthorizedError(WhatsAppMediaRequestError):
    """Raised when WhatsApp media authentication fails."""


class WhatsAppMediaTimeoutError(WhatsAppMediaRequestError):
    """Raised when WhatsApp media download times out."""


def download_media(media_url: str) -> tuple[bytes, str]:
    """
    Download protected Twilio WhatsApp media.

    Compatibility function used by qualification transcription flow.

    Returns:
        tuple[bytes, str]: media bytes and content type.
    """
    started = time.perf_counter()

    try:
        audio_bytes, content_type = download_twilio_media(media_url)

        return (
            audio_bytes,
            content_type or DEFAULT_AUDIO_CONTENT_TYPE,
        )

    except TwilioMediaUnauthorizedError as exc:
        raise WhatsAppMediaUnauthorizedError(
            "WhatsApp media download unauthorized",
        ) from exc

    except TwilioMediaTimeoutError as exc:
        raise WhatsAppMediaTimeoutError(
            "WhatsApp media download timed out",
        ) from exc

    except TwilioMediaRequestError as exc:
        raise WhatsAppMediaRequestError(
            "WhatsApp media download failed",
        ) from exc

    finally:
        download_media.last_elapsed_ms = int(
            (time.perf_counter() - started) * 1000,
        )

