"""Shared pure validators for qualification domain rules."""

from __future__ import annotations

import re

E164_PHONE_PATTERN = re.compile(r"^\+[1-9][0-9]{7,14}$")
_PHONE_FORMATTING_PATTERN = re.compile(r"[^\d+]+")
_DIRECT_PHONE_REPLY_PATTERN = re.compile(r"^[\d+\s().-]+$")


def is_valid_e164_phone_number(value: str) -> bool:
    """
    Return True only when value matches the project's existing E.164 contract.

    This is a pure validator. It does not strip, normalize, coerce, log,
    or mutate the supplied value.
    """
    if not isinstance(value, str):
        return False
    return bool(E164_PHONE_PATTERN.fullmatch(value))


def collapse_phone_formatting(value: str) -> str:
    """Remove spaces, hyphens, parentheses, and other non-digit separators."""
    return _PHONE_FORMATTING_PATTERN.sub("", value.strip())


def _country_code_from_e164(phone_number: str) -> str | None:
    normalized = collapse_phone_formatting(phone_number)
    if not normalized.startswith("+"):
        return None
    if normalized.startswith("+92"):
        return "92"
    known_digits = normalized[1:]
    for length in range(3, 0, -1):
        if len(known_digits) <= length:
            continue
        country_code = known_digits[:length]
        if normalized == f"+{country_code}{known_digits[length:]}":
            return country_code
    return None


def is_direct_phone_reply(message: str) -> bool:
    """Return True when the message contains only phone-formatting characters."""
    stripped = message.strip()
    if not stripped:
        return False
    return bool(_DIRECT_PHONE_REPLY_PATTERN.fullmatch(stripped))


def preferred_phone_reply_needs_openrouter(message: str) -> bool:
    """
    Return True when a preferred-phone reply should be parsed by OpenRouter.

    Free-text replies that embed an E.164 number in a sentence still use the
    existing extraction path. Bare or formatting-only replies stay local.
    """
    if is_direct_phone_reply(message):
        return False

    collapsed = collapse_phone_formatting(message)
    embedded_numbers = re.findall(r"\+[1-9][0-9]{7,14}", collapsed)
    if not embedded_numbers:
        return False

    return bool(re.search(r"[A-Za-z\u0600-\u06FF]", message))


def normalize_preferred_phone_input(
    message: str,
    *,
    known_whatsapp_number: str,
) -> str | None:
    """
    Normalize customer phone text into E.164 when possible.

    Supports common formatting such as spaces, hyphens, and parentheses.
    Local trunk numbers starting with ``0`` are converted using the country
    code from ``known_whatsapp_number``.
    """
    collapsed = collapse_phone_formatting(message)
    if not collapsed:
        return None

    if collapsed.startswith("+"):
        candidate = collapsed
    elif collapsed.startswith("00"):
        candidate = f"+{collapsed[2:]}"
    elif collapsed.startswith("0"):
        country_code = _country_code_from_e164(known_whatsapp_number)
        if country_code is None:
            return None
        candidate = f"+{country_code}{collapsed[1:]}"
    else:
        return None

    if is_valid_e164_phone_number(candidate):
        return candidate
    return None
