"""Twilio Content API helper for the Business Type list picker."""

from __future__ import annotations

import logging

from django.conf import settings
from twilio.rest import Client

from apps.qualification.domain.language_selection import (
    LANGUAGE_ARABIC,
    normalize_conversation_language,
)
from apps.qualification.integrations.twilio_whatsapp_message import (
    TwilioWhatsAppConfigurationError,
    format_whatsapp_address,
)

logger = logging.getLogger("apps.qualification")

# Defaults match the Twilio Content templates configured for production.
DEFAULT_BUSINESS_TYPE_CONTENT_SID_EN = "HX90d7ec0824c2a0fcc066f69c5696f1cd"
DEFAULT_BUSINESS_TYPE_CONTENT_SID_AR = "HX666fdbe4a262136dfcc820d32e80795f"


class TwilioBusinessTypePickerConfigurationError(TwilioWhatsAppConfigurationError):
    """Raised when Business Type Content SID settings are incomplete."""


class TwilioBusinessTypePickerSendError(Exception):
    """Raised when Twilio rejects a Business Type Content template send."""


def resolve_business_type_content_sid(language: str) -> str:
    """Return the Twilio Content SID for the Business Type list picker."""
    normalized = normalize_conversation_language(language)
    if normalized == LANGUAGE_ARABIC:
        return (
            getattr(settings, "TWILIO_BUSINESS_TYPE_CONTENT_SID_AR", "")
            or DEFAULT_BUSINESS_TYPE_CONTENT_SID_AR
        )
    return (
        getattr(settings, "TWILIO_BUSINESS_TYPE_CONTENT_SID_EN", "")
        or DEFAULT_BUSINESS_TYPE_CONTENT_SID_EN
    )


def _validate_send_configuration(*, language: str) -> str:
    content_sid = resolve_business_type_content_sid(language)
    if not content_sid:
        raise TwilioBusinessTypePickerConfigurationError(
            "Business Type Content SID is not configured",
        )
    if not settings.TWILIO_ACCOUNT_SID:
        raise TwilioBusinessTypePickerConfigurationError(
            "Twilio account SID is not configured",
        )
    if not settings.TWILIO_AUTH_TOKEN:
        raise TwilioBusinessTypePickerConfigurationError(
            "Twilio auth token is not configured",
        )
    if not settings.TWILIO_WHATSAPP_FROM_NUMBER:
        raise TwilioBusinessTypePickerConfigurationError(
            "TWILIO_WHATSAPP_FROM_NUMBER is not configured",
        )
    return content_sid


def send_business_type_list_picker(*, to_number: str, language: str) -> str:
    """
    Send the Business Type WhatsApp list picker via Twilio Content API.

    Sends only ``From``, ``To``, and ``ContentSid`` (no Body / MediaUrl /
    ContentVariables). Returns the Twilio Message SID.
    """
    content_sid = _validate_send_configuration(language=language)
    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    try:
        message = client.messages.create(
            from_=settings.TWILIO_WHATSAPP_FROM_NUMBER,
            to=format_whatsapp_address(to_number),
            content_sid=content_sid,
        )
    except Exception as exc:
        logger.exception(
            "business_type_list_picker_send_failed whatsapp_number_prefix=%s",
            to_number[:6],
        )
        raise TwilioBusinessTypePickerSendError(
            "Twilio Business Type list picker send failed.",
        ) from exc
    return message.sid
