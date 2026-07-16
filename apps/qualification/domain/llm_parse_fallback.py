"""Safe fallback response when LLM extraction JSON cannot be parsed."""

from __future__ import annotations

from typing import Any

from apps.qualification.conversation_flow import get_active_next_field
from apps.qualification.conversation_state import get_accepted_fields
from apps.qualification.domain.language_selection import normalize_conversation_language
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.domain.qualification_questions import get_qualification_question_text


def build_llm_parse_failure_response(
    *,
    whatsapp_number: str,
    language: str,
) -> dict[str, Any]:
    """Return a safe in-progress turn response after LLM JSON parse failure."""
    normalized_language = normalize_conversation_language(language)
    persisted_fields = dict(get_accepted_fields(whatsapp_number))
    next_field = get_active_next_field(persisted_fields)
    if next_field:
        reply_text = get_qualification_question_text(
            language=normalized_language,
            field=next_field,
            repeat=False,
            whatsapp_number=whatsapp_number,
        )
    else:
        reply_text = get_customer_message(
            language=normalized_language,
            key="llm_parse_fallback",
        )
    return {
        "accepted_fields": persisted_fields,
        "rejected_fields": {},
        "human_handoff_requested": False,
        "next_field": next_field,
        "reply_text": reply_text,
        "qualification_status": "in_progress",
        "preferred_phone": persisted_fields.get("preferred_phone"),
        "conversation_language": normalized_language,
        "llm_parse_failed": True,
        "complete": False,
        "whatsapp_text": "",
        "skip_onboarding_intro": True,
    }
