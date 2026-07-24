"""Outbound WhatsApp messaging via WAHA (text, buttons, lists)."""

from __future__ import annotations

import json
import logging
from typing import Any

from apps.qualification.domain.language_selection import (
    LANGUAGE_ARABIC,
    LANGUAGE_ENGLISH,
    normalize_conversation_language,
)
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.domain.numbered_qualification import (
    NUMBERED_QUALIFICATION_OPTIONS,
)
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
from apps.qualification.domain.whatsapp_menu_config import (
    MENU_ITEMS,
    MENU_LIST_BODY,
    MENU_LIST_BUTTON_LABEL,
    MENU_LIST_HEADER,
    MENU_LIST_SECTION_TITLE,
)
from apps.whatsapp import waha_client
from apps.whatsapp.config import WahaConfigurationError

logger = logging.getLogger("apps.whatsapp")


class WhatsAppSendError(Exception):
    """Raised when an outbound WhatsApp send fails after fallbacks."""


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

LANGUAGE_PICKER_BUTTONS: tuple[tuple[str, str], ...] = (
    ("lang_en", "English"),
    ("lang_ar", "العربية"),
)


def send_whatsapp_message(phone_number: str, message: str) -> str:
    """
    Send a plain-text WhatsApp message via WAHA.

    ``phone_number`` may be E.164 (``+9233…``) or any customer number; the
    WAHA session is authenticated as the business line (e.g. +923301675395).
    """
    try:
        return waha_client.send_text(phone_number=phone_number, text=message)
    except (WahaConfigurationError, waha_client.WahaApiError) as exc:
        raise WhatsAppSendError(str(exc)) from exc


def send_whatsapp_text_message(*, to_number: str, body: str) -> str:
    """Compatibility wrapper matching the former Twilio helper signature."""
    return send_whatsapp_message(to_number, body)


def send_booking_link_whatsapp_text(
    *,
    to_number: str,
    body: str,
    message_sid: str | None = None,
    input_channel: str | None = None,
) -> str:
    """Send the booking-link completion message as WhatsApp text."""
    message_id = send_whatsapp_message(to_number, body)
    log_payload: dict[str, object] = {
        "event": "booking_link_whatsapp_text_sent",
        "delivery": "whatsapp_text",
        "waha_message_id": message_id,
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
    try:
        return waha_client.send_buttons(
            phone_number=phone_number,
            body=body,
            buttons=buttons,
            header=header,
        )
    except (WahaConfigurationError, waha_client.WahaApiError) as exc:
        logger.warning(
            "waha_buttons_fallback phone_prefix=%s error=%s",
            phone_number[:6],
            type(exc).__name__,
        )
        return send_whatsapp_message(phone_number, fallback_text)


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
    try:
        return waha_client.send_list(
            phone_number=phone_number,
            title=title,
            description=description,
            button_label=button_label,
            sections=sections,
            footer=footer,
        )
    except (WahaConfigurationError, waha_client.WahaApiError) as exc:
        logger.warning(
            "waha_list_fallback phone_prefix=%s error=%s",
            phone_number[:6],
            type(exc).__name__,
        )
        return send_whatsapp_message(phone_number, fallback_text)


def send_language_picker(*, to_number: str) -> str:
    """Send English / العربية reply buttons (stable ids lang_en / lang_ar)."""
    buttons = [
        {"type": "reply", "id": button_id, "text": label}
        for button_id, label in LANGUAGE_PICKER_BUTTONS
    ]
    fallback = (
        "Please choose your language:\n"
        "1. English\n"
        "2. العربية\n\n"
        "Reply with 1 or 2, or English / العربية."
    )
    return _send_buttons_or_fallback(
        phone_number=to_number,
        body="Please choose your language",
        buttons=buttons,
        header="Language",
        fallback_text=fallback,
    )


def send_whatsapp_menu(*, to_number: str) -> str:
    """Send the main menu as a WAHA list (stable row ids from MENU_ITEMS)."""
    rows = [
        {
            "title": item["label"].split("\n", 1)[0][:24],
            "rowId": item["id"],
            "description": (
                item["label"].split("\n", 1)[1][:72]
                if "\n" in item["label"]
                else None
            ),
        }
        for item in MENU_ITEMS
    ]
    sections = [{"title": MENU_LIST_SECTION_TITLE, "rows": rows}]
    fallback_lines = [MENU_LIST_BODY, ""]
    for index, item in enumerate(MENU_ITEMS, start=1):
        fallback_lines.append(f"{index}. {item['label'].replace(chr(10), ' — ')}")
    return _send_list_or_fallback(
        phone_number=to_number,
        title=MENU_LIST_HEADER,
        description=MENU_LIST_BODY,
        button_label=MENU_LIST_BUTTON_LABEL,
        sections=sections,
        fallback_text="\n".join(fallback_lines),
    )


def send_referral_source_list(*, to_number: str, language: str = LANGUAGE_ENGLISH) -> str:
    """Send referral_source list with stable row ids (google, instagram, …)."""
    normalized = normalize_conversation_language(language)
    body = get_customer_message(language=normalized, key="referral_source")
    rows = [
        {"title": label[:24], "rowId": row_id, "description": None}
        for row_id, label in REFERRAL_SOURCE_ROWS
    ]
    sections = [{"title": "How did you hear about us?", "rows": rows}]
    return _send_list_or_fallback(
        phone_number=to_number,
        title="Lead source",
        description=body.split("\n")[0] if body else "How did you hear about us?",
        button_label="Options",
        sections=sections,
        fallback_text=body,
    )


def send_business_type_list(*, to_number: str, language: str = LANGUAGE_ENGLISH) -> str:
    """Send business_type list using numbered qualification option ids."""
    normalized = normalize_conversation_language(language)
    options = NUMBERED_QUALIFICATION_OPTIONS.get("business_type") or ()
    rows = []
    fallback_lines = [
        get_customer_message(language=normalized, key="business_type"),
        "",
    ]
    for option in options:
        label = option.labels.get(normalized) or option.labels.get(LANGUAGE_ENGLISH) or option.value
        rows.append(
            {
                "title": label[:24],
                "rowId": option.value,
                "description": label[24:96] if len(label) > 24 else None,
            }
        )
        fallback_lines.append(f"{option.number}. {label}")
    sections = [{"title": "Business type", "rows": rows}]
    return _send_list_or_fallback(
        phone_number=to_number,
        title="Business type",
        description="Please choose your business type",
        button_label="Options",
        sections=sections,
        fallback_text="\n".join(line for line in fallback_lines if line is not None),
    )


def send_business_type_list_picker(*, to_number: str, language: str) -> str:
    """Compatibility alias for the former Twilio business-type helper."""
    return send_business_type_list(to_number=to_number, language=language)


def send_project_type_buttons(*, to_number: str, language: str = LANGUAGE_ENGLISH) -> str:
    """Send legacy project_type reply buttons (new / upgrade / both)."""
    del language  # Labels are bilingual-stable English for this legacy picker.
    buttons = [
        {"type": "reply", "id": button_id, "text": label}
        for button_id, label in PROJECT_TYPE_BUTTONS
    ]
    fallback = (
        "What do you need?\n"
        "1. Build New Website\n"
        "2. Upgrade Existing Website\n"
        "3. Both"
    )
    return _send_buttons_or_fallback(
        phone_number=to_number,
        body="What do you need?",
        buttons=buttons,
        header="Website type",
        fallback_text=fallback,
    )


def deliver_option_template(
    *,
    option_template: str,
    phone_number: str,
    language: str = LANGUAGE_ENGLISH,
) -> str | None:
    """
    Send the interactive message for an ``option_template`` key via WAHA.

    Returns the message id, or ``None`` when the template key is unknown.
    """
    if option_template == "referral_source":
        return send_referral_source_list(to_number=phone_number, language=language)
    if option_template == "business_type":
        return send_business_type_list(to_number=phone_number, language=language)
    if option_template == "project_type":
        return send_project_type_buttons(to_number=phone_number, language=language)
    return None
