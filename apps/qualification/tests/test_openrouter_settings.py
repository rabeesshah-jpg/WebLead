"""Tests for OpenRouter Django settings."""

from __future__ import annotations

import importlib

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings


def test_default_base_url():
    assert settings.OPENROUTER_BASE_URL == "https://openrouter.ai/api/v1"


def test_default_timeout_is_20():
    assert settings.OPENROUTER_TIMEOUT_SECONDS == 20


def test_api_key_default_is_empty_string(monkeypatch):
    module = _reload_settings_module(monkeypatch, OPENROUTER_API_KEY=None)
    assert module.OPENROUTER_API_KEY == ""


def test_model_default_is_empty_string(monkeypatch):
    module = _reload_settings_module(monkeypatch, OPENROUTER_MODEL=None)
    assert module.OPENROUTER_MODEL == ""


@override_settings(OPENROUTER_BASE_URL="https://custom.example/api/v1")
def test_base_url_can_be_overridden():
    assert settings.OPENROUTER_BASE_URL == "https://custom.example/api/v1"


@override_settings(OPENROUTER_TIMEOUT_SECONDS=30)
def test_timeout_can_be_overridden_with_valid_positive_integer():
    assert settings.OPENROUTER_TIMEOUT_SECONDS == 30


def _reload_settings_module(monkeypatch, **env_values: str | None) -> object:
    import config.settings as settings_module

    monkeypatch.setattr("environ.Env.read_env", lambda *args, **kwargs: None)
    for key, value in env_values.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    importlib.reload(settings_module)
    return settings_module


def test_base_url_trailing_slash_is_removed(monkeypatch):
    module = _reload_settings_module(
        monkeypatch,
        OPENROUTER_BASE_URL="https://custom.example/api/v1/",
    )
    assert module.OPENROUTER_BASE_URL == "https://custom.example/api/v1"


@pytest.mark.parametrize("invalid_value", ["0", "-1", "-10", "not-a-number"])
def test_invalid_timeout_values_are_rejected(monkeypatch, invalid_value: str):
    with pytest.raises(ImproperlyConfigured, match="OPENROUTER_TIMEOUT_SECONDS"):
        _reload_settings_module(monkeypatch, OPENROUTER_TIMEOUT_SECONDS=invalid_value)


def test_valid_timeout_from_environment(monkeypatch):
    module = _reload_settings_module(monkeypatch, OPENROUTER_TIMEOUT_SECONDS="45")
    assert module.OPENROUTER_TIMEOUT_SECONDS == 45
