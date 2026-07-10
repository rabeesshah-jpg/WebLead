"""Booking completion reply text for qualified leads."""

from __future__ import annotations

from django.conf import settings

from apps.qualification.domain.messages import get_customer_message
from apps.qualification.domain.tts_safety import sanitize_spoken_text_for_tts


def resolve_booking_link() -> str:
    """Return the configured booking URL, or an empty string when unset."""
    return (getattr(settings, "BOOKING_LINK", "") or "").strip()


def build_booking_link_message_body(
    *,
    language: str,
    booking_link: str | None = None,
) -> str | None:
    """Build the WhatsApp text body that contains only the booking link ask."""
    link = (booking_link if booking_link is not None else resolve_booking_link()).strip()
    if not link:
        return None
    return get_customer_message(
        language=language,
        key="completion_with_booking_link",
        booking_link=link,
    )


def build_booking_completion_reply(
    *,
    language: str,
    booking_link: str | None = None,
) -> dict[str, object]:
    """
    Build spoken vs WhatsApp completion fields for a booking-ready turn.

    Always returns:
    - ``spoken_text``: TTS-safe (never contains a URL)
    - ``whatsapp_text``: text body that may include the booking URL
    - ``actions``: empty list reserved for future structured actions

    Callers that still use a single ``reply_text`` should pick spoken or WhatsApp
    copy based on channel in ``finalize_turn_response``.
    """
    link = (booking_link if booking_link is not None else resolve_booking_link()).strip()
    if link:
        spoken_text = sanitize_spoken_text_for_tts(
            get_customer_message(language=language, key="completion_spoken"),
        )
        text_reply = get_customer_message(
            language=language,
            key="completion_with_booking_link",
            booking_link=link,
        )
        whatsapp_text = text_reply
        return {
            "spoken_text": spoken_text,
            "whatsapp_text": whatsapp_text,
            "actions": [],
            "reply_text": text_reply,
            "booking_link_sent": True,
            "send_booking_link": False,
            "booking_link": link,
        }

    pending = get_customer_message(
        language=language,
        key="completion_pending_booking_link",
    )
    return {
        "spoken_text": sanitize_spoken_text_for_tts(pending),
        "whatsapp_text": pending,
        "actions": [],
        "reply_text": pending,
        "booking_link_sent": False,
        "send_booking_link": False,
        "booking_link": None,
    }
