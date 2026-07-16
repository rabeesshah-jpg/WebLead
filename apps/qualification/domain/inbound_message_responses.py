"""Compose customer replies from inbound message classification."""

from __future__ import annotations

from typing import Any

from apps.qualification.domain.inbound_message_classification import (
    InboundMessageClassification,
    classification_labels,
)
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.domain.qualification_faq import build_faq_answer
from apps.qualification.domain.qualification_questions import get_qualification_question_text


def _confirmation_also_reask_key(*, for_voice: bool) -> str:
    if for_voice:
        return "whatsapp_confirmation_also_reask_voice"
    return "whatsapp_confirmation_also_reask"


def _confirmation_noted_reask_key(*, for_voice: bool) -> str:
    if for_voice:
        return "whatsapp_confirmation_noted_reask_voice"
    return "whatsapp_confirmation_noted_reask"


def build_rich_inbound_response_metadata(
    classification: InboundMessageClassification,
    updates: dict[str, Any],
    *,
    next_field: str | None,
    complete: bool,
) -> dict[str, Any]:
    """Attach structured rich-handler fields to an extract turn response."""
    saved_services = list(classification.service_tokens)
    saved_requirements: list[str] = []
    if "requirements" in updates and classification.raw_message:
        saved_requirements = [classification.raw_message]
    return {
        "classification": classification_labels(classification),
        "saved_services": saved_services,
        "saved_requirements": saved_requirements,
        "next_required_field": next_field,
        "complete": complete,
    }


def build_whatsapp_confirmation_rich_reply(
    classification: InboundMessageClassification,
    *,
    language: str,
    saved_enrichment: bool,
    for_voice: bool = False,
) -> str:
    """Build a confirmation-window reply that answers questions and re-asks confirmation."""
    also_reask = get_customer_message(
        language=language,
        key=_confirmation_also_reask_key(for_voice=for_voice),
    )
    noted_reask = get_customer_message(
        language=language,
        key=_confirmation_noted_reask_key(for_voice=for_voice),
    )

    if classification.has_user_question or (
        classification.irrelevant_or_unclear and not saved_enrichment
    ):
        parts: list[str] = []
        faq_answer = build_faq_answer(classification, language=language)
        if faq_answer:
            parts.append(faq_answer)
        if classification.unsupported_or_unclear_question:
            parts.append(get_customer_message(language=language, key="faq_unsupported"))
        if classification.irrelevant_or_unclear and not faq_answer:
            parts.append(get_customer_message(language=language, key="irrelevant_redirect"))
        if saved_enrichment:
            parts.append(
                get_customer_message(language=language, key="requirement_acknowledged")
            )
        parts.append(also_reask)
        return " ".join(parts)

    if saved_enrichment:
        return noted_reask

    if classification.irrelevant_or_unclear:
        return " ".join(
            [
                get_customer_message(language=language, key="irrelevant_redirect"),
                also_reask,
            ]
        )

    return get_customer_message(language=language, key="whatsapp_confirmation_unclear")


def _persona_reply_part(classification: InboundMessageClassification, *, language: str) -> str:
    if classification.about_yourself_question:
        return get_customer_message(language=language, key="small_talk_about")
    if classification.identity_question:
        return get_customer_message(language=language, key="small_talk_identity")
    if classification.role_question:
        if classification.role_question_kind == "what_do_you_do":
            return get_customer_message(language=language, key="small_talk_role_alt")
        return get_customer_message(language=language, key="small_talk_role")
    if classification.small_talk_greeting and classification.small_talk_wellbeing:
        return get_customer_message(language=language, key="small_talk_greeting_wellbeing")
    if classification.small_talk_wellbeing:
        return get_customer_message(language=language, key="small_talk_wellbeing")
    if classification.small_talk_greeting:
        return get_customer_message(language=language, key="small_talk_greeting")
    return ""


def build_small_talk_reply(
    classification: InboundMessageClassification,
    *,
    language: str,
    next_field: str | None,
    whatsapp_number: str,
) -> str:
    """Build a friendly persona reply that continues the current qualification question."""
    parts: list[str] = []
    persona_part = _persona_reply_part(classification, language=language)
    if persona_part:
        parts.append(persona_part)

    if next_field:
        parts.append(
            get_qualification_question_text(
                language=language,
                field=next_field,
                repeat=True,
                whatsapp_number=whatsapp_number,
            )
        )
    return " ".join(parts)


_CAPTURE_TRANSITION_KEYS: dict[str, str] = {
    "customer_type": "after_customer_type_captured",
    "referral_source": "after_referral_source_captured",
    "business_type": "after_numbered_option_captured",
    "website_status": "after_numbered_option_captured",
    "paid_ads": "after_numbered_option_captured",
    "main_goal": "after_numbered_option_captured",
    "launch_timeline": "after_numbered_option_captured",
}


def build_reply_after_field_capture(
    *,
    captured_field: str,
    next_field: str,
    language: str,
    whatsapp_number: str,
) -> str:
    """Build a short acknowledgment plus the next qualification question."""
    transition_key = _CAPTURE_TRANSITION_KEYS.get(captured_field)
    question = get_qualification_question_text(
        language=language,
        field=next_field,
        repeat=False,
        whatsapp_number=whatsapp_number,
    )
    if transition_key:
        transition = get_customer_message(language=language, key=transition_key)
        return f"{transition} {question}"
    return question


def build_rich_qualification_reply(
    classification: InboundMessageClassification,
    *,
    language: str,
    saved_enrichment: bool,
    next_field: str | None,
    whatsapp_number: str | None = None,
    qualification_in_progress: bool = False,
) -> str:
    """Build an in-progress qualification reply before falling back to OpenRouter."""
    if classification.irrelevant_or_unclear and not saved_enrichment and not classification.has_user_question:
        parts: list[str] = []
        if not qualification_in_progress:
            parts.append(
                get_customer_message(language=language, key="irrelevant_redirect"),
            )
        if next_field:
            parts.append(
                get_qualification_question_text(
                    language=language,
                    field=next_field,
                    repeat=True,
                    whatsapp_number=whatsapp_number,
                )
            )
        return " ".join(parts)

    parts: list[str] = []
    faq_answer = build_faq_answer(classification, language=language)
    if faq_answer:
        parts.append(faq_answer)
    if saved_enrichment:
        parts.append(
            get_customer_message(language=language, key="requirement_acknowledged")
        )
    if classification.unsupported_or_unclear_question:
        parts.append(get_customer_message(language=language, key="faq_unsupported"))
    if next_field:
        parts.append(
            get_qualification_question_text(
                language=language,
                field=next_field,
                repeat=True,
                whatsapp_number=whatsapp_number,
            )
        )
    if parts:
        return " ".join(parts)
    return get_customer_message(language=language, key="generic_retry")
