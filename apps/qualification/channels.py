"""WhatsApp input channel and reply mode helpers."""

from __future__ import annotations

from typing import Any, Literal

from django.conf import settings

from apps.qualification.domain.language_selection import (
    LANGUAGE_ENGLISH,
    normalize_conversation_language,
)
from apps.qualification.domain.messages import get_customer_message

InputChannel = Literal["whatsapp_text", "whatsapp_voice_note"]
ReplyMode = Literal["text", "voice"]

VALID_INPUT_CHANNELS = frozenset({"whatsapp_text", "whatsapp_voice_note"})

COMPLETION_REPLY_TEXT = get_customer_message(language=LANGUAGE_ENGLISH, key="completion")


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
    conversation_language: str = LANGUAGE_ENGLISH,
) -> dict[str, Any]:
    """Attach channel metadata and completion booking fields to a turn response."""
    finalized = dict(response)
    language = normalize_conversation_language(conversation_language)
    finalized["conversation_language"] = language
    finalized["reply_mode"] = reply_mode_for_input_channel(input_channel)

    if input_channel == "whatsapp_voice_note" and transcript is not None:
        finalized["transcript"] = transcript

    if finalized.get("qualification_status") == "completed":
        finalized["send_booking_link"] = True
        finalized["booking_link"] = settings.BOOKING_LINK
        finalized["reply_text"] = get_customer_message(language=language, key="completion")
    else:
        finalized["send_booking_link"] = False
        finalized["booking_link"] = None

    return finalized
