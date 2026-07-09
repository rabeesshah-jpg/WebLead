"""Post-completion replies after the booking link has already been shared."""

from __future__ import annotations

import re

from apps.qualification.domain.confirmation_reply import normalize_confirmation_message
from apps.qualification.domain.inbound_message_classification import classify_inbound_message
from apps.qualification.domain.messages import get_customer_message

_POST_BOOKING_EXIT_PATTERNS: tuple[str, ...] = (
    r"^exit(?: chat)?$",
    r"^(?:bye|goodbye|see you|talk later|cya|good night)(?:[!.,]?\s*)$",
    r"^(?:i'm done|im done|all done|that's all|thats all)(?:[!.,]?\s*)$",
)

_POST_BOOKING_RESEND_PATTERNS: tuple[str, ...] = (
    r"send(?: the)? (?:booking )?link again",
    r"resend(?: the)? (?:booking )?link",
    r"send again",
    r"(?:booking )?link again",
    r"share(?: the)? link again",
)

_POST_BOOKING_THANKS_PATTERNS: tuple[str, ...] = (
    r"^(?:thanks?|thank you|thx|ty|appreciate it|much appreciated)(?:[!.,]?\s*)$",
    r"^(?:ok|okay|k|cool|great|nice|good|cheers|got it|understood)(?:[!.,]?\s*)$",
)


def _matches_any(normalized: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, normalized) for pattern in patterns)


def build_post_booking_link_reply(*, message: str, language: str) -> str:
    """Return a short follow-up that references the booking link already shared above."""
    normalized = normalize_confirmation_message(message)

    if normalized and _matches_any(normalized, _POST_BOOKING_RESEND_PATTERNS):
        return get_customer_message(language=language, key="post_booking_resend_request")

    if normalized and _matches_any(normalized, _POST_BOOKING_EXIT_PATTERNS):
        return get_customer_message(language=language, key="post_booking_exit")

    if normalized and _matches_any(normalized, _POST_BOOKING_THANKS_PATTERNS):
        return get_customer_message(language=language, key="post_booking_thanks")

    classification = classify_inbound_message(message)
    if classification.small_talk_greeting and classification.small_talk_wellbeing:
        return get_customer_message(language=language, key="post_booking_greeting_wellbeing")
    if classification.small_talk_wellbeing:
        return get_customer_message(language=language, key="post_booking_wellbeing")
    if classification.small_talk_greeting:
        return get_customer_message(language=language, key="post_booking_greeting")

    return get_customer_message(language=language, key="post_booking_default")
