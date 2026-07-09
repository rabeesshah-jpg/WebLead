"""Parsing for WhatsApp help / instructions requests."""

from __future__ import annotations

_HELP_COMMANDS: frozenset[str] = frozenset(
    {
        "help",
        "/help",
        "instructions",
        "menu help",
    }
)


def is_help_request(message: str | None) -> bool:
    """Return True when the customer explicitly asks for chat help or instructions."""
    normalized = " ".join((message or "").split()).strip().lower()
    return normalized in _HELP_COMMANDS
