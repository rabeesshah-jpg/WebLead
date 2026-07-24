"""Shared qualification domain constants."""

from __future__ import annotations

import re

# Legacy Twilio MessageSid shape (SM|MM + 32 alnum).
TWILIO_INBOUND_MESSAGE_SID_PATTERN = re.compile(r"^(?:SM|MM)[a-zA-Z0-9]{32}$")

# Accept Twilio SIDs and WAHA message ids (e.g. true_9233…@c.us_AAAA…).
INBOUND_MESSAGE_SID_PATTERN = re.compile(
    r"^(?:"
    r"(?:SM|MM)[a-zA-Z0-9]{32}"
    r"|(?:true|false)_[A-Za-z0-9@._\-]{8,180}"
    r")$"
)
