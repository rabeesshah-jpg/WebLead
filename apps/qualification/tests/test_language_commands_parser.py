"""Unit tests for explicit /language slash-command parsing."""

from __future__ import annotations

import pytest

from apps.qualification.domain.language_commands import (
    LanguageCommand,
    parse_language_command,
)
from apps.qualification.domain.language_selection import LANGUAGE_ARABIC, LANGUAGE_ENGLISH


def test_slash_language_returns_show_picker():
    assert parse_language_command("/language") == LanguageCommand(
        action="show_picker",
        language=None,
    )


@pytest.mark.parametrize(
    "command",
    [
        "/language set en",
        "/language set english",
        "/LANGUAGE SET EN",
        "/language   set   english",
    ],
)
def test_set_english_commands(command: str):
    assert parse_language_command(command) == LanguageCommand(
        action="set_language",
        language=LANGUAGE_ENGLISH,
    )


@pytest.mark.parametrize(
    "command",
    [
        "/language set ar",
        "/language set arabic",
        "/language set العربية",
        "/LANGUAGE SET AR",
    ],
)
def test_set_arabic_commands(command: str):
    assert parse_language_command(command) == LanguageCommand(
        action="set_language",
        language=LANGUAGE_ARABIC,
    )


@pytest.mark.parametrize(
    "message",
    [
        "I need an English website.",
        "Can you make an Arabic landing page?",
        "My website needs Arabic and English pages.",
        "English",
        "العربية",
        "language",
        "LANGUAGE",
        "/language help",
        "/language set fr",
        "/language set",
        "/languages",
    ],
)
def test_normal_messages_do_not_parse_as_commands(message: str):
    assert parse_language_command(message) is None


def test_none_and_blank_do_not_parse():
    assert parse_language_command(None) is None
    assert parse_language_command("   ") is None
