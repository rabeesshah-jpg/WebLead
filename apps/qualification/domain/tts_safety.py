"""Guards that keep URLs and onboarding copy out of TTS / spoken responses."""

from __future__ import annotations

import logging
import re

from apps.qualification.api.logging import log_qualification_event

_URL_PATTERN = re.compile(
    r"(https?://\S+|www\.\S+)",
    flags=re.IGNORECASE,
)

_ONBOARDING_MENU_MARKERS = (
    "to open the menu",
    "to change your language",
    "to change language",
    "send capital m",
    "send *m*",
    "how to use this chat",
    "quick reminders",
    "*to get started:*",
    "• ",
)

DEFAULT_TTS_URL_REPLACEMENT = (
    "Perfect, thank you. I've sent the booking link above. "
    "You can choose a time whenever you're ready."
)
SPOKEN_TEXT_WARN_LENGTH = 180


def spoken_text_contains_url(text: str) -> bool:
    """Return True when spoken text would include a URL."""
    return bool(_URL_PATTERN.search(text or ""))


def spoken_text_contains_onboarding_copy(text: str) -> bool:
    """Return True when spoken text includes menu/language onboarding instructions."""
    normalized = " ".join((text or "").split()).strip().lower()
    if not normalized:
        return False
    return any(marker in normalized for marker in _ONBOARDING_MENU_MARKERS)


def get_safe_voice_fallback(*, language: str = "en") -> str:
    """Return a short spoken line when unsafe onboarding copy is stripped."""
    from apps.qualification.domain.messages import get_customer_message

    return get_customer_message(language=language, key="onboarding_intro_voice")


def sanitize_spoken_text_for_tts(
    text: str,
    *,
    replacement: str = DEFAULT_TTS_URL_REPLACEMENT,
    language: str = "en",
) -> str:
    """
    Remove URLs and onboarding instructions from text that will be spoken aloud.

    When any URL is present, replace the whole spoken message with a short
    WhatsApp handoff line so the agent never reads calendar links.
    """
    cleaned = " ".join((text or "").split()).strip()
    if not cleaned:
        return cleaned
    if spoken_text_contains_url(cleaned):
        return replacement
    if spoken_text_contains_onboarding_copy(cleaned):
        cleaned = get_safe_voice_fallback(language=language)
    if len(cleaned) > SPOKEN_TEXT_WARN_LENGTH:
        log_qualification_event(
            "spoken_text_too_long",
            level=logging.WARNING,
            spoken_text_length=len(cleaned),
            language=language,
        )
    return cleaned
