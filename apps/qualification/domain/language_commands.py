"""Explicit slash-command parsing for customer language changes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from apps.qualification.domain.language_selection import LANGUAGE_ARABIC, LANGUAGE_ENGLISH

LanguageCommandAction = Literal["show_picker", "set_language"]

_SET_LANGUAGE_ALIASES: dict[str, str] = {
    "en": LANGUAGE_ENGLISH,
    "english": LANGUAGE_ENGLISH,
    "ar": LANGUAGE_ARABIC,
    "arabic": LANGUAGE_ARABIC,
    "العربية": LANGUAGE_ARABIC,
}


@dataclass(frozen=True)
class LanguageCommand:
    action: LanguageCommandAction
    language: str | None = None


def _normalize_command_text(value: str) -> str:
    return " ".join(value.strip().split())


def parse_language_command(value: str | None) -> LanguageCommand | None:
    """
    Parse explicit ``/language`` customer commands.

    Returns ``None`` when the message is not an exact supported command.
    """
    if value is None:
        return None

    normalized = _normalize_command_text(value)
    if not normalized:
        return None

    parts = normalized.split(" ")
    if parts[0].casefold() != "/language":
        return None

    if len(parts) == 1:
        return LanguageCommand(action="show_picker", language=None)

    if len(parts) != 3 or parts[1].casefold() != "set":
        return None

    language = _SET_LANGUAGE_ALIASES.get(parts[2], _SET_LANGUAGE_ALIASES.get(parts[2].casefold()))
    if language is None:
        return None

    return LanguageCommand(action="set_language", language=language)
