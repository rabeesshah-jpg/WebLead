"""WhatsApp input channel and reply mode helpers."""

from __future__ import annotations

from typing import Any, Literal

from apps.qualification.domain.booking_completion import build_booking_completion_reply
from apps.qualification.domain.language_selection import (
    LANGUAGE_ENGLISH,
    normalize_conversation_language,
)
from apps.qualification.domain.tts_safety import sanitize_spoken_text_for_tts

InputChannel = Literal["whatsapp_text", "whatsapp_voice_note"]
ReplyMode = Literal["text", "voice"]

VALID_INPUT_CHANNELS = frozenset({"whatsapp_text", "whatsapp_voice_note"})


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
        booking = build_booking_completion_reply(language=language)
        spoken_text = sanitize_spoken_text_for_tts(
            str(booking["spoken_text"]),
            language=language,
        )
        whatsapp_text = str(booking.get("whatsapp_text") or "")
        finalized["spoken_text"] = spoken_text
        finalized["whatsapp_text"] = whatsapp_text
        finalized["actions"] = list(booking.get("actions") or [])
        finalized["booking_link"] = booking.get("booking_link")

        if input_channel == "whatsapp_voice_note":
            # TTS speaks spoken_text only; WhatsApp delivery sends the booking URL.
            finalized["reply_text"] = spoken_text
            finalized["send_booking_link"] = bool(booking.get("booking_link"))
            finalized["booking_link_sent"] = False
        else:
            # Text channel: single WhatsApp message already contains the URL.
            finalized["reply_text"] = str(booking["reply_text"])
            finalized["send_booking_link"] = False
            finalized["booking_link_sent"] = bool(booking.get("booking_link"))
    else:
        reply_text = str(finalized.get("reply_text") or "")
        if input_channel == "whatsapp_voice_note":
            raw_spoken = finalized.get("spoken_text")
            if raw_spoken is not None and str(raw_spoken).strip():
                spoken_text = sanitize_spoken_text_for_tts(
                    str(raw_spoken),
                    language=language,
                )
            else:
                spoken_text = ""
            finalized["spoken_text"] = spoken_text
            if "whatsapp_text" in finalized:
                finalized["whatsapp_text"] = str(finalized["whatsapp_text"])
            else:
                finalized["whatsapp_text"] = reply_text
            finalized.setdefault("actions", [])
            finalized["reply_text"] = spoken_text
        else:
            spoken_text = sanitize_spoken_text_for_tts(
                str(finalized.get("spoken_text") or reply_text),
                language=language,
            )
            finalized["spoken_text"] = spoken_text
            if "whatsapp_text" in finalized:
                finalized["whatsapp_text"] = str(finalized["whatsapp_text"])
            else:
                finalized["whatsapp_text"] = reply_text
            finalized.setdefault("actions", [])
        finalized["booking_link_sent"] = False
        finalized["send_booking_link"] = False
        finalized["booking_link"] = None

    return finalized
