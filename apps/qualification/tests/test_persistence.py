"""Tests for qualification persistence backends."""

from __future__ import annotations

import pytest
from django.test import override_settings

from apps.qualification.conversation_state import (
    clear_conversations,
    get_accepted_fields,
    save_accepted_fields,
)
from apps.qualification.message_idempotency import (
    begin_idempotent_turn,
    cache_turn_response,
    clear_message_sid_cache,
    get_cached_turn_response,
)
from apps.qualification.persistence.backends import (
    InMemoryPersistenceBackend,
    reset_persistence_backend_for_tests,
)
from apps.qualification.public_urls import get_public_media_base_url

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset_backend():
    reset_persistence_backend_for_tests()
    clear_conversations()
    clear_message_sid_cache()
    yield
    reset_persistence_backend_for_tests()
    clear_conversations()
    clear_message_sid_cache()


def test_conversation_state_persists_across_backend_access():
    save_accepted_fields("+923001234567", {"project_type": "new_website"})
    assert get_accepted_fields("+923001234567") == {"project_type": "new_website"}


def test_conversation_state_normalizes_whatsapp_number_formats():
    save_accepted_fields("+92 300 1234567", {"project_type": "new_website"})
    assert get_accepted_fields("whatsapp:+923001234567") == {"project_type": "new_website"}


def test_message_sid_cache_round_trip():
    payload = {"reply_text": "Hello", "qualification_status": "in_progress"}
    cache_turn_response("SM1234567890abcdef1234567890abcd", payload)
    assert get_cached_turn_response("SM1234567890abcdef1234567890abcd") == payload


def test_begin_idempotent_turn_returns_cached_response_without_reprocessing():
    payload = {"reply_text": "Cached", "qualification_status": "in_progress"}
    cache_turn_response("SM1234567890abcdef1234567890abcd", payload)
    assert begin_idempotent_turn("SM1234567890abcdef1234567890abcd") == payload


def test_in_memory_begin_turn_allows_single_processor():
    backend = InMemoryPersistenceBackend()
    message_sid = "SM1234567890abcdef1234567890abcd"
    assert backend.begin_turn(message_sid) is None
    backend.set_turn_response(message_sid, {"reply_text": "Done"})
    assert backend.begin_turn(message_sid) == {"reply_text": "Done"}


@override_settings(PUBLIC_MEDIA_BASE_URL="https://media.example.com", BASE_WEBHOOK_URL="https://api.example.com")
def test_public_media_base_url_prefers_explicit_setting():
    assert get_public_media_base_url() == "https://media.example.com"


@override_settings(PUBLIC_MEDIA_BASE_URL="", BASE_WEBHOOK_URL="https://api.example.com")
def test_public_media_base_url_falls_back_to_base_webhook_url():
    assert get_public_media_base_url() == "https://api.example.com"
