"""Twilio Content API helper for sending the bilingual language picker."""

from __future__ import annotations

from django.conf import settings
from twilio.rest import Client
from apps.qualification.integrations.twilio_whatsapp_message import (
    format_whatsapp_address,
)


class TwilioLanguagePickerConfigurationError(Exception):
    """Raised when Twilio language-picker settings are incomplete."""


def _validate_send_configuration() -> None:
    if not settings.TWILIO_LANGUAGE_PICKER_CONTENT_SID:
        raise TwilioLanguagePickerConfigurationError(
            "TWILIO_LANGUAGE_PICKER_CONTENT_SID is not configured",
        )
    if not settings.TWILIO_ACCOUNT_SID:
        raise TwilioLanguagePickerConfigurationError("Twilio account SID is not configured")
    if not settings.TWILIO_AUTH_TOKEN:
        raise TwilioLanguagePickerConfigurationError("Twilio auth token is not configured")
    if not settings.TWILIO_WHATSAPP_FROM_NUMBER:
        raise TwilioLanguagePickerConfigurationError(
            "TWILIO_WHATSAPP_FROM_NUMBER is not configured",
        )


def send_language_picker(*, to_number: str) -> str:
    """
    Send the configured Twilio Content language picker to a WhatsApp recipient.

    Returns the Twilio Message SID. Not invoked by inbound webhooks in this phase.
    """
    _validate_send_configuration()
    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    message = client.messages.create(
    from_=settings.TWILIO_WHATSAPP_FROM_NUMBER,
    to=format_whatsapp_address(to_number),
    content_sid=settings.TWILIO_LANGUAGE_PICKER_CONTENT_SID,
)
    return message.sid
