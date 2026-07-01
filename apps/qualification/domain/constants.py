"""Shared qualification domain constants."""

from __future__ import annotations

import re

TWILIO_INBOUND_MESSAGE_SID_PATTERN = re.compile(r"^(?:SM|MM)[a-zA-Z0-9]{32}$")
