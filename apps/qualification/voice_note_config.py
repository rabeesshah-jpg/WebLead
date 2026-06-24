"""Configuration validation for WhatsApp voice-note processing."""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

DEFAULT_DEEPGRAM_BASE_URL = "https://api.deepgram.com"
DEFAULT_DEEPGRAM_MODEL = "nova-2"


class VoiceNoteConfigurationError(Exception):
    """Raised when required voice-note dependencies are not configured."""

    def __init__(self, *, log_event: str, message: str) -> None:
        super().__init__(message)
        self.log_event = log_event


@dataclass(frozen=True)
class VoiceNoteConfigReport:
    twilio_media_credentials: str
    deepgram_api_key: str
    deepgram_model: str
    deepgram_base_url: str
    ready: bool


def _twilio_media_credentials_configured() -> bool:
    return bool(settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN)


def _deepgram_api_key_configured() -> bool:
    return bool(settings.DEEPGRAM_API_KEY)


def get_voice_note_config_report() -> VoiceNoteConfigReport:
    """Return a safe configuration summary for voice-note processing."""
    deepgram_model = settings.DEEPGRAM_MODEL or DEFAULT_DEEPGRAM_MODEL
    deepgram_base_url = settings.DEEPGRAM_BASE_URL or DEFAULT_DEEPGRAM_BASE_URL
    twilio_configured = _twilio_media_credentials_configured()
    deepgram_configured = _deepgram_api_key_configured()

    return VoiceNoteConfigReport(
        twilio_media_credentials="configured" if twilio_configured else "missing",
        deepgram_api_key="configured" if deepgram_configured else "missing",
        deepgram_model=(
            f"configured ({deepgram_model})"
            if settings.DEEPGRAM_MODEL
            else f"default used ({DEFAULT_DEEPGRAM_MODEL})"
        ),
        deepgram_base_url=(
            f"configured ({deepgram_base_url})"
            if settings.DEEPGRAM_BASE_URL
            else f"default used ({DEFAULT_DEEPGRAM_BASE_URL})"
        ),
        ready=twilio_configured and deepgram_configured,
    )


def is_voice_note_ready() -> bool:
    return get_voice_note_config_report().ready


def validate_voice_note_dependencies() -> None:
    """Raise when Twilio media download or Deepgram credentials are missing."""
    if not _twilio_media_credentials_configured():
        raise VoiceNoteConfigurationError(
            log_event="qualification_voice_missing_twilio_credentials",
            message="Twilio media download credentials are not configured",
        )
    if not _deepgram_api_key_configured():
        raise VoiceNoteConfigurationError(
            log_event="qualification_voice_missing_deepgram_credentials",
            message="Deepgram API key is not configured",
        )
