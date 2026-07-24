"""Tests for WhatsApp conversation language foundation (ORM, migrations, constants)."""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError
from django.test import override_settings

from apps.qualification.domain.language import (
    LANGUAGE_ARABIC,
    LANGUAGE_BUTTON_PAYLOADS,
    LANGUAGE_ENGLISH,
    SUPPORTED_CONVERSATION_LANGUAGES,
)
from apps.qualification.models import WhatsAppConversationSession
from apps.qualification.services.conversation_session_service import (
    create_conversation_session,
    get_or_create_conversation_session,
)
from apps.qualification.integrations.twilio_language_picker import (
    TwilioLanguagePickerConfigurationError,
    send_language_picker,
)

pytestmark = pytest.mark.django_db


def test_new_conversation_session_has_null_language():
    session = create_conversation_session(whatsapp_number="+15551234567")
    session.refresh_from_db()
    assert session.language is None
    assert session.language_selected_at is None


def test_get_or_create_defaults_language_to_none():
    session, created = get_or_create_conversation_session(whatsapp_number="+15559876543")
    assert created is True
    assert session.language is None


def test_language_selected_at_accepts_none():
    session = WhatsAppConversationSession(
        whatsapp_number="+15551112222",
        language=LANGUAGE_ENGLISH,
        language_selected_at=None,
    )
    session.full_clean()
    session.save()
    session.refresh_from_db()
    assert session.language_selected_at is None


@pytest.mark.parametrize(
    ("language",),
    [
        (LANGUAGE_ENGLISH,),
        (LANGUAGE_ARABIC,),
    ],
)
def test_model_accepts_supported_languages(language: str):
    session = WhatsAppConversationSession(
        whatsapp_number=f"+1555{language}0001",
        language=language,
    )
    session.full_clean()
    session.save()


def test_invalid_language_fails_validation():
    session = WhatsAppConversationSession(
        whatsapp_number="+15553334444",
        language="fr",
    )
    with pytest.raises(ValidationError):
        session.full_clean()


def test_data_migration_updates_only_null_language_rows():
    null_session = WhatsAppConversationSession.objects.create(
        whatsapp_number="+15550000001",
        language=None,
    )
    arabic_session = WhatsAppConversationSession.objects.create(
        whatsapp_number="+15550000002",
        language=LANGUAGE_ARABIC,
    )

    migration = importlib.import_module(
        "apps.qualification.migrations.0002_backfill_conversation_language_en",
    )
    migration.backfill_language_en(apps, None)

    null_session.refresh_from_db()
    arabic_session.refresh_from_db()
    assert null_session.language == LANGUAGE_ENGLISH
    assert arabic_session.language == LANGUAGE_ARABIC


def test_data_migration_does_not_overwrite_existing_language():
    english_session = WhatsAppConversationSession.objects.create(
        whatsapp_number="+15550000003",
        language=LANGUAGE_ENGLISH,
    )
    migration = importlib.import_module(
        "apps.qualification.migrations.0002_backfill_conversation_language_en",
    )
    migration.backfill_language_en(apps, None)
    english_session.refresh_from_db()
    assert english_session.language == LANGUAGE_ENGLISH


def test_language_button_payloads_map_quick_reply_values():
    assert LANGUAGE_BUTTON_PAYLOADS["lang_en"] == LANGUAGE_ENGLISH
    assert LANGUAGE_BUTTON_PAYLOADS["lang_ar"] == LANGUAGE_ARABIC


def test_supported_conversation_languages_include_only_english_and_arabic():
    assert SUPPORTED_CONVERSATION_LANGUAGES == frozenset({LANGUAGE_ENGLISH, LANGUAGE_ARABIC})


@override_settings(WAHA_BASE_URL="", WAHA_API_KEY="")
def test_language_picker_requires_waha_configuration():
    from apps.whatsapp.message_service import WhatsAppSendError

    assert send_language_picker.__name__ == "send_language_picker"
    with pytest.raises((TwilioLanguagePickerConfigurationError, WhatsAppSendError)):
        send_language_picker(to_number="+15551234567")


@override_settings(
    WAHA_BASE_URL="https://waha.example.com",
    WAHA_API_KEY="test-waha-api-key",
)
def test_language_picker_send_uses_waha_when_configured(monkeypatch):
    calls: list[dict] = []

    def _fake_buttons(**kwargs):
        calls.append(kwargs)
        return "waha-lang-1"

    monkeypatch.setattr(
        "apps.whatsapp.message_service.waha_client.send_buttons",
        _fake_buttons,
    )
    assert send_language_picker(to_number="+15551234567") == "waha-lang-1"
    assert calls and calls[0]["buttons"][0]["id"] == "lang_en"
