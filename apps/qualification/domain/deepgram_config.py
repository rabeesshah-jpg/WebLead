"""Language-aware Deepgram transcription configuration."""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from apps.qualification.domain.language_selection import (
    LANGUAGE_ARABIC,
    LANGUAGE_ENGLISH,
    normalize_conversation_language,
)

DEFAULT_DEEPGRAM_MODEL = "nova-2"
DEFAULT_DEEPGRAM_LANGUAGE = "en"
DEFAULT_DEEPGRAM_ARABIC_MODEL = "nova-3"
DEFAULT_DEEPGRAM_ARABIC_LANGUAGE = "ar"


def _configuration_error(message: str) -> Exception:
    from apps.qualification.deepgram_client import DeepgramConfigurationError

    return DeepgramConfigurationError(message)


@dataclass(frozen=True)
class DeepgramTranscriptionConfig:
    model: str
    language: str
    punctuate: bool
    smart_format: bool
    timeout_seconds: int


def _non_empty_setting(value: str | None) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def get_deepgram_transcription_config(
    *,
    conversation_language: str,
) -> DeepgramTranscriptionConfig:
    """Resolve Deepgram model and language from persisted conversation language."""
    normalized_language = normalize_conversation_language(conversation_language)
    timeout_seconds = settings.DEEPGRAM_TIMEOUT_SECONDS

    if normalized_language == LANGUAGE_ENGLISH:
        model = (
            _non_empty_setting(settings.DEEPGRAM_ENGLISH_MODEL)
            or _non_empty_setting(settings.DEEPGRAM_MODEL)
            or DEFAULT_DEEPGRAM_MODEL
        )
        language = (
            _non_empty_setting(settings.DEEPGRAM_ENGLISH_LANGUAGE)
            or _non_empty_setting(settings.DEEPGRAM_LANGUAGE)
            or DEFAULT_DEEPGRAM_LANGUAGE
        )
        return DeepgramTranscriptionConfig(
            model=model,
            language=language,
            punctuate=False,
            smart_format=False,
            timeout_seconds=timeout_seconds,
        )

    if normalized_language == LANGUAGE_ARABIC:
        model = _non_empty_setting(settings.DEEPGRAM_ARABIC_MODEL)
        language = _non_empty_setting(settings.DEEPGRAM_ARABIC_LANGUAGE)
        if not model or not language:
            raise _configuration_error(
                "Arabic Deepgram transcription model and language are not configured",
            )
        if language in {"en", "multi"}:
            raise _configuration_error(
                "Arabic Deepgram transcription language must not be English or multi",
            )
        return DeepgramTranscriptionConfig(
            model=model,
            language=language,
            punctuate=False,
            smart_format=False,
            timeout_seconds=timeout_seconds,
        )

    raise _configuration_error(
        f"Unsupported conversation language for Deepgram transcription: {conversation_language}",
    )
