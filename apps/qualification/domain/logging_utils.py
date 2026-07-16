"""Shared safe logging helpers for qualification modules."""

from __future__ import annotations


def message_sid_prefix(message_sid: str | None) -> str | None:
    """Return the safe MessageSid prefix format currently emitted in logs."""
    if not message_sid:
        return None
    return message_sid[:8]


def whatsapp_number_prefix(whatsapp_number: str | None) -> str | None:
    """Return a short safe prefix for a normalized WhatsApp number."""
    if not whatsapp_number:
        return None
    from apps.qualification.domain.validators import normalize_whatsapp_session_number

    try:
        canonical = normalize_whatsapp_session_number(whatsapp_number)
    except ValueError:
        return None
    return canonical[:8]


def lock_key_prefix(lock_key: str | None) -> str | None:
    """Return a short safe prefix for a conversation lock key."""
    if not lock_key:
        return None
    return lock_key[:40]
