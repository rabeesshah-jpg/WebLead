"""Optional Twilio inbound webhook field parsing for future button handling."""

from __future__ import annotations

from dataclasses import dataclass

BUTTON_PAYLOAD_FIELD = "ButtonPayload"
BUTTON_TEXT_FIELD = "ButtonText"


@dataclass(frozen=True)
class TwilioInboundPayload:
    """Parsed Twilio WhatsApp inbound parameters with optional Quick Reply fields."""

    raw_params: dict[str, str]
    button_payload: str | None = None
    button_text: str | None = None


def parse_twilio_inbound_payload(params: dict[str, str]) -> TwilioInboundPayload:
    """Parse optional Quick Reply fields without requiring them for text messages."""
    button_payload = params.get(BUTTON_PAYLOAD_FIELD, "").strip() or None
    button_text = params.get(BUTTON_TEXT_FIELD, "").strip() or None
    return TwilioInboundPayload(
        raw_params=params,
        button_payload=button_payload,
        button_text=button_text,
    )
