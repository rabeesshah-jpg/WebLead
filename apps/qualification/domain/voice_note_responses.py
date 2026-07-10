"""In-band responses for WhatsApp voice-note edge cases."""

from __future__ import annotations

from typing import Any

from apps.qualification.conversation_flow import get_active_next_field
from apps.qualification.conversation_state import get_accepted_fields
from apps.qualification.domain.language_selection import normalize_conversation_language
from apps.qualification.domain.messages import get_customer_message


def build_voice_transcription_unclear_response(
    *,
    whatsapp_number: str,
    language: str,
) -> dict[str, Any]:
    """Ask the customer to retry when STT returns no usable transcript."""
    normalized_language = normalize_conversation_language(language)
    persisted_fields = get_accepted_fields(whatsapp_number)
    next_field = get_active_next_field(persisted_fields)
    reply_text = get_customer_message(
        language=normalized_language,
        key="voice_transcription_unclear",
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
        "skip_onboarding_intro": True,
        "is_voice_transcription_unclear": True,
    }
