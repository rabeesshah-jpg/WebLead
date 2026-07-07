"""Process LiveKit post-call qualification completion events."""

from __future__ import annotations

import logging
from typing import Any

from apps.qualification.api.logging import log_qualification_event
from apps.qualification.conversation_state import save_accepted_fields
from apps.qualification.domain.booking_completion import build_booking_completion_reply
from apps.qualification.domain.language_selection import (
    LANGUAGE_ENGLISH,
    normalize_conversation_language,
)
from apps.qualification.services.booking_link_delivery_service import (
    BookingLinkDeliveryError,
    deliver_booking_link_whatsapp_text,
)
from apps.qualification.services.conversation_session_service import (
    get_or_create_conversation_session,
)
from apps.qualification.voice_call_event_idempotency import (
    begin_voice_call_event,
    cache_voice_call_response,
)


class VoiceCallCompletedSendError(Exception):
    """Raised when the booking-link WhatsApp message cannot be sent."""


def _conversation_language_for(whatsapp_number: str) -> str:
    session, _created = get_or_create_conversation_session(whatsapp_number=whatsapp_number)
    return normalize_conversation_language(session.language or LANGUAGE_ENGLISH)


def _build_accepted_fields(payload: dict[str, Any]) -> dict[str, Any]:
    accepted_fields: dict[str, Any] = {
        "project_type": payload["project_type"],
        "requirements": payload["requirements"],
        "referral_source": payload["referral_source"],
        "whatsapp_confirmed": payload["whatsapp_confirmed"],
    }
    preferred_phone = payload.get("preferred_phone")
    if preferred_phone:
        accepted_fields["preferred_phone"] = preferred_phone
    return accepted_fields


def _build_response(
    *,
    status: str,
    payload: dict[str, Any],
    accepted_fields: dict[str, Any],
    booking_fields: dict[str, object],
) -> dict[str, Any]:
    return {
        "status": status,
        "event_id": payload["event_id"],
        "call_id": payload["call_id"],
        "accepted_fields": accepted_fields,
        "qualification_status": "completed",
        "send_booking_link": bool(booking_fields.get("send_booking_link")),
        "booking_link_sent": bool(booking_fields.get("booking_link_sent")),
        "booking_link": booking_fields.get("booking_link"),
    }


class VoiceCallCompletedService:
    """Persist voice-call qualification data and optionally send booking links."""

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        event_id = payload["event_id"]
        cached = begin_voice_call_event(event_id)
        if cached is not None:
            duplicate = dict(cached)
            duplicate["status"] = "duplicate"
            return duplicate

        whatsapp_number = payload["whatsapp_number"]
        accepted_fields = _build_accepted_fields(payload)
        save_accepted_fields(whatsapp_number, accepted_fields)
        get_or_create_conversation_session(whatsapp_number=whatsapp_number)

        booking_fields: dict[str, object] = {
            "send_booking_link": False,
            "booking_link_sent": False,
            "booking_link": None,
        }

        if payload["send_booking_link"]:
            language = _conversation_language_for(whatsapp_number)
            booking_fields = build_booking_completion_reply(language=language)
            if booking_fields.get("booking_link"):
                try:
                    booking_fields["booking_link_sent"] = deliver_booking_link_whatsapp_text(
                        whatsapp_number=whatsapp_number,
                        language=language,
                        booking_link=str(booking_fields.get("booking_link") or ""),
                        input_channel="voice_call_completed",
                    )
                except BookingLinkDeliveryError as exc:
                    raise VoiceCallCompletedSendError(str(exc)) from exc
            else:
                log_qualification_event(
                    "voice_call_completed_booking_link_unconfigured",
                    level=logging.WARNING,
                    event_id=event_id,
                    call_id=payload["call_id"],
                )

        response = _build_response(
            status="accepted",
            payload=payload,
            accepted_fields=accepted_fields,
            booking_fields=booking_fields,
        )
        cache_voice_call_response(event_id, response)
        log_qualification_event(
            "voice_call_completed_accepted",
            event_id=event_id,
            call_id=payload["call_id"],
            send_booking_link=payload["send_booking_link"],
            booking_link_sent=response["booking_link_sent"],
        )
        return response
