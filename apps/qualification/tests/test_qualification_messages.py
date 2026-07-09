"""Tests for the bilingual qualification message catalog."""

from __future__ import annotations

import pytest

from apps.qualification.domain.language import LANGUAGE_ARABIC, LANGUAGE_ENGLISH
from apps.qualification.domain.messages import (
    QUALIFICATION_MESSAGES,
    REQUIRED_MESSAGE_KEYS,
    UnknownMessageKeyError,
    get_customer_message,
    get_language_changed_confirmation_message,
    get_qualification_question,
)

pytestmark = pytest.mark.django_db


def test_english_message_lookup_returns_existing_english_text():
    assert get_customer_message(language=LANGUAGE_ENGLISH, key="project_type") == (
        "Are you looking for a new website, an upgrade to your existing website, "
        "or both?"
    )
    assert (
        get_customer_message(language=LANGUAGE_ENGLISH, key="preferred_phone")
        == "Please share the best phone number to reach you."
    )


def test_onboarding_and_welcome_back_copy_uses_lightweight_formatting():
    intro = get_customer_message(language=LANGUAGE_ENGLISH, key="onboarding_intro")
    welcome = get_customer_message(language=LANGUAGE_ENGLISH, key="onboarding_welcome_back")
    assert intro.startswith("Hi, this is Noura from Good Websites!")
    assert "To get started" in intro
    assert "Send M to open the menu" in intro
    assert "*" not in intro
    assert welcome == "Welcome back! Let's continue."
    assert "*" not in welcome


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


def test_language_changed_keys_are_language_specific():
    assert "language_changed_to_english" in QUALIFICATION_MESSAGES[LANGUAGE_ENGLISH]
    assert "language_changed_to_arabic" in QUALIFICATION_MESSAGES[LANGUAGE_ARABIC]
    assert "language_changed_to_arabic" not in QUALIFICATION_MESSAGES[LANGUAGE_ENGLISH]
    assert "language_changed_to_english" not in QUALIFICATION_MESSAGES[LANGUAGE_ARABIC]


def test_language_changed_confirmation_messages_exist():
    assert (
        get_language_changed_confirmation_message(language=LANGUAGE_ENGLISH)
        == "Language set to English. We can continue from here."
    )
    assert (
        get_language_changed_confirmation_message(language=LANGUAGE_ARABIC)
        == "تم ضبط اللغة إلى العربية. يمكننا المتابعة من هنا."
    )


def test_unsupported_language_falls_back_to_english():
    assert (
        get_customer_message(
            language="fr",
            key="completion_with_booking_link",
            booking_link="https://example.com",
        )
        == get_customer_message(
            language=LANGUAGE_ENGLISH,
            key="completion_with_booking_link",
            booking_link="https://example.com",
        )
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
