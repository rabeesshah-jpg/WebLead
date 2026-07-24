"""Compatibility re-exports for business-type list picker (formerly Twilio Content)."""

from apps.whatsapp.config import WahaConfigurationError as TwilioBusinessTypePickerConfigurationError
from apps.whatsapp.message_service import WhatsAppSendError as TwilioBusinessTypePickerSendError
from apps.whatsapp.message_service import send_business_type_list_picker


def resolve_business_type_content_sid(language: str) -> str:
    """Legacy helper; Content SIDs are unused under WAHA."""
    del language
    return ""


__all__ = [
    "TwilioBusinessTypePickerConfigurationError",
    "TwilioBusinessTypePickerSendError",
    "resolve_business_type_content_sid",
    "send_business_type_list_picker",
]
