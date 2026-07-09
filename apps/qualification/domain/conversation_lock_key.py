"""Lock key normalization for per-user qualification conversation turns."""

from __future__ import annotations

from apps.qualification.domain.validators import normalize_whatsapp_session_number


def normalize_conversation_lock_key(whatsapp_number_or_waid: str) -> str:
    """
    Build a stable per-customer lock key from a WhatsApp number or Twilio WaId.

    Examples:
    - ``+923246271149`` -> ``qualification:conversation_lock:whatsapp:+923246271149``
    - ``whatsapp:+923246271149`` -> same key
    """
    canonical_phone = normalize_whatsapp_session_number(whatsapp_number_or_waid)
    return f"qualification:conversation_lock:whatsapp:{canonical_phone}"
