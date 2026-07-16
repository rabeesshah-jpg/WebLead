"""Automatic customer-type resolution from the inbound WhatsApp number.

The bot no longer asks "Are you a new customer or an existing customer?". After
language selection (and on any subsequent turn before customer_type is captured)
the backend automatically resolves the customer type from the inbound WhatsApp
number:

- If the number is detected as an existing/returning customer, set
  ``customer_type = existing_customer`` and run the sync Twilio handoff
  (connecting text → ``time.sleep(5)`` → Noura follow-up). Detection rules
  themselves are unchanged.
- Otherwise the number is treated as a new customer: set
  ``customer_type = new_customer`` and go straight to ``referral_source`` with a
  first-contact intro. The manual customer_type question is never asked.

Existing-customer detection is based only on durable, per-number signals so it
survives Redis restarts and idle resets:

1. lead_record  - a qualified/booked Lead or Customer record (pluggable; none in
   this codebase yet, reserved as the highest-priority source).
2. session      - a durable ``qualified_at`` marker (previous completed
   qualification for this number).
3. booking_link - ``booking_link_sent_at`` is set for this number.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.qualification.api.logging import log_qualification_event
from apps.qualification.conversation_state import get_accepted_fields, save_accepted_fields
from apps.qualification.domain.language_selection import normalize_conversation_language
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.domain.option_template_delivery import (
    WAITING_FOR_BUSINESS_TYPE_STATE,
)
from apps.qualification.domain.qualification_options import (
    CUSTOMER_TYPE_EXISTING,
    CUSTOMER_TYPE_NEW,
)
from apps.qualification.domain.validators import normalize_whatsapp_session_number
from apps.qualification.services.conversation_session_service import (
    get_or_create_conversation_session,
)
from apps.qualification.services.existing_customer_live_agent_service import (
    build_existing_customer_welcome_response,
)

DETECTION_SOURCE_LEAD_RECORD = "lead_record"
DETECTION_SOURCE_SESSION = "session"
DETECTION_SOURCE_BOOKING_LINK = "booking_link"
DETECTION_SOURCE_NONE = "none"


@dataclass(frozen=True)
class ExistingCustomerDetection:
    detected: bool
    source: str


def _detect_from_lead_record(whatsapp_number: str) -> bool:
    """Return whether a qualified/booked Lead/Customer record exists for this number.

    Reserved highest-priority hook. This codebase has no dedicated Lead/Customer
    model yet, so this always returns ``False`` and detection falls through to the
    session-based signals below.
    """
    return False


def detect_existing_customer(whatsapp_number: str) -> ExistingCustomerDetection:
    """Resolve whether a WhatsApp number belongs to an existing customer."""
    canonical_number = normalize_whatsapp_session_number(whatsapp_number)

    if _detect_from_lead_record(canonical_number):
        return ExistingCustomerDetection(True, DETECTION_SOURCE_LEAD_RECORD)

    session, _ = get_or_create_conversation_session(whatsapp_number=canonical_number)
    session.refresh_from_db()

    if session.qualified_at is not None:
        return ExistingCustomerDetection(True, DETECTION_SOURCE_SESSION)

    if session.booking_link_sent_at is not None:
        return ExistingCustomerDetection(True, DETECTION_SOURCE_BOOKING_LINK)

    return ExistingCustomerDetection(False, DETECTION_SOURCE_NONE)


def _persist_customer_type(whatsapp_number: str, customer_type: str) -> dict[str, Any]:
    persisted_fields = get_accepted_fields(whatsapp_number)
    merged_fields = dict(persisted_fields)
    merged_fields["customer_type"] = customer_type
    save_accepted_fields(whatsapp_number, merged_fields)
    return merged_fields


def _build_existing_customer_welcome_turn(
    *,
    whatsapp_number: str,
    language: str,
) -> dict[str, Any]:
    """Prepare existing_customer fields and deliver sync connecting + Noura texts.

    ``customer_type`` is persisted only after a successful handoff so a failed
    connecting send can be retried on the next inbound message.
    """
    normalized_language = normalize_conversation_language(language)
    merged_fields = dict(get_accepted_fields(whatsapp_number))
    merged_fields["customer_type"] = CUSTOMER_TYPE_EXISTING
    return build_existing_customer_welcome_response(
        whatsapp_number=whatsapp_number,
        language=normalized_language,
        accepted_fields=merged_fields,
    )


def _build_new_customer_referral_response(
    *,
    whatsapp_number: str,
    language: str,
) -> dict[str, Any]:
    """Auto-set new_customer and return the first-contact referral_source question."""
    normalized_language = normalize_conversation_language(language)
    merged_fields = _persist_customer_type(whatsapp_number, CUSTOMER_TYPE_NEW)

    return {
        "accepted_fields": merged_fields,
        "rejected_fields": {},
        "human_handoff_requested": False,
        "next_field": "referral_source",
        "reply_text": get_customer_message(
            language=normalized_language,
            key="referral_source_new_customer_intro",
        ),
        "qualification_status": "in_progress",
        "preferred_phone": merged_fields.get("preferred_phone"),
        "skip_onboarding_intro": True,
        "conversation_language": normalized_language,
        # Consumed by channels: speak the first-contact intro on voice turns
        # instead of the default referral_source_voice option copy.
        "option_spoken_message_key": "referral_source_new_customer_intro_voice",
    }


def maybe_auto_detect_existing_customer(
    *,
    whatsapp_number: str,
    language: str,
    input_channel: str | None = None,
) -> dict[str, Any] | None:
    """Resolve customer_type automatically before the customer_type question.

    Returns the sync Twilio handoff payload for existing customers, or the
    referral_source turn for new customers. The manual customer_type question
    is never asked. Returns ``None`` only when ``customer_type`` is already
    captured so the normal step handler can continue.
    """
    canonical_number = normalize_whatsapp_session_number(whatsapp_number)
    persisted_fields = get_accepted_fields(canonical_number)
    if persisted_fields.get("customer_type"):
        return None

    detection = detect_existing_customer(canonical_number)
    normalized_language = normalize_conversation_language(language)

    if detection.detected:
        log_qualification_event(
            "existing_customer_detected",
            whatsapp_number_prefix=canonical_number[:6],
            input_channel=input_channel,
            conversation_language=normalized_language,
            detection_source=detection.source,
        )
        response = _build_existing_customer_welcome_turn(
            whatsapp_number=canonical_number,
            language=normalized_language,
        )
        auto_assigned_customer_type = CUSTOMER_TYPE_EXISTING
        state_after = str(
            response.get("conversation_state") or WAITING_FOR_BUSINESS_TYPE_STATE
        )
    else:
        response = _build_new_customer_referral_response(
            whatsapp_number=canonical_number,
            language=normalized_language,
        )
        auto_assigned_customer_type = CUSTOMER_TYPE_NEW
        state_after = "WAITING_FOR_REFERRAL_SOURCE"

    next_field = response.get("next_field")
    option_template = response.get("option_template")
    if option_template is None and input_channel == "whatsapp_text":
        option_template = next_field if next_field == "referral_source" else None
    log_qualification_event(
        "auto_customer_detection_checked_after_language",
        whatsapp_number_prefix=canonical_number[:6],
        input_channel=input_channel,
        conversation_language=normalized_language,
        existing_customer_detected=detection.detected,
        detection_source=detection.source,
        auto_assigned_customer_type=auto_assigned_customer_type,
        state_before="WAITING_FOR_CUSTOMER_TYPE",
        state_after=state_after,
        next_field=next_field,
        option_template=option_template,
        customer_type=auto_assigned_customer_type,
        existing_customer_followup_scheduled=False,
    )
    return response
