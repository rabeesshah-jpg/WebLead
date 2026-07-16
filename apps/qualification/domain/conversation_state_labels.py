"""Map qualification progress to conversation_state labels for API consumers."""

from __future__ import annotations

from typing import Any

from apps.qualification.conversation_flow import (
    get_active_next_field,
    is_qualification_complete,
)

_CONVERSATION_STATE_BY_FIELD: dict[str, str] = {
    "customer_type": "WAITING_FOR_CUSTOMER_TYPE",
    "referral_source": "WAITING_FOR_REFERRAL_SOURCE",
    "business_type": "WAITING_FOR_BUSINESS_TYPE",
    "website_status": "WAITING_FOR_WEBSITE_STATUS",
    "paid_ads": "WAITING_FOR_PAID_ADS",
    "main_goal": "WAITING_FOR_MAIN_GOAL",
    "launch_timeline": "WAITING_FOR_LAUNCH_TIMELINE",
    "requirements": "WAITING_FOR_REQUIREMENTS",
    "whatsapp_confirmed": "WAITING_FOR_WHATSAPP_CONFIRMATION",
    "preferred_phone": "WAITING_FOR_PREFERRED_PHONE",
}


def resolve_conversation_state_label(
    *,
    accepted_fields: dict[str, Any] | None,
    next_field: str | None = None,
    qualification_status: str | None = None,
    booking_link_sent: bool = False,
) -> str | None:
    """Return a stable conversation_state label for n8n and analytics."""
    fields = accepted_fields if isinstance(accepted_fields, dict) else {}
    if booking_link_sent or qualification_status == "completed":
        return "BOOKING_LINK_SENT"
    active_field = next_field or get_active_next_field(fields)
    if active_field:
        return _CONVERSATION_STATE_BY_FIELD.get(
            active_field,
            f"WAITING_FOR_{active_field.upper()}",
        )
    if is_qualification_complete(fields):
        return "QUALIFICATION_COMPLETE"
    return "WAITING_FOR_CUSTOMER_TYPE"
