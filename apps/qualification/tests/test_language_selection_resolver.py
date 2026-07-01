"""Unit tests for resolve_selected_language."""

from __future__ import annotations

import pytest

from apps.qualification.domain.language_selection import (
    LANGUAGE_ARABIC,
    LANGUAGE_BUTTONS,
    LANGUAGE_ENGLISH,
    LANGUAGE_TEXT_FALLBACKS,
    resolve_selected_language,
)


@pytest.mark.parametrize(
    ("button_payload", "expected"),
    [
        ("lang_en", LANGUAGE_ENGLISH),
        ("lang_ar", LANGUAGE_ARABIC),
    ],
)
def test_button_payload_maps_to_language(button_payload: str, expected: str):
    assert resolve_selected_language(button_payload=button_payload, body=None) == expected


@pytest.mark.parametrize(
    ("body", "button_payload", "expected"),
    [
        ("العربية", "lang_en", LANGUAGE_ENGLISH),
        ("English", "lang_ar", LANGUAGE_ARABIC),
    ],
)
def test_valid_button_payload_overrides_conflicting_body(
    body: str,
    button_payload: str,
    expected: str,
):
    assert resolve_selected_language(button_payload=button_payload, body=body) == expected


@pytest.mark.parametrize(
    "body",
    [
        "English",
        "english",
        "العربية",
        "hello",
        "hi",
        "website",
        "+923001234567",
        "random text",
    ],
)
def test_body_text_is_not_resolved_without_button_payload(body: str):
    assert resolve_selected_language(button_payload=None, body=body) is None


def test_none_inputs_do_not_raise():
    assert resolve_selected_language(button_payload=None, body=None) is None


def test_language_buttons_exact_mappings():
    assert LANGUAGE_BUTTONS["lang_en"] == LANGUAGE_ENGLISH
    assert LANGUAGE_BUTTONS["lang_ar"] == LANGUAGE_ARABIC


def test_supported_fallback_values_cover_english_and_arabic_only():
    assert set(LANGUAGE_TEXT_FALLBACKS.values()) == {LANGUAGE_ENGLISH, LANGUAGE_ARABIC}
