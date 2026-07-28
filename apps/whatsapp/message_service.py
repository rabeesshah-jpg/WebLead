"""Outbound WhatsApp messaging via Twilio (text, templates, lists)."""

from __future__ import annotations

import json
import logging
from typing import Any

from apps.qualification.domain.language_selection import (
    LANGUAGE_ENGLISH,
    normalize_conversation_language,
)
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.domain.qualification_options import (
    PROJECT_BOTH,
    PROJECT_NEW_WEBSITE,
    PROJECT_WEBSITE_UPGRADE,
    REFERRAL_FACEBOOK,
    REFERRAL_FRIEND,
    REFERRAL_GOOGLE,
    REFERRAL_INSTAGRAM,
    REFERRAL_OTHER,
)

from apps.qualification.integrations.twilio_whatsapp_message import (
    TwilioWhatsAppConfigurationError,
    send_whatsapp_text_message as send_twilio_text_message,
)

from apps.qualification.integrations.twilio_whatsapp_menu import (
    send_whatsapp_menu as send_twilio_menu,
)

from apps.qualification.integrations.twilio_language_picker import (
    send_language_picker as send_twilio_language_picker,
)

from apps.qualification.integrations.twilio_business_type_picker import (
    send_business_type_list_picker as send_twilio_business_picker,
)

logger = logging.getLogger("apps.whatsapp")


class WhatsAppSendError(Exception):
    """Raised when an outbound WhatsApp send fails."""


REFERRAL_SOURCE_ROWS: tuple[tuple[str, str], ...] = (
    (REFERRAL_GOOGLE, "Google"),
    (REFERRAL_INSTAGRAM, "Instagram"),
    (REFERRAL_FACEBOOK, "Facebook"),
    (REFERRAL_FRIEND, "Friend / Referral"),
    (REFERRAL_OTHER, "Other"),
)


PROJECT_TYPE_BUTTONS: tuple[tuple[str, str], ...] = (
    (PROJECT_NEW_WEBSITE, "Build New Website"),
    (PROJECT_WEBSITE_UPGRADE, "Upgrade Existing Website"),
    (PROJECT_BOTH, "Both"),
)


def send_whatsapp_message(phone_number: str, message: str) -> str:
    """
    Send plain WhatsApp text message via Twilio.
    """
    try:
        return send_twilio_text_message(
            to_number=phone_number,
            body=message,
        )
    except TwilioWhatsAppConfigurationError as exc:
        raise WhatsAppSendError(str(exc)) from exc


def send_whatsapp_text_message(*, to_number: str, body: str) -> str:
    """
    Compatibility wrapper.
    """
    return send_whatsapp_message(to_number, body)


def send_booking_link_whatsapp_text(
    *,
    to_number: str,
    body: str,
    message_sid: str | None = None,
    input_channel: str | None = None,
) -> str:
    """
    Send booking link message via Twilio.
    """
    message_id = send_whatsapp_message(to_number, body)

    log_payload: dict[str, object] = {
        "event": "booking_link_whatsapp_text_sent",
        "delivery": "whatsapp_text",
        "twilio_message_sid": message_id,
    }

    if message_sid:
        log_payload["message_sid"] = message_sid[:8]

    if input_channel:
        log_payload["input_channel"] = input_channel

    logger.info(json.dumps(log_payload, separators=(",", ":")))

    return message_id


def _send_buttons_or_fallback(
    *,
    phone_number: str,
    body: str,
    buttons: list[dict[str, Any]],
    header: str | None,
    fallback_text: str,
) -> str:
    """
    Twilio does not support dynamic WAHA buttons.
    Use Twilio Content templates.
    """
    try:
        return send_twilio_language_picker(
            to_number=phone_number,
        )

    except Exception as exc:
        logger.warning(
            "twilio_buttons_fallback phone_prefix=%s error=%s",
            phone_number[:6],
            type(exc).__name__,
        )

        return send_whatsapp_message(
            phone_number,
            fallback_text,
        )


def _send_list_or_fallback(
    *,
    phone_number: str,
    title: str,
    description: str,
    button_label: str,
    sections: list[dict[str, Any]],
    fallback_text: str,
    footer: str | None = None,
) -> str:
    """
    Send Twilio Content list template.
    """
    try:
        return send_twilio_menu(
            to_number=phone_number,
        )

    except Exception as exc:
        logger.warning(
            "twilio_list_fallback phone_prefix=%s error=%s",
            phone_number[:6],
            type(exc).__name__,
        )

        return send_whatsapp_message(
            phone_number,
            fallback_text,
        )


def send_language_picker(*, to_number: str) -> str:
    """
    Send language picker using Twilio Content API.
    """
    return send_twilio_language_picker(
        to_number=to_number,
    )


def send_whatsapp_menu(*, to_number: str) -> str:
    """
    Send main menu using Twilio Content API.
    """
    return send_twilio_menu(
        to_number=to_number,
    )


def send_referral_source_list(
    *,
    to_number: str,
    language: str = LANGUAGE_ENGLISH,
) -> str:
    """
    Send referral source selection.

    Currently falls back to text because the old WAHA dynamic list
    cannot be directly represented by Twilio without a dedicated SID.
    """

    normalized = normalize_conversation_language(language)

    body = get_customer_message(
        language=normalized,
        key="referral_source",
    )

    return send_whatsapp_message(
        to_number,
        body,
    )


def send_business_type_list(
    *,
    to_number: str,
    language: str = LANGUAGE_ENGLISH,
) -> str:
    """
    Send business type picker using Twilio Content API.
    """

    return send_twilio_business_picker(
        to_number=to_number,
        language=language,
    )


def send_business_type_list_picker(
    *,
    to_number: str,
    language: str,
) -> str:
    return send_business_type_list(
        to_number=to_number,
        language=language,
    )


def send_project_type_buttons(
    *,
    to_number: str,
    language: str = LANGUAGE_ENGLISH,
) -> str:
    """
    Send project type selection.

    Falls back to text because no Twilio Content SID exists yet.
    """

    del language

    fallback = (
        "What do you need?\n"
        "1. Build New Website\n"
        "2. Upgrade Existing Website\n"
        "3. Both"
    )

    return send_whatsapp_message(
        to_number,
        fallback,
    )


def deliver_option_template(
    *,
    option_template: str,
    phone_number: str,
    language: str = LANGUAGE_ENGLISH,
) -> str | None:
    """
    Route qualification templates through Twilio.
    """

    if option_template == "referral_source":
        return send_referral_source_list(
            to_number=phone_number,
            language=language,
        )

    if option_template == "business_type":
        return send_business_type_list(
            to_number=phone_number,
            language=language,
        )

    if option_template == "project_type":
        return send_project_type_buttons(
            to_number=phone_number,
            language=language,
        )

    return None