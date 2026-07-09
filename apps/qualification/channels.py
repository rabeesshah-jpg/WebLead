"""WhatsApp input channel and reply mode helpers."""

from __future__ import annotations

import logging
from typing import Any, Literal

from apps.qualification.api.logging import log_qualification_event
from apps.qualification.domain.booking_completion import (
    build_booking_completion_reply,
    resolve_booking_link,
)
from apps.qualification.domain.language_selection import (
    LANGUAGE_ENGLISH,
    normalize_conversation_language,
)
from apps.qualification.domain.post_booking_link_response import (
    build_post_booking_link_reply,
)
from apps.qualification.domain.tts_safety import sanitize_spoken_text_for_tts
from apps.qualification.services.booking_link_delivery_service import (
    booking_link_already_sent,
    mark_booking_link_sent_for_text_completion,
)
from apps.qualification.services.conversation_session_service import (
    get_or_create_conversation_session,
)

InputChannel = Literal["whatsapp_text", "whatsapp_voice_note"]
ReplyMode = Literal["text", "voice"]

VALID_INPUT_CHANNELS = frozenset({"whatsapp_text", "whatsapp_voice_note"})


def reply_mode_for_input_channel(input_channel: InputChannel) -> ReplyMode:
    """Map the latest inbound channel to the outbound reply mode."""
    if input_channel == "whatsapp_voice_note":
        return "voice"
    return "text"


def _apply_post_booking_completion_fields(
    finalized: dict[str, Any],
    *,
    language: str,
    input_channel: InputChannel,
    user_message: str,
    booking_link: str,
) -> None:
    reply = build_post_booking_link_reply(message=user_message, language=language)
    spoken_text = sanitize_spoken_text_for_tts(reply, language=language)
    finalized["spoken_text"] = spoken_text
    finalized["whatsapp_text"] = reply
    finalized["actions"] = []
    finalized["booking_link"] = booking_link or None
    finalized["send_booking_link"] = False
    finalized["booking_link_sent"] = True
    finalized["conversation_state"] = "BOOKING_LINK_SENT"
    if input_channel == "whatsapp_voice_note":
        finalized["reply_text"] = spoken_text
    else:
        finalized["reply_text"] = reply


def _apply_first_booking_completion_fields(
    finalized: dict[str, Any],
    *,
    language: str,
    input_channel: InputChannel,
    booking: dict[str, object],
) -> None:
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
        finalized["reply_text"] = spoken_text
        finalized["send_booking_link"] = bool(booking.get("booking_link"))
        finalized["booking_link_sent"] = False
    else:
        finalized["reply_text"] = str(booking["reply_text"])
        finalized["send_booking_link"] = False
        finalized["booking_link_sent"] = bool(booking.get("booking_link"))

    if finalized.get("booking_link_sent"):
        finalized["conversation_state"] = "BOOKING_LINK_SENT"


def finalize_turn_response(
    response: dict[str, Any],
    *,
    input_channel: InputChannel,
    transcript: str | None = None,
    conversation_language: str = LANGUAGE_ENGLISH,
    whatsapp_number: str | None = None,
    user_message: str | None = None,
) -> dict[str, Any]:
    """Attach channel metadata and completion booking fields to a turn response."""
    finalized = dict(response)
    language = normalize_conversation_language(conversation_language)
    finalized["conversation_language"] = language
    finalized["reply_mode"] = reply_mode_for_input_channel(input_channel)

    if input_channel == "whatsapp_voice_note" and transcript is not None:
        finalized["transcript"] = transcript

    if finalized.get("qualification_status") == "completed":
        booking_link = resolve_booking_link()
        session = None
        already_sent = False
        if whatsapp_number:
            session, _ = get_or_create_conversation_session(whatsapp_number=whatsapp_number)
            already_sent = booking_link_already_sent(session=session)

        if already_sent:
            _apply_post_booking_completion_fields(
                finalized,
                language=language,
                input_channel=input_channel,
                user_message=user_message or "",
                booking_link=booking_link,
            )
            log_qualification_event(
                "booking_link_send_blocked",
                whatsapp_number_prefix=(whatsapp_number or "")[:6],
                conversation_state=finalized.get("conversation_state"),
                booking_link_sent=True,
            )
        else:
            booking = build_booking_completion_reply(language=language)
            _apply_first_booking_completion_fields(
                finalized,
                language=language,
                input_channel=input_channel,
                booking=booking,
            )
            if (
                input_channel == "whatsapp_text"
                and booking_link
                and session is not None
            ):
                mark_booking_link_sent_for_text_completion(
                    session=session,
                    whatsapp_number=whatsapp_number or "",
                )
                finalized["booking_link_sent"] = True
                finalized["conversation_state"] = "BOOKING_LINK_SENT"
                log_qualification_event(
                    "booking_link_sent",
                    whatsapp_number_prefix=(whatsapp_number or "")[:6],
                    conversation_state="BOOKING_LINK_SENT",
                    delivery="whatsapp_text_inline",
                )
    else:
        reply_text = str(finalized.get("reply_text") or "")
        if input_channel == "whatsapp_voice_note":
            raw_spoken = finalized.get("spoken_text")
            if raw_spoken is not None and str(raw_spoken).strip():
                spoken_source = str(raw_spoken)
            elif reply_text.strip():
                spoken_source = reply_text
            else:
                spoken_source = ""
            spoken_text = (
                sanitize_spoken_text_for_tts(spoken_source, language=language)
                if spoken_source
                else ""
            )
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
