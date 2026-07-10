"""Deliver booking links as WhatsApp text messages with conversation-level idempotency."""

from __future__ import annotations

import logging
from typing import Any, Callable, Literal

from apps.qualification.api.logging import log_qualification_event
from apps.qualification.domain.booking_completion import (
    build_booking_completion_reply,
    build_booking_link_message_body,
    resolve_booking_link,
)
from apps.qualification.domain.language_selection import normalize_conversation_language
from apps.qualification.domain.post_booking_link_response import (
    build_post_booking_link_reply,
)
from apps.qualification.domain.tts_safety import (
    sanitize_spoken_text_for_tts,
    spoken_text_contains_url,
)
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

InputChannel = Literal["whatsapp_text", "whatsapp_voice_note"]

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


def mark_booking_link_sent_for_text_completion(
    *,
    session: WhatsAppConversationSession,
    whatsapp_number: str,
) -> None:
    """Persist booking-link delivery after the URL is included in a text reply."""
    if booking_link_already_sent(session=session):
        return
    mark_booking_link_sent(session)


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
    updated = dict(response_payload)
    language = str(updated.get("conversation_language") or "en")

    if updated.get("spoken_text"):
        updated["spoken_text"] = sanitize_spoken_text_for_tts(
            str(updated["spoken_text"]),
            language=language,
        )
        if spoken_text_contains_url(str(updated["spoken_text"])):
            updated["spoken_text"] = sanitize_spoken_text_for_tts(
                str(updated.get("reply_text") or ""),
                language=language,
            )

    if updated.get("qualification_status") != "completed":
        return updated

    booking_link = resolve_booking_link()
    if booking_link and response_contains_booking_url(updated, booking_link=booking_link):
        updated["booking_link_sent"] = True
        updated["conversation_state"] = updated.get("conversation_state") or "BOOKING_LINK_SENT"
        return updated

    if not updated.get("send_booking_link"):
        return updated

    session, _ = get_or_create_conversation_session(whatsapp_number=whatsapp_number)
    session.refresh_from_db()

    if booking_link_already_sent(session=session):
        log_qualification_event(
            "booking_link_send_blocked",
            whatsapp_number_prefix=whatsapp_number[:6],
            message_sid=message_sid,
            input_channel=input_channel,
            conversation_state=updated.get("conversation_state", "BOOKING_LINK_SENT"),
            booking_link_sent=True,
        )
        updated["send_booking_link"] = False
        updated["booking_link_sent"] = True
        updated["conversation_state"] = "BOOKING_LINK_SENT"
        return updated

    log_qualification_event(
        "attempted_booking_link_send",
        whatsapp_number_prefix=whatsapp_number[:6],
        message_sid=message_sid,
        input_channel=input_channel,
        conversation_state=updated.get("conversation_state"),
        delivery="whatsapp_text",
    )

    if updated.get("booking_link_sent"):
        return updated

    try:
        updated["booking_link_sent"] = deliver_booking_link_whatsapp_text(
            whatsapp_number=whatsapp_number,
            language=language,
            booking_link=updated.get("booking_link"),
            message_sid=message_sid,
            input_channel=input_channel,
        )
        if updated["booking_link_sent"]:
            updated["conversation_state"] = "BOOKING_LINK_SENT"
            updated["send_booking_link"] = False
            log_qualification_event(
                "booking_link_sent",
                whatsapp_number_prefix=whatsapp_number[:6],
                message_sid=message_sid,
                input_channel=input_channel,
                conversation_state="BOOKING_LINK_SENT",
                delivery="whatsapp_text",
                booking_link_sent_after=True,
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


def response_contains_booking_url(
    response_payload: dict[str, Any],
    *,
    booking_link: str | None = None,
) -> bool:
    """Return True when a response field would expose the raw booking URL."""
    link = (booking_link if booking_link is not None else resolve_booking_link()).strip()
    if not link:
        return False
    for key in ("reply_text", "whatsapp_text", "spoken_text"):
        value = str(response_payload.get(key) or "")
        if link in value:
            return True
    return False


def send_booking_link_once(
    *,
    session: WhatsAppConversationSession,
    language: str,
    input_channel: InputChannel,
    user_message: str,
    message_sid: str | None = None,
    whatsapp_number: str | None = None,
) -> dict[str, Any]:
    """
    Apply booking-link idempotency for a completed qualification turn.

    Returns channel-specific reply fields. The raw URL is included in text
    exactly once per session; spoken copy never contains the URL.
    """
    normalized_language = normalize_conversation_language(language)
    booking_link = resolve_booking_link()
    session.refresh_from_db()
    already_sent = booking_link_already_sent(session=session)
    prefix = (whatsapp_number or session.whatsapp_number or "")[:6]

    log_qualification_event(
        "booking_link_send_evaluated",
        whatsapp_number_prefix=prefix,
        message_sid=message_sid,
        input_channel=input_channel,
        booking_link_sent_before=already_sent,
        conversation_state="BOOKING_LINK_SENT" if already_sent else "completed",
    )

    if already_sent:
        reply = build_post_booking_link_reply(
            message=user_message,
            language=normalized_language,
        )
        spoken_text = sanitize_spoken_text_for_tts(reply, language=normalized_language)
        log_qualification_event(
            "booking_link_send_blocked",
            whatsapp_number_prefix=prefix,
            message_sid=message_sid,
            input_channel=input_channel,
            conversation_state="BOOKING_LINK_SENT",
            booking_link_sent=True,
        )
        return {
            "spoken_text": spoken_text,
            "whatsapp_text": reply,
            "reply_text": reply,
            "actions": [],
            "booking_link": booking_link or None,
            "send_booking_link": False,
            "booking_link_sent": True,
            "conversation_state": "BOOKING_LINK_SENT",
            "contains_booking_url": False,
        }

    booking = build_booking_completion_reply(language=normalized_language)
    text_reply = str(booking.get("reply_text") or "")
    spoken_text = sanitize_spoken_text_for_tts(
        str(booking.get("spoken_text") or ""),
        language=normalized_language,
    )
    contains_url = bool(booking_link and booking_link in text_reply)

    if contains_url:
        log_qualification_event(
            "attempted_booking_link_send",
            whatsapp_number_prefix=prefix,
            message_sid=message_sid,
            input_channel=input_channel,
            conversation_state="completed",
            delivery="whatsapp_text_inline",
        )
        mark_booking_link_sent_for_text_completion(
            session=session,
            whatsapp_number=session.whatsapp_number,
        )
        log_qualification_event(
            "booking_link_sent",
            whatsapp_number_prefix=prefix,
            message_sid=message_sid,
            input_channel=input_channel,
            conversation_state="BOOKING_LINK_SENT",
            delivery="whatsapp_text_inline",
            booking_link_sent_after=True,
        )

    return {
        "spoken_text": spoken_text,
        "whatsapp_text": text_reply,
        "reply_text": text_reply,
        "actions": list(booking.get("actions") or []),
        "booking_link": booking.get("booking_link"),
        "send_booking_link": contains_url,
        "booking_link_sent": contains_url,
        "conversation_state": "BOOKING_LINK_SENT" if contains_url else None,
        "contains_booking_url": contains_url,
    }


def clear_booking_link_sent(*, session: WhatsAppConversationSession) -> None:
    """Clear booking-link delivery state when a conversation restarts."""
    if session.booking_link_sent_at is None:
        return
    session.booking_link_sent_at = None
    session.save(update_fields=["booking_link_sent_at"])
