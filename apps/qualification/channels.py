"""WhatsApp input channel and reply mode helpers."""

from __future__ import annotations

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
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.domain.option_template_delivery import (
    resolve_option_template,
)
from apps.qualification.domain.numbered_qualification import (
    build_qualification_state_machine_fields,
)
from apps.qualification.domain.tts_safety import sanitize_spoken_text_for_tts
from apps.qualification.domain.validators import normalize_whatsapp_session_number
from apps.qualification.services.booking_link_delivery_service import (
    response_contains_booking_url,
    send_booking_link_once,
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


def _resolve_session_whatsapp_number(
    whatsapp_number: str | None,
    finalized: dict[str, Any],
) -> str | None:
    """Return a canonical session number when one is available on the turn."""
    for candidate in (whatsapp_number, finalized.get("preferred_phone")):
        if not candidate:
            continue
        try:
            return normalize_whatsapp_session_number(str(candidate))
        except ValueError:
            continue
    return None


def _booking_completion_fields_without_session(
    *,
    language: str,
    input_channel: InputChannel,
) -> dict[str, Any]:
    """Apply first-send booking copy when no session number is available."""
    booking = build_booking_completion_reply(language=language)
    text_reply = str(booking.get("reply_text") or "")
    spoken_text = sanitize_spoken_text_for_tts(
        str(booking.get("spoken_text") or ""),
        language=language,
    )
    booking_link = booking.get("booking_link")
    contains_url = bool(booking_link and booking_link in text_reply)
    return {
        "spoken_text": spoken_text,
        "whatsapp_text": text_reply,
        "reply_text": text_reply,
        "actions": list(booking.get("actions") or []),
        "booking_link": booking_link,
        "send_booking_link": contains_url,
        "booking_link_sent": contains_url,
        "conversation_state": "BOOKING_LINK_SENT" if contains_url else None,
        "contains_booking_url": contains_url,
    }


def _voice_transcription_unclear_copy(*, language: str) -> tuple[str, str]:
    """Return spoken and text-fallback copy for empty or failed voice transcription."""
    spoken = get_customer_message(
        language=language,
        key="voice_transcription_unclear_spoken",
    )
    text_fallback = get_customer_message(
        language=language,
        key="voice_transcription_unclear",
    )
    return spoken, text_fallback


def apply_outbound_channel_routing(
    finalized: dict[str, Any],
    *,
    input_channel: InputChannel,
) -> dict[str, Any]:
    """
    Attach n8n routing flags so text and voice inbound channels do not duplicate replies.

    Text inbound sends ``whatsapp_text`` only. Voice inbound sends audio from
    ``spoken_text`` only, except the one-time booking-link text on first completion.
    """
    language = normalize_conversation_language(
        str(finalized.get("conversation_language") or LANGUAGE_ENGLISH),
    )
    booking_link = resolve_booking_link()
    contains_booking_link = response_contains_booking_url(
        finalized,
        booking_link=booking_link,
    )

    if input_channel == "whatsapp_text":
        text_reply = str(
            finalized.get("reply_text") or finalized.get("whatsapp_text") or ""
        ).strip()
        finalized["reply_text"] = text_reply
        finalized["whatsapp_text"] = text_reply
        finalized["spoken_text"] = sanitize_spoken_text_for_tts(
            str(finalized.get("spoken_text") or text_reply),
            language=language,
        )
        finalized["should_send_text"] = bool(text_reply)
        finalized["should_send_audio"] = False
        finalized["contains_booking_link"] = contains_booking_link
        finalized.pop("text_fallback_reply", None)
        return finalized

    if finalized.get("is_voice_transcription_unclear"):
        spoken_text, text_fallback = _voice_transcription_unclear_copy(language=language)
        finalized["spoken_text"] = spoken_text
        finalized["reply_text"] = spoken_text
        finalized["whatsapp_text"] = text_fallback
        finalized["text_fallback_reply"] = text_fallback
        finalized["should_send_text"] = False
        finalized["should_send_audio"] = bool(spoken_text.strip())
        finalized["contains_booking_link"] = False
        return finalized

    if contains_booking_link:
        booking_text = str(
            finalized.get("reply_text") or finalized.get("whatsapp_text") or ""
        ).strip()
        spoken_text = sanitize_spoken_text_for_tts(
            str(finalized.get("spoken_text") or ""),
            language=language,
        )
        finalized["spoken_text"] = spoken_text
        finalized["reply_text"] = booking_text
        finalized["whatsapp_text"] = booking_text
        finalized["should_send_text"] = bool(booking_text)
        finalized["should_send_audio"] = bool(spoken_text.strip())
        finalized.pop("text_fallback_reply", None)
    else:
        spoken_source = (
            str(finalized.get("spoken_text") or "").strip()
            or str(finalized.get("reply_text") or "").strip()
        )
        spoken_text = (
            sanitize_spoken_text_for_tts(spoken_source, language=language)
            if spoken_source
            else ""
        )
        finalized["spoken_text"] = spoken_text
        finalized["reply_text"] = spoken_text
        finalized["whatsapp_text"] = ""
        finalized["should_send_text"] = False
        finalized["should_send_audio"] = bool(spoken_text.strip())
        finalized.pop("text_fallback_reply", None)

    finalized["contains_booking_link"] = contains_booking_link
    return finalized


def _attach_option_template(
    finalized: dict[str, Any],
    *,
    input_channel: InputChannel,
) -> dict[str, Any]:
    """
    Tell n8n which Twilio clickable template to send for the current question.

    Text inbound sets ``option_template`` for referral_source (all customers) and
    business_type (existing customers only). New-customer numbered questions and
    voice notes must not trigger clickable templates.
    """
    next_field = finalized.get("next_field")
    accepted_fields = finalized.get("accepted_fields")
    if not isinstance(accepted_fields, dict):
        accepted_fields = None
    option_template = resolve_option_template(
        next_field=str(next_field) if next_field is not None else None,
        input_channel=input_channel,
        qualification_status=str(finalized.get("qualification_status") or ""),
        accepted_fields=accepted_fields,
    )
    if option_template is not None:
        finalized["option_template"] = option_template
    else:
        finalized.pop("option_template", None)
    return finalized


def _apply_voice_option_spoken_copy(
    finalized: dict[str, Any],
    *,
    language: str,
    input_channel: InputChannel,
) -> dict[str, Any]:
    """Use natural spoken options for option-step questions on voice turns."""
    next_field = finalized.get("next_field")
    accepted_fields = finalized.get("accepted_fields")
    if not isinstance(accepted_fields, dict):
        accepted_fields = None
    # List-picker / Twilio-handoff turns intentionally leave Body/spoken empty.
    # Do not invent a ``{field}_voice`` message key for those responses.
    if not str(finalized.get("reply_text") or finalized.get("spoken_text") or "").strip():
        return finalized
    if (
        input_channel != "whatsapp_voice_note"
        or finalized.get("qualification_status") != "in_progress"
        or resolve_option_template(
            next_field=str(next_field) if next_field is not None else None,
            input_channel="whatsapp_text",
            qualification_status=str(finalized.get("qualification_status") or ""),
            accepted_fields=accepted_fields,
        )
        is None
    ):
        return finalized
    spoken_key = str(finalized.get("option_spoken_message_key") or f"{next_field}_voice")
    spoken = get_customer_message(language=language, key=spoken_key)
    finalized["spoken_text"] = spoken
    return finalized


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
        session_number = _resolve_session_whatsapp_number(whatsapp_number, finalized)
        if session_number:
            session, _ = get_or_create_conversation_session(whatsapp_number=session_number)
            booking_fields = send_booking_link_once(
                session=session,
                language=language,
                input_channel=input_channel,
                user_message=user_message or "",
                whatsapp_number=session_number,
            )
        else:
            booking_fields = _booking_completion_fields_without_session(
                language=language,
                input_channel=input_channel,
            )
        finalized.update(booking_fields)
    else:
        qualification_reply = str(finalized.get("reply_text") or "")
        if input_channel == "whatsapp_voice_note":
            spoken_source = (
                str(finalized.get("spoken_text") or "").strip()
                or qualification_reply
            )
            spoken_text = (
                sanitize_spoken_text_for_tts(spoken_source, language=language)
                if spoken_source
                else ""
            )
            finalized["spoken_text"] = spoken_text
            finalized.setdefault("actions", [])
            finalized["reply_text"] = spoken_text
        else:
            spoken_text = sanitize_spoken_text_for_tts(
                str(finalized.get("spoken_text") or qualification_reply),
                language=language,
            )
            finalized["spoken_text"] = spoken_text
            if "whatsapp_text" in finalized:
                finalized["whatsapp_text"] = str(finalized["whatsapp_text"])
            else:
                finalized["whatsapp_text"] = qualification_reply
            finalized.setdefault("actions", [])
        finalized["booking_link_sent"] = False
        finalized["send_booking_link"] = False
        finalized["booking_link"] = None
        finalized["contains_booking_url"] = False

    finalized = _apply_voice_option_spoken_copy(
        finalized,
        language=language,
        input_channel=input_channel,
    )

    routed = apply_outbound_channel_routing(
        finalized,
        input_channel=input_channel,
    )
    routed = _attach_option_template(routed, input_channel=input_channel)
    routed.pop("option_spoken_message_key", None)
    should_send_qualification_override = (
        bool(routed.get("should_send_qualification_question"))
        if "should_send_qualification_question" in routed
        else None
    )
    routed.update(
        build_qualification_state_machine_fields(
            next_field=str(routed["next_field"]) if routed.get("next_field") else None,
            qualification_status=str(routed.get("qualification_status") or ""),
            conversation_language=language,
            reply_text=str(routed.get("reply_text") or ""),
            should_send_text=(
                bool(routed.get("should_send_text"))
                if "should_send_text" in routed
                else None
            ),
            should_send_qualification_question=should_send_qualification_override,
        )
    )

    log_qualification_event(
        "outbound_channel_routing",
        input_channel=input_channel,
        conversation_language=language,
        option_template=routed.get("option_template"),
        next_field=routed.get("next_field"),
        qualification_step=routed.get("qualification_step"),
        has_media=input_channel == "whatsapp_voice_note",
        transcript_text=(transcript or "")[:120] if transcript else None,
        reply_text=str(routed.get("reply_text") or "")[:200],
        spoken_text=str(routed.get("spoken_text") or "")[:200],
        should_send_text=bool(routed.get("should_send_text")),
        should_send_audio=bool(routed.get("should_send_audio")),
        contains_booking_link=bool(routed.get("contains_booking_link")),
        booking_link_sent_after=bool(routed.get("booking_link_sent")),
    )
    return routed
