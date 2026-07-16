"""Deterministic yes/no matching for WhatsApp number confirmation."""

from __future__ import annotations

import re
from typing import Literal

_YES_CONFIRMATION_PHRASES: tuple[str, ...] = (
    "yes",
    "y",
    "yeah",
    "yep",
    "yup",
    "correct",
    "confirm",
    "confirmed",
    "ok",
    "okay",
    "haan",
    "han",
    "ji",
    "sure",
    "it is",
    "this is best",
    "yes it is",
    "yes it's best",
    "yes its best",
    "it's best",
    "its best",
    "best number",
    "this number is best",
)

_NO_CONFIRMATION_PHRASES: tuple[str, ...] = (
    "no",
    "n",
    "nope",
    "nah",
    "nahi",
    "nahin",
    "not this number",
    "no it is not",
    "use another number",
    "different number",
)


def normalize_confirmation_message(message: str) -> str:
    """Normalize inbound text for deterministic yes/no matching."""
    normalized = message.strip().lower().replace("\u2019", "'")
    normalized = re.sub(r"[^\w\s']", " ", normalized)
    normalized = " ".join(normalized.split())
    return normalized.strip(".,!?;:\"' ")


def _phrase_matches(normalized: str, phrase: str) -> bool:
    if normalized == phrase:
        return True
    if len(phrase) == 1:
        return normalized == phrase
    pattern = rf"(?:^|\s){re.escape(phrase)}(?:\s|$)"
    return bool(re.search(pattern, normalized))


def classify_whatsapp_confirmation_reply(message: str) -> Literal["yes", "no", "unclear"]:
    """Classify a customer reply to the WhatsApp confirmation question."""
    normalized = normalize_confirmation_message(message)

    for phrase in _NO_CONFIRMATION_PHRASES:
        if _phrase_matches(normalized, phrase):
            return "no"

    for phrase in _YES_CONFIRMATION_PHRASES:
        if _phrase_matches(normalized, phrase):
            return "yes"

    return "unclear"
