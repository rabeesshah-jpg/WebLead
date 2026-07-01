"""Tests for the bilingual qualification message catalog."""

from __future__ import annotations

import pytest

from apps.qualification.domain.language import LANGUAGE_ARABIC, LANGUAGE_ENGLISH
from apps.qualification.domain.messages import (
    QUALIFICATION_MESSAGES,
    REQUIRED_MESSAGE_KEYS,
    UnknownMessageKeyError,
    get_customer_message,
    get_qualification_question,
)

pytestmark = pytest.mark.django_db


def test_english_message_lookup_returns_existing_english_text():
    assert (
        get_customer_message(language=LANGUAGE_ENGLISH, key="project_type")
        == "Are you looking for a new website or an upgrade to your existing website?"
    )
    assert (
        get_customer_message(language=LANGUAGE_ENGLISH, key="preferred_phone")
        == "Please share the best phone number to reach you."
    )


def test_arabic_message_lookup_returns_arabic_text():
    assert (
        get_customer_message(language=LANGUAGE_ARABIC, key="project_type")
        == "ما نوع الموقع الإلكتروني الذي تحتاجه؟"
    )
    assert "يرجى إرسال رقم هاتف صحيح" in get_customer_message(
        language=LANGUAGE_ARABIC,
        key="invalid_phone",
    )


def test_all_required_message_keys_exist_for_both_languages():
    for language in (LANGUAGE_ENGLISH, LANGUAGE_ARABIC):
        catalog = QUALIFICATION_MESSAGES[language]
        for key in REQUIRED_MESSAGE_KEYS:
            assert key in catalog
            assert catalog[key].strip()


def test_unsupported_language_falls_back_to_english():
    assert (
        get_customer_message(language="fr", key="completion")
        == get_customer_message(language=LANGUAGE_ENGLISH, key="completion")
    )
    assert (
        get_qualification_question(language="unknown", field="requirements")
        == get_customer_message(language=LANGUAGE_ENGLISH, key="requirements")
    )


def test_arabic_language_is_not_silently_converted_to_english():
    arabic_text = get_customer_message(language=LANGUAGE_ARABIC, key="human_handoff")
    english_text = get_customer_message(language=LANGUAGE_ENGLISH, key="human_handoff")
    assert arabic_text != english_text
    assert "شكرًا" in arabic_text


def test_missing_message_key_raises_unknown_message_key_error():
    with pytest.raises(UnknownMessageKeyError):
        get_customer_message(language=LANGUAGE_ENGLISH, key="not_a_real_key")
