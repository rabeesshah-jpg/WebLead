"""Twilio helper for sending outbound WhatsApp text messages."""

from __future__ import annotations

import json
import logging

from django.conf import settings
from twilio.rest import Client

logger = logging.getLogger("apps.qualification")


class TwilioWhatsAppConfigurationError(Exception):
    """Raised when Twilio WhatsApp send settings are incomplete."""


def _validate_send_configuration() -> None:
    if not settings.TWILIO_ACCOUNT_SID:
        raise TwilioWhatsAppConfigurationError("Twilio account SID is not configured")
    if not settings.TWILIO_AUTH_TOKEN:
        raise TwilioWhatsAppConfigurationError("Twilio auth token is not configured")
    if not settings.TWILIO_WHATSAPP_FROM_NUMBER:
        raise TwilioWhatsAppConfigurationError(
            "TWILIO_WHATSAPP_FROM_NUMBER is not configured",
        )


def format_whatsapp_address(e164_number: str) -> str:
    """Format an E.164 number for Twilio WhatsApp addressing."""
    normalized = "".join(e164_number.split())
    if normalized.startswith("whatsapp:"):
        return normalized
    return f"whatsapp:{normalized}"


def send_whatsapp_text_message(*, to_number: str, body: str) -> str:
    """
    Send a plain-text WhatsApp message via Twilio.

    Returns the Twilio Message SID.
    """
    _validate_send_configuration()
    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    message = client.messages.create(
        from_=settings.TWILIO_WHATSAPP_FROM_NUMBER,
        to=format_whatsapp_address(to_number),
        body=body,
    )
    return message.sid


def send_booking_link_whatsapp_text(
    *,
    to_number: str,
    body: str,
    message_sid: str | None = None,
    input_channel: str | None = None,
) -> str:
    """
    Send the booking-link completion message as a WhatsApp text message.

    Returns the Twilio Message SID.
    """
    twilio_message_sid = send_whatsapp_text_message(to_number=to_number, body=body)
    log_payload: dict[str, object] = {
        "event": "booking_link_whatsapp_text_sent",
        "delivery": "whatsapp_text",
        "twilio_message_sid": twilio_message_sid,
    }
    if message_sid:
        log_payload["message_sid"] = message_sid[:8]
    if input_channel:
        log_payload["input_channel"] = input_channel
    logger.info(json.dumps(log_payload, separators=(",", ":")))
    return twilio_message_sid
