"""Stateful WhatsApp qualification conversation flow."""

from __future__ import annotations

import re
from typing import Any, Literal

from apps.qualification.conversation_state import get_accepted_fields, save_accepted_fields
from apps.qualification.channels import COMPLETION_REPLY_TEXT
from apps.qualification.models import QualificationFieldFilterResult

QualificationStatus = Literal["in_progress", "completed", "human_handoff"]

FIELD_ORDER: tuple[str, ...] = (
    "project_type",
    "requirements",
    "referral_source",
    "whatsapp_confirmed",
    "preferred_phone",
)

QUESTIONS: dict[str, str] = {
    "project_type": "Are you looking for a new website or an upgrade to your existing website?",
    "requirements": "What are you specifically looking for?",
    "referral_source": "Thank you. How did you hear about us?",
    "whatsapp_confirmed": "Thank you. Is this WhatsApp number the best number to reach you?",
    "preferred_phone": "Please share the best phone number to reach you.",
}

VALID_PROJECT_TYPES = frozenset({"new_website", "website_upgrade"})
E164_PHONE_PATTERN = re.compile(r"^\+[1-9][0-9]{7,14}$")

REJECTED_FIELD_REASON_CODES = {
    "null value": "value_missing",
    "confidence below threshold": "low_confidence",
}

WHATSAPP_CONFIRMATION_UNCLEAR_REPLY = (
    "Please reply Yes if this is the best number to reach you, or No if you "
    "would prefer us to use another number."
)

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


def build_completed_retry_response(whatsapp_number: str) -> dict[str, Any]:
    """Return a completed response for an already-finished conversation."""
    merged_fields = get_accepted_fields(whatsapp_number)
    return {
        "accepted_fields": merged_fields,
        "rejected_fields": {},
        "human_handoff_requested": False,
        "next_field": None,
        "reply_text": _completed_reply_text(),
        "qualification_status": "completed",
        "preferred_phone": merged_fields.get("preferred_phone"),
    }


def try_handle_whatsapp_confirmation_turn(
    *,
    whatsapp_number: str,
    message: str,
) -> dict[str, Any] | None:
    """Handle yes/no replies deterministically when whatsapp_confirmed is active."""
    persisted_fields = get_accepted_fields(whatsapp_number)
    if get_active_next_field(persisted_fields) != "whatsapp_confirmed":
        return None

    merged_fields = dict(persisted_fields)
    classification = classify_whatsapp_confirmation_reply(message)

    if classification == "yes":
        merged_fields["whatsapp_confirmed"] = True
        merged_fields["preferred_phone"] = whatsapp_number
        save_accepted_fields(whatsapp_number, merged_fields)
        return {
            "accepted_fields": merged_fields,
            "rejected_fields": {},
            "human_handoff_requested": False,
            "next_field": None,
            "reply_text": _completed_reply_text(),
            "qualification_status": "completed",
            "preferred_phone": whatsapp_number,
        }

    if classification == "no":
        merged_fields["whatsapp_confirmed"] = False
        save_accepted_fields(whatsapp_number, merged_fields)
        return {
            "accepted_fields": merged_fields,
            "rejected_fields": {},
            "human_handoff_requested": False,
            "next_field": "preferred_phone",
            "reply_text": QUESTIONS["preferred_phone"],
            "qualification_status": "in_progress",
            "preferred_phone": merged_fields.get("preferred_phone"),
        }

    return {
        "accepted_fields": merged_fields,
        "rejected_fields": {},
        "human_handoff_requested": False,
        "next_field": "whatsapp_confirmed",
        "reply_text": WHATSAPP_CONFIRMATION_UNCLEAR_REPLY,
        "qualification_status": "in_progress",
        "preferred_phone": merged_fields.get("preferred_phone"),
    }


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
    normalized = "".join(value.split())
    return bool(E164_PHONE_PATTERN.fullmatch(normalized))


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


def _completed_reply_text() -> str:
    return COMPLETION_REPLY_TEXT


def build_turn_response(
    *,
    whatsapp_number: str,
    filter_result: QualificationFieldFilterResult,
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

    if filter_result.human_handoff_requested:
        return {
            "accepted_fields": merged_fields,
            "rejected_fields": rejected_fields,
            "human_handoff_requested": True,
            "next_field": None,
            "reply_text": "Thank you. A team member will follow up with you shortly.",
            "qualification_status": "human_handoff",
            "preferred_phone": merged_fields.get("preferred_phone"),
        }

    if _is_qualification_complete(merged_fields):
        return {
            "accepted_fields": merged_fields,
            "rejected_fields": rejected_fields,
            "human_handoff_requested": False,
            "next_field": None,
            "reply_text": _completed_reply_text(),
            "qualification_status": "completed",
            "preferred_phone": merged_fields.get("preferred_phone"),
        }

    next_field = _next_missing_field(merged_fields)
    return {
        "accepted_fields": merged_fields,
        "rejected_fields": rejected_fields,
        "human_handoff_requested": False,
        "next_field": next_field,
        "reply_text": QUESTIONS[next_field] if next_field else "",
        "qualification_status": "in_progress",
        "preferred_phone": merged_fields.get("preferred_phone"),
    }
