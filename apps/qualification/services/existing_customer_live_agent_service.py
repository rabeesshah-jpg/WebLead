"""Existing-customer handoff: connecting text, synchronous wait, then Noura + picker.

Flow (automatic detection only; no Celery / Redis / Timer):

1. Send connecting WhatsApp text via WAHA.
2. ``time.sleep(5)`` so the first message can be seen before the follow-up.
3. Send the Noura welcome follow-up via WAHA.
4. Send the Business Type list via WAHA and return ``option_template=business_type``
   so n8n does not also send a template.
5. Persist ``existing_customer_followup_sent`` / session markers once.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.qualification.api.logging import log_qualification_event
from apps.qualification.conversation_state import get_accepted_fields, save_accepted_fields
from apps.qualification.domain.language_selection import normalize_conversation_language
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.domain.numbered_qualification import FIRST_NUMBERED_QUALIFICATION_FIELD
from apps.qualification.domain.option_template_delivery import (
    WAITING_FOR_BUSINESS_TYPE_STATE,
)
from apps.qualification.domain.validators import normalize_whatsapp_session_number
from apps.qualification.integrations.twilio_whatsapp_message import (
    send_whatsapp_text_message,
)
from apps.qualification.services.conversation_session_service import (
    claim_existing_customer_connecting,
    claim_existing_customer_followup_send,
    claim_existing_customer_noura_send,
    clear_existing_customer_live_agent_state,
    get_or_create_conversation_session,
)

logger = logging.getLogger("apps.qualification")

EXISTING_CUSTOMER_CONNECTING_KEY = "existing_customer_connecting"
EXISTING_CUSTOMER_NOURA_FOLLOWUP_KEY = "existing_customer_noura_followup"
EXISTING_CUSTOMER_FOLLOWUP_DELAY_SECONDS = 5
EXISTING_CUSTOMER_HANDED_OFF_STATE = "EXISTING_CUSTOMER_NOURA_SENT"
SOURCE_SYNC_TWILIO_HANDOFF = "existing_customer_sync_twilio_handoff"
BUSINESS_TYPE_OPTION_TEMPLATE = FIRST_NUMBERED_QUALIFICATION_FIELD

# Backward-compat aliases used by older imports / logs.
WAITING_FOR_LIVE_AGENT_STATE = "WAITING_FOR_LIVE_AGENT"
EXISTING_CUSTOMER_LIVE_AGENT_FIELD = "existing_customer_live_agent"
EXISTING_CUSTOMER_WELCOME_KEY = "existing_customer_welcome_back"
EXISTING_CUSTOMER_WELCOME_VOICE_KEY = "existing_customer_welcome_back_voice"


class ExistingCustomerHandoffError(Exception):
    """Controlled failure while delivering the existing-customer WhatsApp handoff."""


def reconcile_stale_existing_customer_delivery_markers(*, whatsapp_number: str) -> None:
    """
    Clear delivery markers that outlived lost in-progress qualification fields.

    After a process restart with an empty overlay and empty durable
    ``accepted_fields``, leftover connecting/noura/followup timestamps must not
    suppress a fresh existing-customer handoff.
    """
    canonical_number = normalize_whatsapp_session_number(whatsapp_number)
    fields = get_accepted_fields(canonical_number)
    if fields:
        return
    session, _ = get_or_create_conversation_session(whatsapp_number=canonical_number)
    session.refresh_from_db()
    if (
        session.existing_customer_connecting_sent_at is None
        and session.existing_customer_noura_sent_at is None
        and session.existing_customer_followup_sent_at is None
        and session.existing_customer_business_type_picker_sent_at is None
        and session.existing_customer_followup_due_at is None
    ):
        return
    log_qualification_event(
        "existing_customer_stale_delivery_markers_reconciled",
        whatsapp_number_prefix=canonical_number[:6],
        conversation_cycle=session.conversation_cycle,
        source=SOURCE_SYNC_TWILIO_HANDOFF,
    )
    clear_existing_customer_live_agent_state(session)


def _release_connecting_claim(session) -> None:
    """Clear connecting markers so a failed first send can retry later."""
    with transaction.atomic():
        locked = type(session).objects.select_for_update().get(pk=session.pk)
        locked.existing_customer_connecting_sent_at = None
        locked.existing_customer_followup_due_at = None
        locked.save(
            update_fields=[
                "existing_customer_connecting_sent_at",
                "existing_customer_followup_due_at",
            ],
        )
    session.refresh_from_db()


def _release_noura_claim(session) -> None:
    """Clear Noura marker so a failed follow-up send can retry without resending connecting."""
    with transaction.atomic():
        locked = type(session).objects.select_for_update().get(pk=session.pk)
        locked.existing_customer_noura_sent_at = None
        locked.save(update_fields=["existing_customer_noura_sent_at"])
    session.refresh_from_db()


def _business_type_picker_response(
    *,
    accepted_fields: dict[str, Any],
    language: str,
    duplicate_suppressed: bool = False,
    whatsapp_number: str | None = None,
) -> dict[str, Any]:
    """
    Response after connecting + Noura texts; Django sends the business_type list via WAHA.

    Empty reply_text so n8n does not send numbered Body text; list picker only.
    """
    fields = dict(accepted_fields)
    fields["customer_type"] = "existing_customer"
    fields["qualification_step"] = BUSINESS_TYPE_OPTION_TEMPLATE
    fields["qualification_complete"] = False
    fields["existing_customer_followup_sent"] = True
    if whatsapp_number and not duplicate_suppressed:
        try:
            from apps.whatsapp.message_service import send_business_type_list

            send_business_type_list(to_number=whatsapp_number, language=language)
        except Exception:  # noqa: BLE001
            log_qualification_event(
                "existing_customer_business_type_waha_send_failed",
                level=logging.ERROR,
                whatsapp_number_prefix=whatsapp_number[:6],
                conversation_language=language,
            )
    return {
        "accepted_fields": fields,
        "rejected_fields": {},
        "human_handoff_requested": False,
        "next_field": BUSINESS_TYPE_OPTION_TEMPLATE,
        "reply_text": "",
        "whatsapp_text": "",
        "qualification_status": "in_progress",
        "preferred_phone": fields.get("preferred_phone"),
        "skip_onboarding_intro": True,
        "conversation_language": language,
        "conversation_state": WAITING_FOR_BUSINESS_TYPE_STATE,
        "option_template": BUSINESS_TYPE_OPTION_TEMPLATE,
        "business_type_content_sid": None,
        "qualification_step": BUSINESS_TYPE_OPTION_TEMPLATE,
        "qualification_complete": False,
        "should_send_qualification_question": True,
        "should_send_text": False,
        "should_send_audio": False,
        "existing_customer_followup_scheduled": False,
        "followup_delay_seconds": EXISTING_CUSTOMER_FOLLOWUP_DELAY_SECONDS,
        "existing_customer_followup_sent": True,
        "duplicate_detected": duplicate_suppressed,
    }


def _waiting_response(
    *,
    accepted_fields: dict[str, Any],
    language: str,
    duplicate_suppressed: bool = False,
) -> dict[str, Any]:
    """Controlled quiet response while a concurrent handoff owns delivery."""
    return {
        "accepted_fields": dict(accepted_fields),
        "rejected_fields": {},
        "human_handoff_requested": False,
        "next_field": None,
        "reply_text": "",
        "whatsapp_text": "",
        "qualification_status": "in_progress",
        "preferred_phone": accepted_fields.get("preferred_phone"),
        "skip_onboarding_intro": True,
        "conversation_language": language,
        "conversation_state": WAITING_FOR_LIVE_AGENT_STATE,
        "option_template": None,
        "qualification_step": None,
        "qualification_complete": False,
        "should_send_qualification_question": False,
        "should_send_text": False,
        "should_send_audio": False,
        "existing_customer_followup_scheduled": False,
        "followup_delay_seconds": EXISTING_CUSTOMER_FOLLOWUP_DELAY_SECONDS,
        "existing_customer_followup_sent": bool(
            accepted_fields.get("existing_customer_followup_sent")
        ),
        "duplicate_detected": duplicate_suppressed,
    }


def _persist_followup_accepted_fields(
    whatsapp_number: str,
    accepted_fields: dict[str, Any],
) -> dict[str, Any]:
    fields = dict(accepted_fields)
    fields["customer_type"] = "existing_customer"
    fields.pop(EXISTING_CUSTOMER_LIVE_AGENT_FIELD, None)
    fields["existing_customer_followup_sent"] = True
    fields["qualification_step"] = BUSINESS_TYPE_OPTION_TEMPLATE
    fields["qualification_complete"] = False
    save_accepted_fields(whatsapp_number, fields)
    return fields


def _send_noura_followup(
    *,
    canonical_number: str,
    normalized_language: str,
    fields: dict[str, Any],
    session,
    already_claimed_noura: bool = False,
) -> dict[str, Any]:
    """Send the Noura WhatsApp text once connecting has already succeeded."""
    if not already_claimed_noura:
        session, claimed = claim_existing_customer_noura_send(session)
        if not claimed:
            session.refresh_from_db()
            if session.existing_customer_followup_sent_at is not None:
                persisted = get_accepted_fields(canonical_number)
                if not persisted.get("existing_customer_followup_sent"):
                    persisted = _persist_followup_accepted_fields(
                        canonical_number, persisted
                    )
                return _business_type_picker_response(
                    accepted_fields=persisted,
                    language=normalized_language,
                    duplicate_suppressed=True,
                    whatsapp_number=canonical_number,
                )
            log_qualification_event(
                "existing_customer_duplicate_flow_suppressed",
                whatsapp_number_prefix=canonical_number[:6],
                conversation_language=normalized_language,
                reason="noura_already_claimed",
                source=SOURCE_SYNC_TWILIO_HANDOFF,
            )
            return _waiting_response(
                accepted_fields=get_accepted_fields(canonical_number),
                language=normalized_language,
                duplicate_suppressed=True,
            )

    noura_body = get_customer_message(
        language=normalized_language,
        key=EXISTING_CUSTOMER_NOURA_FOLLOWUP_KEY,
    )
    try:
        followup_sid = send_whatsapp_text_message(
            to_number=canonical_number,
            body=noura_body,
        )
    except Exception as exc:
        log_qualification_event(
            "existing_customer_twilio_send_failure",
            level=logging.ERROR,
            whatsapp_number_prefix=canonical_number[:6],
            conversation_language=normalized_language,
            stage="noura_followup",
            failure_type=type(exc).__name__,
            source=SOURCE_SYNC_TWILIO_HANDOFF,
        )
        _release_noura_claim(session)
        raise ExistingCustomerHandoffError(
            "Failed to send existing-customer Noura follow-up"
        ) from exc

    if not followup_sid:
        log_qualification_event(
            "existing_customer_twilio_send_failure",
            level=logging.ERROR,
            whatsapp_number_prefix=canonical_number[:6],
            conversation_language=normalized_language,
            stage="noura_followup",
            failure_type="empty_message_sid",
            source=SOURCE_SYNC_TWILIO_HANDOFF,
        )
        _release_noura_claim(session)
        raise ExistingCustomerHandoffError(
            "Failed to send existing-customer Noura follow-up"
        )

    session.refresh_from_db()
    session, _ = claim_existing_customer_followup_send(session)
    persisted = _persist_followup_accepted_fields(canonical_number, fields)

    log_qualification_event(
        "existing_customer_noura_followup_sent",
        whatsapp_number_prefix=canonical_number[:6],
        conversation_language=normalized_language,
        twilio_message_sid=followup_sid,
        followup_sent_at=timezone.now().isoformat(),
        source=SOURCE_SYNC_TWILIO_HANDOFF,
    )
    return _business_type_picker_response(
        accepted_fields=persisted,
        language=normalized_language,
        whatsapp_number=canonical_number,
    )


def build_existing_customer_welcome_response(
    *,
    whatsapp_number: str,
    language: str,
    accepted_fields: dict[str, Any],
) -> dict[str, Any]:
    """
    Deliver connecting + Noura WhatsApp texts, then return Business Type picker trigger.

    Uses ``send_whatsapp_text_message`` twice with ``time.sleep(5)`` between them.
    Does not schedule Celery/Redis tasks. n8n alone sends the List Picker.
    """
    canonical_number = normalize_whatsapp_session_number(whatsapp_number)
    normalized_language = normalize_conversation_language(language)
    fields = dict(accepted_fields)
    fields["customer_type"] = "existing_customer"
    fields.pop(EXISTING_CUSTOMER_LIVE_AGENT_FIELD, None)

    session, _ = get_or_create_conversation_session(whatsapp_number=canonical_number)
    session.refresh_from_db()

    if session.existing_customer_followup_sent_at is not None:
        log_qualification_event(
            "existing_customer_duplicate_flow_suppressed",
            whatsapp_number_prefix=canonical_number[:6],
            conversation_language=normalized_language,
            reason="followup_already_sent",
            source=SOURCE_SYNC_TWILIO_HANDOFF,
        )
        persisted = get_accepted_fields(canonical_number)
        if not persisted.get("existing_customer_followup_sent"):
            persisted = _persist_followup_accepted_fields(canonical_number, persisted)
        # Re-emit picker trigger only (no Twilio resend) so n8n can deliver it.
        return _business_type_picker_response(
            accepted_fields=persisted,
            language=normalized_language,
            duplicate_suppressed=True,
        )

    session, claimed = claim_existing_customer_connecting(
        session,
        followup_delay_seconds=EXISTING_CUSTOMER_FOLLOWUP_DELAY_SECONDS,
    )
    if not claimed:
        session.refresh_from_db()
        if (
            session.existing_customer_connecting_sent_at is not None
            and session.existing_customer_followup_sent_at is None
            and session.existing_customer_noura_sent_at is None
        ):
            return _send_noura_followup(
                canonical_number=canonical_number,
                normalized_language=normalized_language,
                fields=fields,
                session=session,
            )
        log_qualification_event(
            "existing_customer_duplicate_flow_suppressed",
            whatsapp_number_prefix=canonical_number[:6],
            conversation_language=normalized_language,
            reason="connecting_already_claimed",
            source=SOURCE_SYNC_TWILIO_HANDOFF,
        )
        return _waiting_response(
            accepted_fields=get_accepted_fields(canonical_number),
            language=normalized_language,
            duplicate_suppressed=True,
        )

    log_qualification_event(
        "existing_customer_detected_handoff_started",
        whatsapp_number_prefix=canonical_number[:6],
        conversation_language=normalized_language,
        source=SOURCE_SYNC_TWILIO_HANDOFF,
        followup_delay_seconds=EXISTING_CUSTOMER_FOLLOWUP_DELAY_SECONDS,
        conversation_cycle=session.conversation_cycle,
    )

    connecting_body = get_customer_message(
        language=normalized_language,
        key=EXISTING_CUSTOMER_CONNECTING_KEY,
    )
    try:
        connecting_sid = send_whatsapp_text_message(
            to_number=canonical_number,
            body=connecting_body,
        )
    except Exception as exc:
        log_qualification_event(
            "existing_customer_twilio_send_failure",
            level=logging.ERROR,
            whatsapp_number_prefix=canonical_number[:6],
            conversation_language=normalized_language,
            stage="connecting",
            failure_type=type(exc).__name__,
            source=SOURCE_SYNC_TWILIO_HANDOFF,
        )
        _release_connecting_claim(session)
        raise ExistingCustomerHandoffError(
            "Failed to send existing-customer connecting message"
        ) from exc

    if not connecting_sid:
        log_qualification_event(
            "existing_customer_twilio_send_failure",
            level=logging.ERROR,
            whatsapp_number_prefix=canonical_number[:6],
            conversation_language=normalized_language,
            stage="connecting",
            failure_type="empty_message_sid",
            source=SOURCE_SYNC_TWILIO_HANDOFF,
        )
        _release_connecting_claim(session)
        raise ExistingCustomerHandoffError(
            "Failed to send existing-customer connecting message"
        )

    log_qualification_event(
        "existing_customer_connecting_message_sent",
        whatsapp_number_prefix=canonical_number[:6],
        conversation_language=normalized_language,
        twilio_message_sid=connecting_sid,
        source=SOURCE_SYNC_TWILIO_HANDOFF,
    )

    session, claimed_noura = claim_existing_customer_noura_send(session)
    if not claimed_noura:
        log_qualification_event(
            "existing_customer_duplicate_flow_suppressed",
            whatsapp_number_prefix=canonical_number[:6],
            conversation_language=normalized_language,
            reason="noura_already_claimed",
            source=SOURCE_SYNC_TWILIO_HANDOFF,
        )
        return _waiting_response(
            accepted_fields=get_accepted_fields(canonical_number),
            language=normalized_language,
            duplicate_suppressed=True,
        )

    log_qualification_event(
        "existing_customer_five_second_sleep_started",
        whatsapp_number_prefix=canonical_number[:6],
        conversation_language=normalized_language,
        sleep_seconds=EXISTING_CUSTOMER_FOLLOWUP_DELAY_SECONDS,
        source=SOURCE_SYNC_TWILIO_HANDOFF,
    )
    time.sleep(EXISTING_CUSTOMER_FOLLOWUP_DELAY_SECONDS)
    log_qualification_event(
        "existing_customer_five_second_sleep_completed",
        whatsapp_number_prefix=canonical_number[:6],
        conversation_language=normalized_language,
        sleep_seconds=EXISTING_CUSTOMER_FOLLOWUP_DELAY_SECONDS,
        source=SOURCE_SYNC_TWILIO_HANDOFF,
    )

    return _send_noura_followup(
        canonical_number=canonical_number,
        normalized_language=normalized_language,
        fields=fields,
        session=session,
        already_claimed_noura=True,
    )


def maybe_handle_existing_customer_live_agent_turn(
    *,
    whatsapp_number: str,
    language: str,
    message: str | None = None,
) -> dict[str, Any] | None:
    """No mid-wait gate — handoff completes in the detection turn via time.sleep."""
    del whatsapp_number, language, message
    return None


def is_waiting_for_existing_customer_live_agent(whatsapp_number: str) -> bool:
    """Retired wait state — handoff no longer pauses for a later inbound message."""
    del whatsapp_number
    return False
