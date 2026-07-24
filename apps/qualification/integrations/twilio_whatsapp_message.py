"""Compatibility re-exports for WhatsApp text sends (formerly Twilio)."""

from apps.whatsapp.message_service import (
    WhatsAppSendError as TwilioWhatsAppConfigurationError,
    send_booking_link_whatsapp_text,
    send_whatsapp_message,
    send_whatsapp_text_message,
)
from apps.whatsapp.config import phone_to_chat_id


def format_whatsapp_address(e164_number: str) -> str:
    """Return a WAHA chatId for the given phone number."""
    return phone_to_chat_id(e164_number)


__all__ = [
    "TwilioWhatsAppConfigurationError",
    "format_whatsapp_address",
    "send_booking_link_whatsapp_text",
    "send_whatsapp_message",
    "send_whatsapp_text_message",
]
