"""Shared option_template delivery contract for Twilio clickable templates via n8n.

New-customer extract turns use ``referral_source`` list pickers. Existing-customer
auto-detection sends connecting + Noura via Twilio, then returns
``option_template=business_type`` in the same HTTP response so n8n can send the
List Picker (Django does not send the picker). Other numbered steps stay plain
text so new-customer behavior after referral is unchanged.
"""

from __future__ import annotations

from typing import Any

from apps.qualification.domain.conversation_state_labels import resolve_conversation_state_label
from apps.qualification.domain.language_selection import normalize_conversation_language
from apps.qualification.domain.numbered_qualification import FIRST_NUMBERED_QUALIFICATION_FIELD
from apps.qualification.domain.validators import normalize_whatsapp_session_number

# Twilio clickable template keys. Values match n8n Switch cases and button capture.
OPTION_TEMPLATE_FIELDS = frozenset({"referral_source", "business_type"})
PROJECT_TYPE_OPTION_TEMPLATE = "project_type"  # retained for legacy log/test references
REFERRAL_SOURCE_OPTION_TEMPLATE = "referral_source"
BUSINESS_TYPE_OPTION_TEMPLATE = FIRST_NUMBERED_QUALIFICATION_FIELD
WAITING_FOR_PROJECT_TYPE_STATE = "WAITING_FOR_PROJECT_TYPE"  # legacy alias
WAITING_FOR_BUSINESS_TYPE_STATE = f"WAITING_FOR_{FIRST_NUMBERED_QUALIFICATION_FIELD.upper()}"


def resolve_option_template(
    *,
    next_field: str | None,
    input_channel: str,
    qualification_status: str | None,
    accepted_fields: dict[str, Any] | None = None,
) -> str | None:
    """
    Return the option_template key n8n should send, or None.

    ``business_type`` clickable templates are only used for existing customers.
    New customers answering ``business_type`` keep numbered plain-text questions.
    """
    if (
        input_channel != "whatsapp_text"
        or qualification_status != "in_progress"
        or next_field not in OPTION_TEMPLATE_FIELDS
    ):
        return None
    if next_field == BUSINESS_TYPE_OPTION_TEMPLATE:
        customer_type = (accepted_fields or {}).get("customer_type")
        if customer_type != "existing_customer":
            return None
    return str(next_field)


def build_option_template_delivery_contract(
    *,
    whatsapp_number: str,
    language: str,
    accepted_fields: dict[str, Any],
    next_field: str,
    input_channel: str = "whatsapp_text",
    event: str = "option_template_delivery",
    source: str | None = None,
    delivery_idempotency_key: str | None = None,
    suppress_plain_text_body: bool = False,
) -> dict[str, Any]:
    """Build the shared outbound contract for an option-template question."""
    normalized_language = normalize_conversation_language(language)
    canonical_number = normalize_whatsapp_session_number(whatsapp_number)
    qualification_status = "in_progress"
    option_template = resolve_option_template(
        next_field=next_field,
        input_channel=input_channel,
        qualification_status=qualification_status,
        accepted_fields=accepted_fields,
    )
    conversation_state = resolve_conversation_state_label(
        accepted_fields=accepted_fields,
        next_field=next_field,
        qualification_status=qualification_status,
    )
    contract: dict[str, Any] = {
        "event": event,
        "whatsapp_number": canonical_number,
        "conversation_language": normalized_language,
        "input_channel": input_channel,
        "qualification_status": qualification_status,
        "next_field": next_field,
        "option_template": option_template,
        "conversation_state": conversation_state,
        "accepted_fields": dict(accepted_fields),
        "rejected_fields": {},
        "human_handoff_requested": False,
        "preferred_phone": accepted_fields.get("preferred_phone"),
        "reply_text": "",
        "whatsapp_text": "",
        "spoken_text": "",
        "should_send_text": False if suppress_plain_text_body else bool(option_template is None),
        "should_send_audio": False,
        "send_booking_link": False,
        "booking_link_sent": False,
        "booking_link": None,
    }
    if source:
        contract["source"] = source
    if delivery_idempotency_key:
        contract["delivery_idempotency_key"] = delivery_idempotency_key
    return contract


def build_project_type_option_template_delivery_contract(
    *,
    whatsapp_number: str,
    language: str,
    accepted_fields: dict[str, Any],
    source: str | None = None,
    delivery_idempotency_key: str | None = None,
    suppress_plain_text_body: bool = True,
) -> dict[str, Any]:
    """Shared project_type clickable-template contract (legacy; unused)."""
    return build_option_template_delivery_contract(
        whatsapp_number=whatsapp_number,
        language=language,
        accepted_fields=accepted_fields,
        next_field=PROJECT_TYPE_OPTION_TEMPLATE,
        input_channel="whatsapp_text",
        event="option_template_delivery",
        source=source,
        delivery_idempotency_key=delivery_idempotency_key,
        suppress_plain_text_body=suppress_plain_text_body,
    )
