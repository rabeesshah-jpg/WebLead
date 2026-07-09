"""Safe FAQ answers for common qualification questions."""

from __future__ import annotations

from apps.qualification.domain.inbound_message_classification import InboundMessageClassification
from apps.qualification.domain.messages import get_customer_message


def build_faq_answer(
    classification: InboundMessageClassification,
    *,
    language: str,
) -> str | None:
    """Return a brief FAQ answer when the message contains a supported question."""
    parts: list[str] = []
    if classification.user_question_services:
        parts.append(get_customer_message(language=language, key="faq_services"))
    if classification.user_question_location:
        parts.append(get_customer_message(language=language, key="faq_location"))
    if classification.user_question_pricing:
        parts.append(get_customer_message(language=language, key="faq_pricing"))
    if not parts:
        return None
    return " ".join(parts)
