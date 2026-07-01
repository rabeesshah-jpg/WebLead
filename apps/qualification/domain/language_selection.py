"""Pure language-selection resolution for WhatsApp inbound messages."""

from __future__ import annotations

LANGUAGE_ENGLISH = "en"
LANGUAGE_ARABIC = "ar"

LANGUAGE_BUTTONS: dict[str, str] = {
    "lang_en": LANGUAGE_ENGLISH,
    "lang_ar": LANGUAGE_ARABIC,
}

LANGUAGE_TEXT_FALLBACKS: dict[str, str] = {
    "english": LANGUAGE_ENGLISH,
    "en": LANGUAGE_ENGLISH,
    "1": LANGUAGE_ENGLISH,
    "arabic": LANGUAGE_ARABIC,
    "العربية": LANGUAGE_ARABIC,
    "عربي": LANGUAGE_ARABIC,
    "ar": LANGUAGE_ARABIC,
    "2": LANGUAGE_ARABIC,
}


def normalize_conversation_language(language: str | None) -> str:
    """Return a supported language code, falling back to English when unset or invalid."""
    if language == LANGUAGE_ARABIC:
        return LANGUAGE_ARABIC
    return LANGUAGE_ENGLISH


def resolve_selected_language(
    *,
    button_payload: str | None,
    body: str | None = None,
) -> str | None:
    """
    Resolve language from a Twilio Quick Reply ``ButtonPayload`` only.

    Visible ``Body`` text is handled separately via pending-picker fallback.
    """
    if button_payload in LANGUAGE_BUTTONS:
        return LANGUAGE_BUTTONS[button_payload]
    return None
