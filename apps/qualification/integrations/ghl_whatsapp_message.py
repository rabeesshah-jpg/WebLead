"""
GoHighLevel WhatsApp messaging integration.
"""

from __future__ import annotations

import logging
import requests
from django.conf import settings


logger = logging.getLogger("apps.whatsapp")


class GHLWhatsAppConfigurationError(Exception):
    """Raised when GHL WhatsApp configuration is missing."""


def send_ghl_text_message(
    *,
    to_number: str,
    body: str,
) -> str:
    """
    Send WhatsApp text message through GoHighLevel.
    """

    api_key = getattr(settings, "GHL_API_KEY", "")
    location_id = getattr(settings, "GHL_LOCATION_ID", "")


    if not api_key or not location_id:
        raise GHLWhatsAppConfigurationError(
            "Missing GHL_API_KEY or GHL_LOCATION_ID"
        )


    url = (
        "https://services.leadconnectorhq.com/"
        "conversations/messages"
    )


    payload = {
        "type": "WhatsApp",
        "phone": to_number,
        "message": body,
    }


    headers = {
        "Authorization": f"Bearer {api_key}",
        "Version": "2021-07-28",
        "Content-Type": "application/json",
    }


    response = requests.post(
        url,
        json=payload,
        headers=headers,
        timeout=20,
    )


    if response.status_code >= 400:
        logger.error(
            "ghl_message_failed status=%s body=%s",
            response.status_code,
            response.text,
        )

        raise GHLWhatsAppConfigurationError(
            response.text
        )


    data = response.json()

    return (
        data.get("messageId")
        or data.get("id")
        or "ghl_message_sent"
    )