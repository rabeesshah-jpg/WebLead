"""Deliver booking links as WhatsApp text messages with conversation-level idempotency."""

from __future__ import annotations

import logging
from typing import Any, Callable

from apps.qualification.api.logging import log_qualification_event
from apps.qualification.domain.booking_completion import (
    build_booking_link_message_body,
    resolve_booking_link,
)
from apps.qualification.domain.language_selection import normalize_conversation_language
from apps.qualification.integrations.twilio_whatsapp_message import (
    TwilioWhatsAppConfigurationError,
    send_booking_link_whatsapp_text,
)
from apps.qualification.conversation_flow import is_qualification_complete
from apps.qualification.conversation_state import get_accepted_fields
from apps.qualification.models import WhatsAppConversationSession
from apps.qualification.services.conversation_session_service import (
    get_or_create_conversation_session,
    mark_booking_link_sent,
)

BookingLinkSender = Callable[..., str]


class BookingLinkDeliveryError(Exception):
    """Raised when the booking-link WhatsApp message cannot be sent."""


def reconcile_stale_booking_link_sent_state(*, whatsapp_number: str) -> None:
    """
    Clear booking-link delivery flags when a fresh qualification cycle is in progress.

    After ``runserver`` restarts, in-memory conversation state is lost but the DB
    session row may still have ``booking_link_sent_at`` from a prior completed
    conversation. That stale flag must not suppress delivery for the new cycle.
    """
    if is_qualification_complete(get_accepted_fields(whatsapp_number)):
        return

    session, _ = get_or_create_conversation_session(whatsapp_number=whatsapp_number)
    clear_booking_link_sent(session=session)


def clear_booking_link_sent_for_customer(*, whatsapp_number: str) -> None:
    """Clear booking-link delivery state when qualification data is reset."""
    session, _ = get_or_create_conversation_session(whatsapp_number=whatsapp_number)
    clear_booking_link_sent(session=session)


def deliver_booking_link_whatsapp_text(
    *,
    whatsapp_number: str,
    language: str,
    booking_link: str | None = None,
    message_sid: str | None = None,
    input_channel: str | None = None,
    sender: BookingLinkSender | None = None,
) -> bool:
    """
    Send the booking link as a WhatsApp text message exactly once per conversation.

    Returns ``True`` when the link is configured and has been sent (or was sent
    previously for this customer session).
    """
    link = (booking_link if booking_link is not None else resolve_booking_link()).strip()
    if not link:
        return False

    reconcile_stale_booking_link_sent_state(whatsapp_number=whatsapp_number)

    session, _ = get_or_create_conversation_session(whatsapp_number=whatsapp_number)
    session.refresh_from_db()
    if session.booking_link_sent_at is not None:
        log_qualification_event(
            "booking_link_whatsapp_text_duplicate_suppressed",
            whatsapp_number_prefix=whatsapp_number[:6],
            message_sid=message_sid,
            input_channel=input_channel,
        )
        return True

    normalized_language = normalize_conversation_language(language)
    body = build_booking_link_message_body(
        language=normalized_language,
        booking_link=link,
    )
    if not body:
        return False

    send = sender or send_booking_link_whatsapp_text
    try:
        send(
            to_number=whatsapp_number,
            body=body,
            message_sid=message_sid,
            input_channel=input_channel,
        )
    except TwilioWhatsAppConfigurationError as exc:
        log_qualification_event(
            "booking_link_whatsapp_text_unavailable",
            level=logging.ERROR,
            whatsapp_number_prefix=whatsapp_number[:6],
            message_sid=message_sid,
            input_channel=input_channel,
            failure_type=type(exc).__name__,
        )
        raise BookingLinkDeliveryError(str(exc)) from exc
    except Exception as exc:
        log_qualification_event(
            "booking_link_whatsapp_text_failed",
            level=logging.ERROR,
            whatsapp_number_prefix=whatsapp_number[:6],
            message_sid=message_sid,
            input_channel=input_channel,
            failure_type=type(exc).__name__,
        )
        raise BookingLinkDeliveryError("Booking link WhatsApp send failed.") from exc

    mark_booking_link_sent(session)
    log_qualification_event(
        "booking_link_whatsapp_text_delivered",
        whatsapp_number_prefix=whatsapp_number[:6],
        message_sid=message_sid,
        input_channel=input_channel,
        delivery="whatsapp_text",
    )
    return True


def ensure_booking_link_delivery_on_response(
    response_payload: dict[str, Any],
    *,
    whatsapp_number: str,
    message_sid: str | None,
    input_channel: str,
) -> dict[str, Any]:
    """
    Send the booking-link WhatsApp text when a response indicates completion.

    Safe to call on cached/idempotent replays: delivery remains once per session.
    """
    if response_payload.get("qualification_status") != "completed":
        return response_payload
    if not response_payload.get("send_booking_link"):
        return response_payload
    if response_payload.get("booking_link_sent"):
        return response_payload

    updated = dict(response_payload)
    try:
        updated["booking_link_sent"] = deliver_booking_link_whatsapp_text(
            whatsapp_number=whatsapp_number,
            language=str(updated.get("conversation_language") or "en"),
            booking_link=updated.get("booking_link"),
            message_sid=message_sid,
            input_channel=input_channel,
        )
    except BookingLinkDeliveryError as exc:
        updated["booking_link_sent"] = False
        log_qualification_event(
            "booking_link_whatsapp_text_delivery_skipped",
            level=logging.ERROR,
            message_sid=message_sid,
            input_channel=input_channel,
            failure_type=type(exc).__name__,
        )
    return updated


def booking_link_already_sent(*, session: WhatsAppConversationSession) -> bool:
    """Return whether this conversation already received a booking-link text."""
    return session.booking_link_sent_at is not None


def clear_booking_link_sent(*, session: WhatsAppConversationSession) -> None:
    """Clear booking-link delivery state when a conversation restarts."""
    if session.booking_link_sent_at is None:
        return
    session.booking_link_sent_at = None
    session.save(update_fields=["booking_link_sent_at"])
