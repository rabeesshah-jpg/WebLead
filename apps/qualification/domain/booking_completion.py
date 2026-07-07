"""Booking completion reply text for qualified leads."""

from __future__ import annotations

from django.conf import settings

from apps.qualification.domain.messages import get_customer_message


def resolve_booking_link() -> str:
    """Return the configured booking URL, or an empty string when unset."""
    return (getattr(settings, "BOOKING_LINK", "") or "").strip()


def build_booking_link_message_body(
    *,
    language: str,
    booking_link: str | None = None,
) -> str | None:
    """Build the WhatsApp text body that contains the clickable booking link."""
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
    Build completion response fields for a booking-ready qualification turn.

    ``reply_text`` is always TTS-safe and excludes the booking URL. The link is
    delivered separately as a WhatsApp text message.
    """
    link = (booking_link if booking_link is not None else resolve_booking_link()).strip()
    if link:
        return {
            "reply_text": get_customer_message(language=language, key="completion"),
            "booking_link_sent": False,
            "send_booking_link": True,
            "booking_link": link,
        }

    return {
        "reply_text": get_customer_message(
            language=language,
            key="completion_pending_booking_link",
        ),
        "booking_link_sent": False,
        "send_booking_link": False,
        "booking_link": None,
    }
