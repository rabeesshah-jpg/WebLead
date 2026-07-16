"""Language-aware Supertonic TTS voice configuration."""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from apps.qualification.domain.language_selection import (
    LANGUAGE_ARABIC,
    LANGUAGE_ENGLISH,
)

DEFAULT_SUPERTONIC_ENGLISH_VOICE = "F1"

FALLBACK_REASON_ARABIC_TTS_UNAVAILABLE = "arabic_tts_unavailable"
FALLBACK_REASON_ENGLISH_TTS_UNAVAILABLE = "english_tts_unavailable"
FALLBACK_REASON_UNSUPPORTED_LANGUAGE = "unsupported_language"


@dataclass(frozen=True)
class SupertonicVoiceConfig:
    language: str
    voice: str
    enabled: bool


def _non_empty_setting(value: str | None) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def get_supertonic_voice_config(
    *,
    conversation_language: str,
) -> SupertonicVoiceConfig:
    """Resolve Supertonic voice settings from persisted conversation language."""
    if conversation_language == LANGUAGE_ENGLISH:
        voice = (
            _non_empty_setting(settings.SUPERTONIC_ENGLISH_VOICE)
            or DEFAULT_SUPERTONIC_ENGLISH_VOICE
        )
        return SupertonicVoiceConfig(
            language=LANGUAGE_ENGLISH,
            voice=voice,
            enabled=True,
        )

    if conversation_language == LANGUAGE_ARABIC:
        voice = _non_empty_setting(settings.SUPERTONIC_ARABIC_VOICE) or ""
        enabled = bool(settings.SUPERTONIC_ARABIC_ENABLED and voice)
        return SupertonicVoiceConfig(
            language=LANGUAGE_ARABIC,
            voice=voice,
            enabled=enabled,
        )

    return SupertonicVoiceConfig(
        language=conversation_language,
        voice="",
        enabled=False,
    )
