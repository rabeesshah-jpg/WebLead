"""WhatsApp input channel and reply mode helpers."""

from __future__ import annotations

from typing import Any, Literal

from django.conf import settings

InputChannel = Literal["whatsapp_text", "whatsapp_voice_note"]
ReplyMode = Literal["text", "voice"]

VALID_INPUT_CHANNELS = frozenset({"whatsapp_text", "whatsapp_voice_note"})

COMPLETION_REPLY_TEXT = "Thank you. I will send you a booking link now."


def reply_mode_for_input_channel(input_channel: InputChannel) -> ReplyMode:
    """Map the latest inbound channel to the outbound reply mode."""
    if input_channel == "whatsapp_voice_note":
        return "voice"
    return "text"


def finalize_turn_response(
    response: dict[str, Any],
    *,
    input_channel: InputChannel,
    transcript: str | None = None,
) -> dict[str, Any]:
    """Attach channel metadata and completion booking fields to a turn response."""
    finalized = dict(response)
    finalized["reply_mode"] = reply_mode_for_input_channel(input_channel)

    if input_channel == "whatsapp_voice_note" and transcript is not None:
        finalized["transcript"] = transcript

    if finalized.get("qualification_status") == "completed":
        finalized["send_booking_link"] = True
        finalized["booking_link"] = settings.BOOKING_LINK
        finalized["reply_text"] = COMPLETION_REPLY_TEXT
    else:
        finalized["send_booking_link"] = False
        finalized["booking_link"] = None

    return finalized
