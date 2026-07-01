"""Tests for the shared qualification cache backend."""

from __future__ import annotations

import pytest
from django.test import override_settings

from apps.qualification.persistence.cache_backend import (
    InMemoryQualificationCacheBackend,
    get_qualification_cache_backend,
    openrouter_cache_key,
    reset_qualification_cache_backend_for_tests,
    twilio_media_cache_key,
)


@pytest.fixture(autouse=True)
def _reset_cache_backend():
    reset_qualification_cache_backend_for_tests()
    yield
    reset_qualification_cache_backend_for_tests()


def test_in_memory_cache_stores_bytes_and_strings():
    backend = InMemoryQualificationCacheBackend()
    media_key = twilio_media_cache_key(message_sid="MM123", media_url="https://example.com/media")
    backend.set(media_key, b"audio-bytes", 3600)
    backend.set(openrouter_cache_key("abc123"), "completion-json", 3600)

    assert backend.get(media_key) == b"audio-bytes"
    assert backend.get(openrouter_cache_key("abc123")) == "completion-json"


def test_in_memory_cache_delete_by_prefix():
    backend = InMemoryQualificationCacheBackend()
    backend.set("twilio_media:one", b"a", 60)
    backend.set("twilio_media:two", b"b", 60)
    backend.set("openrouter:one", "x", 60)

    backend.delete_by_prefix("twilio_media:")

    assert backend.get("twilio_media:one") is None
    assert backend.get("twilio_media:two") is None
    assert backend.get("openrouter:one") == "x"


@override_settings(QUALIFICATION_REDIS_URL="")
def test_get_qualification_cache_backend_uses_memory_without_redis():
    backend = get_qualification_cache_backend()
    assert backend.backend_name == "memory"
