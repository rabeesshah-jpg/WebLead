"""Tests for startup voice-agent configuration logging."""

from __future__ import annotations

import json
import logging

import pytest
from django.test import override_settings

from apps.qualification.startup_validation import log_voice_agent_config


@override_settings(
    DEEPGRAM_MODEL="nova-2",
    DEEPGRAM_TIMEOUT_SECONDS=8,
    DEEPGRAM_API_KEY="configured-key",
    WAHA_MEDIA_DOWNLOAD_TIMEOUT_SECONDS=30,
    WAHA_BASE_URL="https://waha.example.com",
    WAHA_API_KEY="test-waha-api-key",
    OPENROUTER_MODEL="openai/gpt-4o-mini",
    OPENROUTER_TIMEOUT_SECONDS=20,
    OPENROUTER_API_KEY="configured-key",
)
def test_log_voice_agent_config_emits_safe_values_only(caplog):
    with caplog.at_level(logging.INFO, logger="apps.qualification"):
        log_voice_agent_config()

    payload = json.loads(caplog.records[-1].message)
    assert payload["step"] == "voice_agent_config"
    assert payload["deepgram_model"] == "nova-2"
    assert payload["deepgram_timeout_seconds"] == 8
    assert payload["deepgram_api_key"] == "configured"
    assert payload["waha_media_download_timeout_seconds"] == 30
    assert payload["waha_media_credentials"] == "configured"
    assert payload["openrouter_model"] == "openai/gpt-4o-mini"
    assert payload["openrouter_timeout_seconds"] == 20
    assert "sk-" not in caplog.text
