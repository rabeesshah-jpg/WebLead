"""Tests for language-aware Supertonic voice configuration."""

from __future__ import annotations

import pytest
from django.test import override_settings

from apps.qualification.domain.supertonic_config import (
    FALLBACK_REASON_ARABIC_TTS_UNAVAILABLE,
    SupertonicVoiceConfig,
    get_supertonic_voice_config,
)


@override_settings(SUPERTONIC_ENGLISH_VOICE="F1")
def test_english_conversation_resolves_to_configured_english_voice():
    config = get_supertonic_voice_config(conversation_language="en")

    assert config == SupertonicVoiceConfig(language="en", voice="F1", enabled=True)


@override_settings(SUPERTONIC_ARABIC_ENABLED=False, SUPERTONIC_ARABIC_VOICE="M1")
def test_arabic_conversation_with_disabled_flag_returns_disabled_state():
    config = get_supertonic_voice_config(conversation_language="ar")

    assert config.language == "ar"
    assert config.voice == "M1"
    assert config.enabled is False


@override_settings(SUPERTONIC_ARABIC_ENABLED=True, SUPERTONIC_ARABIC_VOICE="")
def test_arabic_conversation_with_enabled_flag_but_missing_voice_returns_disabled_state():
    config = get_supertonic_voice_config(conversation_language="ar")

    assert config.language == "ar"
    assert config.voice == ""
    assert config.enabled is False


@override_settings(SUPERTONIC_ARABIC_ENABLED=True, SUPERTONIC_ARABIC_VOICE="M1")
def test_arabic_conversation_with_enabled_flag_and_voice_resolves_correctly():
    config = get_supertonic_voice_config(conversation_language="ar")

    assert config == SupertonicVoiceConfig(language="ar", voice="M1", enabled=True)


@override_settings(SUPERTONIC_ENGLISH_VOICE="F1", SUPERTONIC_ARABIC_ENABLED=True, SUPERTONIC_ARABIC_VOICE="M1")
def test_unsupported_persisted_language_is_disabled_without_english_voice():
    config = get_supertonic_voice_config(conversation_language="fr")

    assert config.language == "fr"
    assert config.voice == ""
    assert config.enabled is False


@override_settings(SUPERTONIC_ENGLISH_VOICE="F1", SUPERTONIC_ARABIC_ENABLED=False, SUPERTONIC_ARABIC_VOICE="")
def test_arabic_does_not_use_english_f1_when_arabic_voice_not_configured():
    config = get_supertonic_voice_config(conversation_language="ar")

    assert config.voice != "F1"
    assert config.enabled is False


def test_arabic_fallback_reason_constant_is_stable():
    assert FALLBACK_REASON_ARABIC_TTS_UNAVAILABLE == "arabic_tts_unavailable"
