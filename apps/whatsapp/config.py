"""WAHA configuration and chatId helpers."""

from __future__ import annotations

from django.conf import settings


class WahaConfigurationError(Exception):
    """Raised when WAHA settings are incomplete."""


def get_waha_base_url() -> str:
    return (getattr(settings, "WAHA_BASE_URL", "") or "").rstrip("/")


def get_waha_session() -> str:
    return (getattr(settings, "WAHA_SESSION", "") or "default").strip() or "default"


def get_waha_api_key() -> str:
    return (getattr(settings, "WAHA_API_KEY", "") or "").strip()


def get_waha_webhook_secret() -> str:
    """
    Secret expected on inbound WAHA webhooks.

    Prefers WAHA_WEBHOOK_SECRET; falls back to WAHA_API_KEY so a single key can
    protect both REST and webhook when a dedicated secret is unset.
    """
    dedicated = (getattr(settings, "WAHA_WEBHOOK_SECRET", "") or "").strip()
    if dedicated:
        return dedicated
    return get_waha_api_key()


def validate_waha_send_configuration() -> None:
    if not get_waha_base_url():
        raise WahaConfigurationError("WAHA_BASE_URL is not configured")
    if not get_waha_api_key():
        raise WahaConfigurationError("WAHA_API_KEY is not configured")


def phone_to_chat_id(phone_number: str) -> str:
    """
    Convert an E.164 (or digits) phone number to a WAHA chatId.

    Examples:
    - ``+923301675395`` -> ``923301675395@c.us``
    - ``whatsapp:+923301675395`` -> ``923301675395@c.us``
    - ``923301675395@c.us`` -> unchanged
    """
    raw = "".join(str(phone_number or "").split())
    if not raw:
        raise ValueError("phone_number is required")
    if raw.endswith("@c.us") or raw.endswith("@g.us") or raw.endswith("@lid"):
        return raw
    if raw.lower().startswith("whatsapp:"):
        raw = raw.split(":", 1)[1]
    digits = raw[1:] if raw.startswith("+") else raw
    digits = "".join(ch for ch in digits if ch.isdigit())
    if not digits:
        raise ValueError("phone_number must contain digits")
    return f"{digits}@c.us"


def chat_id_to_e164(chat_id: str) -> str:
    """Convert ``9233…@c.us`` (or similar) to ``+9233…`` E.164."""
    raw = "".join(str(chat_id or "").split())
    if "@" in raw:
        raw = raw.split("@", 1)[0]
    if raw.lower().startswith("whatsapp:"):
        raw = raw.split(":", 1)[1]
    digits = raw[1:] if raw.startswith("+") else raw
    digits = "".join(ch for ch in digits if ch.isdigit())
    if not digits:
        raise ValueError("chat_id must contain digits")
    return f"+{digits}"
