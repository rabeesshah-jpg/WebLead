"""UltraMsg WhatsApp text message integration."""

from __future__ import annotations

import logging

import requests
from django.conf import settings

from apps.qualification.integrations.twilio_whatsapp_message import (
    TwilioWhatsAppConfigurationError,
)

logger = logging.getLogger("apps.qualification")


class UltraMsgWhatsAppConfigurationError(Exception):
    """Raised when UltraMsg configuration is missing."""


class UltraMsgWhatsAppSendError(Exception):
    """Raised when UltraMsg rejects a message."""


def _validate_configuration() -> None:
    if not settings.ULTRAMSG_INSTANCE_ID:
        raise UltraMsgWhatsAppConfigurationError(
            "ULTRAMSG_INSTANCE_ID is not configured",
        )

    if not settings.ULTRAMSG_TOKEN:
        raise UltraMsgWhatsAppConfigurationError(
            "ULTRAMSG_TOKEN is not configured",
        )

    if not settings.ULTRAMSG_BASE_URL:
        raise UltraMsgWhatsAppConfigurationError(
            "ULTRAMSG_BASE_URL is not configured",
        )


def send_ultramsg_text_message(
    *,
    to_number: str,
    body: str,
) -> str:
    """
    Send plain WhatsApp text message using UltraMsg.
    """

    _validate_configuration()

    url = (
        f"{settings.ULTRAMSG_BASE_URL}/"
        f"{settings.ULTRAMSG_INSTANCE_ID}/messages/chat"
    )

    payload = {
        "token": settings.ULTRAMSG_TOKEN,
        "to": to_number.replace("+", ""),
        "body": body,
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=20,
        )

        response.raise_for_status()

        data = response.json()

    except Exception as exc:
        logger.exception(
            "ultramsg_text_message_failed phone_prefix=%s",
            to_number[:6],
        )
        raise UltraMsgWhatsAppSendError(
            "UltraMsg text message send failed.",
        ) from exc

    message_id = (
        data.get("id")
        or data.get("messageId")
        or "ultramsg_unknown_id"
    )

    logger.info(
        "ultramsg_text_message_sent message_id=%s",
        message_id,
    )

    return str(message_id)