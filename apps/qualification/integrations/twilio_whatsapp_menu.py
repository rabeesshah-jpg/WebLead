"""Compatibility re-exports for the WhatsApp main menu (formerly Twilio Content)."""

from apps.whatsapp.config import WahaConfigurationError as TwilioWhatsAppMenuConfigurationError
from apps.whatsapp.message_service import WhatsAppSendError as TwilioWhatsAppMenuSendError
from apps.whatsapp.message_service import send_whatsapp_menu
from apps.qualification.domain.whatsapp_menu_config import MENU_ITEMS

MENU_LIST_PICKER_ITEM_IDS: tuple[str, ...] = tuple(item["id"] for item in MENU_ITEMS)

__all__ = [
    "MENU_LIST_PICKER_ITEM_IDS",
    "TwilioWhatsAppMenuConfigurationError",
    "TwilioWhatsAppMenuSendError",
    "send_whatsapp_menu",
]
