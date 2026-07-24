"""Compatibility shim: WhatsApp media download now uses WAHA."""

from apps.whatsapp.media import (
    DEFAULT_AUDIO_CONTENT_TYPE,
    WahaMediaConfigurationError as TwilioMediaConfigurationError,
    WahaMediaRequestError as TwilioMediaRequestError,
    WahaMediaTimeoutError as TwilioMediaTimeoutError,
    WahaMediaUnauthorizedError as TwilioMediaUnauthorizedError,
    download_media as download_twilio_media,
)

__all__ = [
    "DEFAULT_AUDIO_CONTENT_TYPE",
    "TwilioMediaConfigurationError",
    "TwilioMediaRequestError",
    "TwilioMediaTimeoutError",
    "TwilioMediaUnauthorizedError",
    "download_twilio_media",
]
