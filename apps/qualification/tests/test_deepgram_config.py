"""Tests for language-aware Deepgram transcription configuration."""

from __future__ import annotations

import pytest
from django.test import override_settings

from apps.qualification.deepgram_client import DeepgramConfigurationError
from apps.qualification.domain.deepgram_config import get_deepgram_transcription_config
from apps.qualification.domain.language_selection import LANGUAGE_ARABIC, LANGUAGE_ENGLISH

BASE_DEEPGRAM_SETTINGS = {
    "DEEPGRAM_MODEL": "nova-2",
    "DEEPGRAM_LANGUAGE": "en",
    "DEEPGRAM_TIMEOUT_SECONDS": 60,
    "DEEPGRAM_ENGLISH_MODEL": "",
    "DEEPGRAM_ENGLISH_LANGUAGE": "",
    "DEEPGRAM_ARABIC_MODEL": "nova-3",
    "DEEPGRAM_ARABIC_LANGUAGE": "ar"}


@override_settings(**BASE_DEEPGRAM_SETTINGS)
def test_english_uses_explicit_english_overrides_when_configured():
    with override_settings(
        DEEPGRAM_ENGLISH_MODEL="nova-2-explicit",
        DEEPGRAM_ENGLISH_LANGUAGE="en-GB",
    ):
        config = get_deepgram_transcription_config(conversation_language=LANGUAGE_ENGLISH)

    assert config.model == "nova-2-explicit"
    assert config.language == "en-GB"
    assert config.punctuate is False
    assert config.smart_format is False
    assert config.timeout_seconds == 60


@override_settings(**BASE_DEEPGRAM_SETTINGS)
def test_english_falls_back_to_legacy_deepgram_settings():
    config = get_deepgram_transcription_config(conversation_language=LANGUAGE_ENGLISH)

    assert config.model == "nova-2"
    assert config.language == "en"


@override_settings(**BASE_DEEPGRAM_SETTINGS)
def test_arabic_uses_arabic_model_and_language():
    config = get_deepgram_transcription_config(conversation_language=LANGUAGE_ARABIC)

    assert config.model == "nova-3"
    assert config.language == "ar"
    assert config.punctuate is False
    assert config.smart_format is False


@override_settings(**BASE_DEEPGRAM_SETTINGS)
def test_arabic_configuration_does_not_use_english_language():
    config = get_deepgram_transcription_config(conversation_language=LANGUAGE_ARABIC)

    assert config.language != "en"


@override_settings(**BASE_DEEPGRAM_SETTINGS)
def test_arabic_configuration_does_not_use_multi_language():
    config = get_deepgram_transcription_config(conversation_language=LANGUAGE_ARABIC)

    assert config.language != "multi"


@override_settings(**{**BASE_DEEPGRAM_SETTINGS, "DEEPGRAM_ARABIC_MODEL": ""})
def test_missing_arabic_model_raises_configuration_error():
    with pytest.raises(DeepgramConfigurationError, match="Arabic Deepgram"):
        get_deepgram_transcription_config(conversation_language=LANGUAGE_ARABIC)


@override_settings(**{**BASE_DEEPGRAM_SETTINGS, "DEEPGRAM_ARABIC_LANGUAGE": ""})
def test_missing_arabic_language_raises_configuration_error():
    with pytest.raises(DeepgramConfigurationError, match="Arabic Deepgram"):
        get_deepgram_transcription_config(conversation_language=LANGUAGE_ARABIC)


@override_settings(**{**BASE_DEEPGRAM_SETTINGS, "DEEPGRAM_ARABIC_LANGUAGE": "multi"})
def test_arabic_multi_language_setting_raises_configuration_error():
    with pytest.raises(DeepgramConfigurationError, match="must not be English or multi"):
        get_deepgram_transcription_config(conversation_language=LANGUAGE_ARABIC)


@override_settings(**BASE_DEEPGRAM_SETTINGS)
def test_unknown_language_falls_back_to_english_configuration():
    config = get_deepgram_transcription_config(conversation_language="unknown")

    assert config.model == "nova-2"
    assert config.language == "en"
    assert config.language != "multi"
