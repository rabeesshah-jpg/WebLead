"""Stateful WhatsApp qualification conversation flow."""

from __future__ import annotations

from typing import Any, Literal

from apps.qualification.conversation_state import get_accepted_fields, save_accepted_fields
from apps.qualification.domain.language_selection import LANGUAGE_ENGLISH, normalize_conversation_language
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.domain.qualification_questions import get_qualification_question_text
from apps.qualification.domain.confirmation_reply import (
    classify_whatsapp_confirmation_reply,
    normalize_confirmation_message,
)
from apps.qualification.domain.help_commands import is_help_request
from apps.qualification.domain.inbound_message_classification import (
    InboundMessageClassification,
    classify_inbound_message,
    infer_project_type_from_answer,
    is_direct_project_type_answer,
)
from apps.qualification.domain.inbound_message_responses import (
    build_reply_after_field_capture,
    build_rich_inbound_response_metadata,
    build_rich_qualification_reply,
    build_small_talk_reply,
    build_whatsapp_confirmation_rich_reply,
)
from apps.qualification.domain.qualification_field_enrichment import (
    apply_classification_to_fields,
    merge_requirements,
    merge_services_required,
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

VALID_PROJECT_TYPES = frozenset({"new_website", "website_upgrade", "new_and_upgrade"})

REJECTED_FIELD_REASON_CODES = {
    "null value": "value_missing",
    "confidence below threshold": "low_confidence",
}

_CAPTURE_TRANSITION_FIELDS = frozenset(
    {"project_type", "requirements", "referral_source"},
)


def qualification_has_started(fields: dict[str, Any]) -> bool:
    """Return True once any qualification field has been captured."""
    return any(
        (
            _has_project_type(fields),
            _has_requirements(fields),
            _has_referral_source(fields),
            _is_whatsapp_confirmed_resolved(fields),
            _has_preferred_phone(fields),
        )
    )


def _newly_captured_qualification_field(
    before: dict[str, Any],
    after: dict[str, Any],
) -> str | None:
    """Return the last qualification field newly captured between two snapshots."""
    captured: str | None = None
    checks: tuple[tuple[str, Any], ...] = (
        ("project_type", _has_project_type),
        ("requirements", _has_requirements),
        ("referral_source", _has_referral_source),
        ("whatsapp_confirmed", _is_whatsapp_confirmed_resolved),
        ("preferred_phone", _has_preferred_phone),
    )
    for field_name, checker in checks:
        if checker(after) and not checker(before):
            captured = field_name
    return captured


def _should_skip_onboarding_for_turn(
    *,
    persisted_fields: dict[str, Any],
    merged_fields: dict[str, Any],
    captured_field: str | None,
) -> bool:
    """Skip first-contact onboarding once qualification is active or a field was captured."""
    return qualification_has_started(persisted_fields) or captured_field is not None


def _reply_text_for_next_field(
    *,
    language: str,
    next_field: str | None,
    rejected_fields: dict[str, str],
    whatsapp_number: str,
    repeat: bool = False,
) -> str:
    if not next_field:
        return ""
    reason = rejected_fields.get(next_field)
    if next_field == "preferred_phone" and reason and reason != "value_missing":
        return get_customer_message(language=language, key="invalid_phone")
    if reason == "low_confidence":
        return get_customer_message(language=language, key="generic_retry")
    return get_qualification_question_text(
        language=language,
        field=next_field,
        repeat=repeat or bool(reason),
        whatsapp_number=whatsapp_number,
    )


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


def _apply_field_updates(
    merged_fields: dict[str, Any],
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Apply enrichment updates while merging list and text fields."""
    result = dict(merged_fields)
    for field, value in updates.items():
        if field == "services_required":
            result[field] = merge_services_required(
                result.get("services_required"),
                tuple(value),
            )
        elif field == "requirements":
            result[field] = merge_requirements(result.get("requirements"), str(value))
        elif field == "project_type" and not result.get("project_type"):
            result[field] = value
        else:
            result[field] = value
    return result


def try_handle_help_request_turn(
    *,
    whatsapp_number: str,
    message: str,
    language: str = LANGUAGE_ENGLISH,
) -> dict[str, Any] | None:
    """Return full onboarding/help instructions when the customer asks for help."""
    if not is_help_request(message):
        return None

    persisted_fields = get_accepted_fields(whatsapp_number)
    normalized_language = normalize_conversation_language(language)
    intro = get_customer_message(language=normalized_language, key="onboarding_intro")
    next_field = get_active_next_field(persisted_fields)
    if next_field:
        question = get_qualification_question_text(
            language=normalized_language,
            field=next_field,
            repeat=True,
            whatsapp_number=whatsapp_number,
        )
        reply_text = f"{intro}\n\n{question}".strip()
    else:
        reply_text = intro

    status: QualificationStatus = (
        "completed" if is_qualification_complete(persisted_fields) else "in_progress"
    )

    return _with_conversation_language(
        {
            "accepted_fields": dict(persisted_fields),
            "rejected_fields": {},
            "human_handoff_requested": False,
            "next_field": next_field,
            "reply_text": reply_text,
            "qualification_status": status,
            "preferred_phone": persisted_fields.get("preferred_phone"),
            "skip_onboarding_intro": True,
            "classification": ["help_request"],
        },
        language=normalized_language,
    )


def try_handle_small_talk_qualification_turn(
    *,
    whatsapp_number: str,
    message: str,
    language: str = LANGUAGE_ENGLISH,
) -> dict[str, Any] | None:
    """
    Handle greetings, wellbeing, and identity questions without changing state.

    Runs before rich inbound handling so small talk does not break qualification flow.
    """
    persisted_fields = get_accepted_fields(whatsapp_number)
    next_field = get_active_next_field(persisted_fields)
    if not next_field:
        return None

    classification = classify_inbound_message(message)
    if not classification.is_small_talk_or_identity and not classification.role_question:
        return None

    if next_field == "whatsapp_confirmed" and (
        classification.yes_confirmation or classification.no_confirmation
    ):
        return None

    normalized_language = normalize_conversation_language(language)
    reply_text = build_small_talk_reply(
        classification,
        language=normalized_language,
        next_field=next_field,
        whatsapp_number=whatsapp_number,
    )
    return _with_conversation_language(
        {
            "accepted_fields": dict(persisted_fields),
            "rejected_fields": {},
            "human_handoff_requested": False,
            "next_field": next_field,
            "reply_text": reply_text,
            "qualification_status": "in_progress",
            "preferred_phone": persisted_fields.get("preferred_phone"),
            "skip_onboarding_intro": True,
            **build_rich_inbound_response_metadata(
                classification,
                {},
                next_field=next_field,
                complete=False,
            ),
        },
        language=normalized_language,
    )


def _rich_inbound_skip_onboarding(
    classification: InboundMessageClassification,
    *,
    saved_enrichment: bool,
) -> bool:
    """Skip first-contact onboarding only for FAQ-style rich inbound turns."""
    if classification.has_answerable_question:
        return True
    if classification.unsupported_or_unclear_question:
        return True
    if classification.irrelevant_or_unclear and not saved_enrichment:
        return True
    return False


def try_handle_rich_inbound_qualification_turn(
    *,
    whatsapp_number: str,
    message: str,
    language: str = LANGUAGE_ENGLISH,
) -> dict[str, Any] | None:
    """
    Handle services, requirements, and safe FAQ answers before OpenRouter fallback.

    Runs during early qualification steps when the message carries actionable content.
    """
    persisted_fields = get_accepted_fields(whatsapp_number)
    active_field = get_active_next_field(persisted_fields)
    if active_field in {"whatsapp_confirmed", "preferred_phone"}:
        return None

    classification = classify_inbound_message(message)
    if classification.is_small_talk_or_identity or classification.role_question:
        return None
    if classification.yes_confirmation or classification.no_confirmation:
        return None

    normalized_language = normalize_conversation_language(language)

    if active_field == "project_type" and not persisted_fields.get("project_type"):
        project_type_answer = infer_project_type_from_answer(message)
        if project_type_answer and is_direct_project_type_answer(message):
            merged_fields = dict(persisted_fields)
            merged_fields["project_type"] = project_type_answer
            save_accepted_fields(whatsapp_number, merged_fields)
            next_field = _next_missing_field(merged_fields)
            if next_field:
                reply_text = build_reply_after_field_capture(
                    captured_field="project_type",
                    next_field=next_field,
                    language=normalized_language,
                    whatsapp_number=whatsapp_number,
                )
            else:
                reply_text = _completed_reply_text(language=normalized_language)
            return _with_conversation_language(
                {
                    "accepted_fields": merged_fields,
                    "rejected_fields": {},
                    "human_handoff_requested": False,
                    "next_field": next_field,
                    "reply_text": reply_text,
                    "qualification_status": (
                        "completed" if next_field is None else "in_progress"
                    ),
                    "preferred_phone": merged_fields.get("preferred_phone"),
                    "skip_onboarding_intro": True,
                    **build_rich_inbound_response_metadata(
                        classification,
                        {"project_type": project_type_answer},
                        next_field=next_field,
                        complete=next_field is None,
                    ),
                },
                language=normalized_language,
            )

    updates = apply_classification_to_fields(persisted_fields, classification)
    saved_enrichment = bool(updates)
    has_rich_content = (
        saved_enrichment
        or classification.has_user_question
        or classification.unsupported_or_unclear_question
        or classification.irrelevant_or_unclear
    )
    if not has_rich_content:
        return None

    # Irrelevant alone: redirect politely without inventing new field values.
    if classification.irrelevant_or_unclear and not saved_enrichment and not classification.has_user_question:
        merged_fields = dict(persisted_fields)
        next_field = _next_missing_field(merged_fields)
        reply_text = build_rich_qualification_reply(
            classification,
            language=normalized_language,
            saved_enrichment=False,
            next_field=next_field,
            whatsapp_number=whatsapp_number,
            qualification_in_progress=qualification_has_started(merged_fields),
        )
        return _with_conversation_language(
            {
                "accepted_fields": merged_fields,
                "rejected_fields": {},
                "human_handoff_requested": False,
                "next_field": next_field,
                "reply_text": reply_text,
                "qualification_status": "in_progress",
            "preferred_phone": merged_fields.get("preferred_phone"),
            "skip_onboarding_intro": _rich_inbound_skip_onboarding(
                classification,
                saved_enrichment=False,
            ),
            **build_rich_inbound_response_metadata(
                classification,
                {},
                next_field=next_field,
                complete=False,
            ),
        },
        language=normalize_conversation_language(language),
    )

    merged_fields = _apply_field_updates(persisted_fields, updates)
    save_accepted_fields(whatsapp_number, merged_fields)
    next_field = _next_missing_field(merged_fields)
    captured_field = _newly_captured_qualification_field(persisted_fields, merged_fields)

    if _is_qualification_complete(merged_fields):
        return _with_conversation_language(
            {
                "accepted_fields": merged_fields,
                "rejected_fields": {},
                "human_handoff_requested": False,
                "next_field": None,
                "reply_text": _completed_reply_text(language=normalized_language),
                "qualification_status": "completed",
                "preferred_phone": merged_fields.get("preferred_phone"),
                **build_rich_inbound_response_metadata(
                    classification,
                    updates,
                    next_field=None,
                    complete=True,
                ),
            },
            language=normalized_language,
        )

    if (
        captured_field in _CAPTURE_TRANSITION_FIELDS
        and next_field
        and not classification.has_answerable_question
        and not classification.unsupported_or_unclear_question
    ):
        reply_text = build_reply_after_field_capture(
            captured_field=captured_field,
            next_field=next_field,
            language=normalized_language,
            whatsapp_number=whatsapp_number,
        )
    else:
        reply_text = build_rich_qualification_reply(
            classification,
            language=normalized_language,
            saved_enrichment=saved_enrichment,
            next_field=next_field,
            whatsapp_number=whatsapp_number,
            qualification_in_progress=qualification_has_started(merged_fields),
        )
    return _with_conversation_language(
        {
            "accepted_fields": merged_fields,
            "rejected_fields": {},
            "human_handoff_requested": False,
            "next_field": next_field,
            "reply_text": reply_text,
            "qualification_status": "in_progress",
            "preferred_phone": merged_fields.get("preferred_phone"),
            "skip_onboarding_intro": (
                _should_skip_onboarding_for_turn(
                    persisted_fields=persisted_fields,
                    merged_fields=merged_fields,
                    captured_field=captured_field,
                )
                or _rich_inbound_skip_onboarding(
                    classification,
                    saved_enrichment=saved_enrichment,
                )
            ),
            **build_rich_inbound_response_metadata(
                classification,
                updates,
                next_field=next_field,
                complete=False,
            ),
        },
        language=normalized_language,
    )



def _completed_reply_text(*, language: str = LANGUAGE_ENGLISH) -> str:
    """Return interim completion copy; finalize_turn_response replaces this when a link exists."""
    from apps.qualification.domain.booking_completion import (
        build_booking_completion_reply,
    )

    return str(build_booking_completion_reply(language=language)["reply_text"])


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
    for_voice: bool = False,
) -> dict[str, Any] | None:
    """
    High-priority handler while WhatsApp confirmation is the active next field.

    Yes confirms the WhatsApp number and completes qualification. No asks for an
    alternate preferred phone. Any other meaningful reply is saved as requirement
    detail and the confirmation question is re-asked without calling OpenRouter.
    """
    persisted_fields = get_accepted_fields(whatsapp_number)
    if get_active_next_field(persisted_fields) != "whatsapp_confirmed":
        return None

    merged_fields = dict(persisted_fields)
    confirmation_reply = classify_whatsapp_confirmation_reply(message)
    inbound_classification = classify_inbound_message(message)
    normalized_language = normalize_conversation_language(language)

    if confirmation_reply == "yes":
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
                **build_rich_inbound_response_metadata(
                    inbound_classification,
                    {},
                    next_field=None,
                    complete=True,
                ),
            },
            language=normalized_language,
        )

    if confirmation_reply == "no":
        merged_fields["whatsapp_confirmed"] = False
        save_accepted_fields(whatsapp_number, merged_fields)
        return _with_conversation_language(
            {
                "accepted_fields": merged_fields,
                "rejected_fields": {},
                "human_handoff_requested": False,
                "next_field": "preferred_phone",
                "reply_text": get_customer_message(
                    language=normalized_language,
                    key="preferred_phone_after_whatsapp_decline",
                ),
                "qualification_status": "in_progress",
                "preferred_phone": merged_fields.get("preferred_phone"),
            },
            language=normalized_language,
        )

    updates = apply_classification_to_fields(merged_fields, inbound_classification)
    saved_enrichment = bool(updates)
    if saved_enrichment:
        merged_fields = _apply_field_updates(merged_fields, updates)
        save_accepted_fields(whatsapp_number, merged_fields)

    reply_text = build_whatsapp_confirmation_rich_reply(
        inbound_classification,
        language=normalized_language,
        saved_enrichment=saved_enrichment,
        for_voice=for_voice,
    )

    return _with_conversation_language(
        {
            "accepted_fields": merged_fields,
            "rejected_fields": {},
            "human_handoff_requested": False,
            "next_field": "whatsapp_confirmed",
            "reply_text": reply_text,
            "qualification_status": "in_progress",
            "preferred_phone": merged_fields.get("preferred_phone"),
            **build_rich_inbound_response_metadata(
                inbound_classification,
                updates,
                next_field="whatsapp_confirmed",
                complete=False,
            ),
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
    captured_field = _newly_captured_qualification_field(persisted_fields, merged_fields)
    if (
        captured_field in _CAPTURE_TRANSITION_FIELDS
        and next_field
        and captured_field not in rejected_fields
    ):
        reply_text = build_reply_after_field_capture(
            captured_field=captured_field,
            next_field=next_field,
            language=normalized_language,
            whatsapp_number=whatsapp_number,
        )
    else:
        reply_text = _reply_text_for_next_field(
            language=normalized_language,
            next_field=next_field,
            rejected_fields=rejected_fields,
            whatsapp_number=whatsapp_number,
        )
    return _with_conversation_language(
        {
            "accepted_fields": merged_fields,
            "rejected_fields": rejected_fields,
            "human_handoff_requested": False,
            "next_field": next_field,
            "reply_text": reply_text,
            "qualification_status": "in_progress",
            "preferred_phone": merged_fields.get("preferred_phone"),
            "skip_onboarding_intro": _should_skip_onboarding_for_turn(
                persisted_fields=persisted_fields,
                merged_fields=merged_fields,
                captured_field=captured_field,
            ),
        },
        language=normalized_language,
    )
