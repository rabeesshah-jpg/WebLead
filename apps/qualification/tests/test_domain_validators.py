"""Tests for shared qualification domain validators."""

from __future__ import annotations

import pytest

from apps.qualification import extractor
from apps.qualification.domain.validators import (
    E164_PHONE_PATTERN,
    is_direct_phone_reply,
    is_valid_e164_phone_number,
    normalize_preferred_phone_input,
    preferred_phone_reply_needs_openrouter,
)


@pytest.mark.parametrize(
    "phone",
    [
        "+923001234567",
        "+14155552671",
        "+12345678",
        "+123456789012345",
    ],
)
def test_valid_e164_numbers_are_accepted(phone: str):
    assert is_valid_e164_phone_number(phone) is True


@pytest.mark.parametrize(
    "phone",
    [
        "923001234567",
        "+0",
        "+0123456789",
        "+92300",
        "+92 3001234567",
        "+92-300-1234567",
        "",
        "   ",
        "+1234567",
    ],
)
def test_invalid_e164_numbers_are_rejected(phone: str):
    assert is_valid_e164_phone_number(phone) is False


@pytest.mark.parametrize("value", [None, 923001234567, [], {}])
def test_non_string_input_is_rejected(value: object):
    assert is_valid_e164_phone_number(value) is False  # type: ignore[arg-type]


def test_extractor_reexports_shared_pattern_object():
    assert extractor.E164_PHONE_PATTERN is E164_PHONE_PATTERN


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+923246271156", "+923246271156"),
        ("+92 324 627 1156", "+923246271156"),
        ("+92-324-627-1156", "+923246271156"),
        ("(0324) 6271156", "+923246271156"),
    ],
)
def test_normalize_preferred_phone_input_accepts_common_formats(raw: str, expected: str):
    assert normalize_preferred_phone_input(
        raw,
        known_whatsapp_number="+923001234567",
    ) == expected


@pytest.mark.parametrize(
    "raw",
    ["abc", "123", "+12", "not a phone"],
)
def test_normalize_preferred_phone_input_rejects_invalid_values(raw: str):
    assert normalize_preferred_phone_input(
        raw,
        known_whatsapp_number="+923001234567",
    ) is None


def test_normalize_preferred_phone_input_rejects_embedded_phone_in_sentence():
    message = "Please contact me on +923009999999"
    assert preferred_phone_reply_needs_openrouter(message) is True
    assert normalize_preferred_phone_input(
        message,
        known_whatsapp_number="+923001234567",
    ) == "+923009999999"
