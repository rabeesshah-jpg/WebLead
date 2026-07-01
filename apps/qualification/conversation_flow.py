"""Stateful WhatsApp qualification conversation flow."""

from __future__ import annotations

import re
from typing import Any, Literal

from apps.qualification.conversation_state import get_accepted_fields, save_accepted_fields
from apps.qualification.domain.language_selection import LANGUAGE_ENGLISH, normalize_conversation_language
from apps.qualification.domain.messages import (
    QUESTIONS,
    get_customer_message,
    get_qualification_question,
)
from apps.qualification.domain.validators import (
    collapse_phone_formatting,
    is_valid_e164_phone_number,
)
from apps.qualification.models import QualificationFieldFilterResult

QualificationStatus = Literal["in_progress", "completed", "human_handoff"]

FIELD_ORDER: tuple[str, ...] = (
    "project_type",
    "requirements",
    "referral_source",
    "whatsapp_confirmed",
    "preferred_phone",
)

VALID_PROJECT_TYPES = frozenset({"new_website", "website_upgrade"})

REJECTED_FIELD_REASON_CODES = {
    "null value": "value_missing",
    "confidence below threshold": "low_confidence",
}

_YES_CONFIRMATION_PHRASES: tuple[str, ...] = (
    "yes",
    "y",
    "yep",
    "yeah",
    "yup",
    "correct",
    "sure",
    "okay",
    "ok",
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
    "not this number",
    "no it is not",
    "use another number",
    "different number",
)


def _reply_text_for_next_field(
    *,
    language: str,
    next_field: str | None,
    rejected_fields: dict[str, str],
) -> str:
    if not next_field:
        return ""
    reason = rejected_fields.get(next_field)
    if next_field == "preferred_phone" and reason and reason != "value_missing":
        return get_customer_message(language=language, key="invalid_phone")
    if reason == "low_confidence":
        return get_customer_message(language=language, key="generic_retry")
    return get_qualification_question(language=language, field=next_field)


def _with_conversation_language(
    response: dict[str, Any],
    *,
    language: str,
) -> dict[str, Any]:
    enriched = dict(response)
    enriched["conversation_language"] = normalize_conversation_language(language)
    return enriched


def get_active_next_field(persisted_fields: dict[str, Any]) -> str | None:
    """Return the next unresolved qualification field from persisted state."""
    return _next_missing_field(persisted_fields)


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


def _completed_reply_text(*, language: str = LANGUAGE_ENGLISH) -> str:
    return get_customer_message(language=language, key="completion")


def build_completed_retry_response(
    whatsapp_number: str,
    *,
    language: str = LANGUAGE_ENGLISH,
) -> dict[str, Any]:
    """Return a completed response for an already-finished conversation."""
    merged_fields = get_accepted_fields(whatsapp_number)
    return _with_conversation_language(
        {
            "accepted_fields": merged_fields,
            "rejected_fields": {},
            "human_handoff_requested": False,
            "next_field": None,
            "reply_text": _completed_reply_text(language=language),
            "qualification_status": "completed",
            "preferred_phone": merged_fields.get("preferred_phone"),
        },
        language=language,
    )


def try_handle_whatsapp_confirmation_turn(
    *,
    whatsapp_number: str,
    message: str,
    language: str = LANGUAGE_ENGLISH,
) -> dict[str, Any] | None:
    """Handle yes/no replies deterministically when whatsapp_confirmed is active."""
    persisted_fields = get_accepted_fields(whatsapp_number)
    if get_active_next_field(persisted_fields) != "whatsapp_confirmed":
        return None

    merged_fields = dict(persisted_fields)
    classification = classify_whatsapp_confirmation_reply(message)
    normalized_language = normalize_conversation_language(language)

    if classification == "yes":
        merged_fields["whatsapp_confirmed"] = True
        merged_fields["preferred_phone"] = whatsapp_number
        save_accepted_fields(whatsapp_number, merged_fields)
        return _with_conversation_language(
            {
                "accepted_fields": merged_fields,
                "rejected_fields": {},
                "human_handoff_requested": False,
                "next_field": None,
                "reply_text": _completed_reply_text(language=normalized_language),
                "qualification_status": "completed",
                "preferred_phone": whatsapp_number,
            },
            language=normalized_language,
        )

    if classification == "no":
        merged_fields["whatsapp_confirmed"] = False
        save_accepted_fields(whatsapp_number, merged_fields)
        return _with_conversation_language(
            {
                "accepted_fields": merged_fields,
                "rejected_fields": {},
                "human_handoff_requested": False,
                "next_field": "preferred_phone",
                "reply_text": get_qualification_question(
                    language=normalized_language,
                    field="preferred_phone",
                ),
                "qualification_status": "in_progress",
                "preferred_phone": merged_fields.get("preferred_phone"),
            },
            language=normalized_language,
        )

    return _with_conversation_language(
        {
            "accepted_fields": merged_fields,
            "rejected_fields": {},
            "human_handoff_requested": False,
            "next_field": "whatsapp_confirmed",
            "reply_text": get_customer_message(
                language=normalized_language,
                key="whatsapp_confirmation_unclear",
            ),
            "qualification_status": "in_progress",
            "preferred_phone": merged_fields.get("preferred_phone"),
        },
        language=normalized_language,
    )


def try_handle_preferred_phone_turn(
    *,
    whatsapp_number: str,
    message: str,
    language: str = LANGUAGE_ENGLISH,
) -> dict[str, Any] | None:
    """Accept a direct preferred-phone reply without calling OpenRouter."""
    from apps.qualification.domain.validators import (
        is_direct_phone_reply,
        normalize_preferred_phone_input,
        preferred_phone_reply_needs_openrouter,
    )

    persisted_fields = get_accepted_fields(whatsapp_number)
    if get_active_next_field(persisted_fields) != "preferred_phone":
        return None

    if _has_preferred_phone(persisted_fields):
        return None

    if preferred_phone_reply_needs_openrouter(message):
        return None

    normalized_language = normalize_conversation_language(language)
    normalized_phone = normalize_preferred_phone_input(
        message,
        known_whatsapp_number=whatsapp_number,
    )

    if normalized_phone is None:
        return _with_conversation_language(
            {
                "accepted_fields": dict(persisted_fields),
                "rejected_fields": {"preferred_phone": "invalid_format"},
                "human_handoff_requested": False,
                "next_field": "preferred_phone",
                "reply_text": get_customer_message(
                    language=normalized_language,
                    key="invalid_phone",
                ),
                "qualification_status": "in_progress",
                "preferred_phone": persisted_fields.get("preferred_phone"),
            },
            language=normalized_language,
        )

    merged_fields = dict(persisted_fields)
    merged_fields["preferred_phone"] = normalized_phone
    save_accepted_fields(whatsapp_number, merged_fields)

    return _with_conversation_language(
        {
            "accepted_fields": merged_fields,
            "rejected_fields": {},
            "human_handoff_requested": False,
            "next_field": None,
            "reply_text": _completed_reply_text(language=normalized_language),
            "qualification_status": "completed",
            "preferred_phone": normalized_phone,
        },
        language=normalized_language,
    )


def should_ask_phone_confirmation(persisted_fields: dict[str, Any]) -> bool:
    """Return whether the phone-confirmation question context is active."""
    if not _has_referral_source(persisted_fields):
        return False
    if not _is_whatsapp_confirmed_resolved(persisted_fields):
        return True
    return (
        persisted_fields.get("whatsapp_confirmed") is False
        and not _has_preferred_phone(persisted_fields)
    )


def merge_accepted_fields(
    persisted_fields: dict[str, Any],
    new_accepted_fields: dict[str, Any],
) -> dict[str, Any]:
    """Merge new accepted fields without overwriting previously stored answers."""
    merged = dict(persisted_fields)
    for field, value in new_accepted_fields.items():
        if field not in merged:
            merged[field] = value
    return merged


def apply_preferred_phone_rules(
    accepted_fields: dict[str, Any],
    whatsapp_number: str,
) -> dict[str, Any]:
    """Set preferred_phone from WhatsApp number when the customer confirmed it."""
    if accepted_fields.get("whatsapp_confirmed") is True:
        accepted_fields = dict(accepted_fields)
        accepted_fields["preferred_phone"] = whatsapp_number
    return accepted_fields


def _has_project_type(fields: dict[str, Any]) -> bool:
    return fields.get("project_type") in VALID_PROJECT_TYPES


def _has_requirements(fields: dict[str, Any]) -> bool:
    value = fields.get("requirements")
    return isinstance(value, str) and bool(value.strip())


def _has_referral_source(fields: dict[str, Any]) -> bool:
    value = fields.get("referral_source")
    return isinstance(value, str) and bool(value.strip())


def _is_whatsapp_confirmed_resolved(fields: dict[str, Any]) -> bool:
    value = fields.get("whatsapp_confirmed")
    return isinstance(value, bool)


def _has_preferred_phone(fields: dict[str, Any]) -> bool:
    value = fields.get("preferred_phone")
    if not isinstance(value, str):
        return False
    normalized = collapse_phone_formatting(value)
    return is_valid_e164_phone_number(normalized)


def _next_missing_field(fields: dict[str, Any]) -> str | None:
    if not _has_project_type(fields):
        return "project_type"
    if not _has_requirements(fields):
        return "requirements"
    if not _has_referral_source(fields):
        return "referral_source"
    if not _is_whatsapp_confirmed_resolved(fields):
        return "whatsapp_confirmed"
    if fields.get("whatsapp_confirmed") is False and not _has_preferred_phone(fields):
        return "preferred_phone"
    return None


def _is_qualification_complete(fields: dict[str, Any]) -> bool:
    return _next_missing_field(fields) is None


def is_qualification_complete(persisted_fields: dict[str, Any]) -> bool:
    """Return whether all required qualification fields are stored."""
    return _is_qualification_complete(persisted_fields)


def build_turn_response(
    *,
    whatsapp_number: str,
    filter_result: QualificationFieldFilterResult,
    language: str = LANGUAGE_ENGLISH,
) -> dict[str, Any]:
    """Merge extraction results into conversation state and build the API response."""
    persisted_fields = get_accepted_fields(whatsapp_number)
    merged_fields = merge_accepted_fields(persisted_fields, filter_result.accepted_fields)
    merged_fields = apply_preferred_phone_rules(merged_fields, whatsapp_number)
    save_accepted_fields(whatsapp_number, merged_fields)

    rejected_fields = {
        rejected.field_name: REJECTED_FIELD_REASON_CODES[rejected.reason]
        for rejected in filter_result.rejected_fields
    }
    normalized_language = normalize_conversation_language(language)

    if filter_result.human_handoff_requested:
        return _with_conversation_language(
            {
                "accepted_fields": merged_fields,
                "rejected_fields": rejected_fields,
                "human_handoff_requested": True,
                "next_field": None,
                "reply_text": get_customer_message(
                    language=normalized_language,
                    key="human_handoff",
                ),
                "qualification_status": "human_handoff",
                "preferred_phone": merged_fields.get("preferred_phone"),
            },
            language=normalized_language,
        )

    if _is_qualification_complete(merged_fields):
        return _with_conversation_language(
            {
                "accepted_fields": merged_fields,
                "rejected_fields": rejected_fields,
                "human_handoff_requested": False,
                "next_field": None,
                "reply_text": _completed_reply_text(language=normalized_language),
                "qualification_status": "completed",
                "preferred_phone": merged_fields.get("preferred_phone"),
            },
            language=normalized_language,
        )

    next_field = _next_missing_field(merged_fields)
    return _with_conversation_language(
        {
            "accepted_fields": merged_fields,
            "rejected_fields": rejected_fields,
            "human_handoff_requested": False,
            "next_field": next_field,
            "reply_text": _reply_text_for_next_field(
                language=normalized_language,
                next_field=next_field,
                rejected_fields=rejected_fields,
            ),
            "qualification_status": "in_progress",
            "preferred_phone": merged_fields.get("preferred_phone"),
        },
        language=normalized_language,
    )
