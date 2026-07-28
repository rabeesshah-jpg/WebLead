"""Twilio Content API helper for sending the WhatsApp interactive list-picker menu."""

from __future__ import annotations

import logging

from django.conf import settings
from twilio.rest import Client

from apps.qualification.domain.whatsapp_menu_config import MENU_ITEMS
from apps.qualification.domain.whatsapp_menu_logging import log_whatsapp_menu_event
from apps.qualification.integrations.twilio_whatsapp_message import (
    format_whatsapp_address,
)

logger = logging.getLogger("apps.qualification")

# Twilio list-picker template item IDs must match MENU_ITEMS[].id in whatsapp_menu_config.
MENU_LIST_PICKER_ITEM_IDS: tuple[str, ...] = tuple(item["id"] for item in MENU_ITEMS)


class TwilioWhatsAppMenuConfigurationError(Exception):
    """Raised when Twilio interactive-menu settings are incomplete."""


class TwilioWhatsAppMenuSendError(Exception):
    """Raised when the Twilio Messages API rejects an interactive menu send."""


def _recipient_prefix(to_number: str) -> str:
    stripped = to_number.strip()
    return stripped[:12] if stripped else ""


def _validate_send_configuration() -> str:
    content_sid = getattr(settings, "TWILIO_WHATSAPP_MENU_CONTENT_SID", "") or ""
    if not content_sid:
        raise TwilioWhatsAppMenuConfigurationError(
            "TWILIO_WHATSAPP_MENU_CONTENT_SID is not configured",
        )
    if not settings.TWILIO_ACCOUNT_SID:
        raise TwilioWhatsAppMenuConfigurationError("Twilio account SID is not configured")
    if not settings.TWILIO_AUTH_TOKEN:
        raise TwilioWhatsAppMenuConfigurationError("Twilio auth token is not configured")
    if not settings.TWILIO_WHATSAPP_FROM_NUMBER:
        raise TwilioWhatsAppMenuConfigurationError(
            "TWILIO_WHATSAPP_FROM_NUMBER is not configured",
        )
    return content_sid


def send_whatsapp_menu(*, to_number: str) -> str:
    """
    Send the WhatsApp main menu via Twilio Content API list-picker template.

    Uses ``content_sid=TWILIO_WHATSAPP_MENU_CONTENT_SID`` only. No plain-text body.
    Returns the outbound Twilio Message SID.
    """
    content_sid = _validate_send_configuration()
    recipient_prefix = _recipient_prefix(to_number)
    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    try:
        message = client.messages.create(
        from_=settings.TWILIO_WHATSAPP_FROM_NUMBER,
        to=format_whatsapp_address(to_number),
        content_sid=content_sid,
)
    except Exception as exc:
        log_whatsapp_menu_event(
            "MENU_SEND_FAILED",
            recipient_prefix=recipient_prefix,
            channel="whatsapp",
            error_type=type(exc).__name__,
        )
        raise TwilioWhatsAppMenuSendError("Twilio WhatsApp menu send failed.") from exc

    status = getattr(message, "status", None)
    log_whatsapp_menu_event(
        "MENU_SENT",
        message_sid=message.sid,
        recipient_prefix=recipient_prefix,
        channel="whatsapp",
        status=status,
        content_sid_prefix=content_sid[:8],
    )
    return message.sid
