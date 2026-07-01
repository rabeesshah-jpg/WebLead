"""Shared safe logging helpers for qualification modules."""

from __future__ import annotations


def message_sid_prefix(message_sid: str | None) -> str | None:
    """Return the safe MessageSid prefix format currently emitted in logs."""
    if not message_sid:
        return None
    return message_sid[:8]
