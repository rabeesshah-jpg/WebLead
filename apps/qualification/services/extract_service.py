"""Qualification extract turn orchestration."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Callable

from django.utils import timezone

from apps.qualification.channels import finalize_turn_response
from apps.qualification.conversation_flow import (
    build_completed_retry_response,
    is_qualification_complete,
)
from apps.qualification.conversation_state import get_accepted_fields
from apps.qualification.api.logging import log_qualification_event
from apps.qualification.domain.latency_profiling import (
    elapsed_ms_since,
    log_external_api_total,
    log_latency_step,
    reset_external_api_accumulator,
    reset_step_duration_tracker,
)
from apps.qualification.domain.language import get_conversation_language
from apps.qualification.domain.whatsapp_menu_logging import log_whatsapp_menu_event
from apps.qualification.domain.whatsapp_menu_payload import extract_menu_selection_payload
from apps.qualification.conversation_lock import (
    acquire_conversation_turn_lock,
    build_conversation_lock_timeout_response,
)
from apps.qualification.domain.conversation_lock_key import normalize_conversation_lock_key
from apps.qualification.domain.logging_utils import (
    lock_key_prefix,
    message_sid_prefix,
    whatsapp_number_prefix,
)
from apps.qualification.domain.validators import normalize_whatsapp_session_number
from apps.qualification.domain.onboarding import maybe_prepend_onboarding_intro
from apps.qualification.domain.conversation_state_labels import (
    resolve_conversation_state_label,
)
from apps.qualification.domain.session_idle_reset import (
    compute_inactivity_gap_seconds_from_timestamps,
    session_idle_reset_threshold_seconds,
    should_reset_qualification_after_inactivity,
)
from apps.qualification.message_idempotency import (
    begin_idempotent_turn,
    cache_turn_response,
    get_cached_turn_response,
)

from apps.qualification.domain.extract_errors import ExtractStepFailure
from apps.qualification.domain.voice_note_responses import (
    build_voice_transcription_unclear_response,
)
from apps.qualification.qualification_turn import run_qualification_turn
from apps.qualification.services.booking_link_delivery_service import (
    ensure_booking_link_delivery_on_response,
    reconcile_stale_booking_link_sent_state,
)
from apps.qualification.services.conversation_restart_service import (
    reset_qualification_progress_after_inactivity,
)
from apps.qualification.services.conversation_session_service import (
    get_or_create_conversation_session,
    touch_session_last_message_at,
)
from apps.qualification.services.language_gate_service import LanguageGateService
from apps.qualification.services.transcription_service import VoiceNoteTranscriptionService
from apps.qualification.services.whatsapp_menu_service import (
    WhatsAppMenuService,
    is_lead_qualification_enabled,
)
from apps.qualification.voice_turn_idempotency import (
    begin_voice_utterance_turn,
    build_transcript_hash,
    cache_voice_utterance_response,
)

TurnHandler = Callable[..., dict[str, Any]]


class ExtractService:
    def __init__(
        self,
        *,
        transcription_service: VoiceNoteTranscriptionService | None = None,
        turn_handler: TurnHandler | None = None,
        language_gate_service: LanguageGateService | None = None,
        menu_service: WhatsAppMenuService | None = None,
    ) -> None:
        self._transcription_service = transcription_service or VoiceNoteTranscriptionService()
        self._turn_handler = turn_handler or run_qualification_turn
        self._language_gate_service = language_gate_service or LanguageGateService()
        self._menu_service = menu_service or WhatsAppMenuService()

    def _touch_session_activity(self, whatsapp_number: str) -> None:
        session, _ = get_or_create_conversation_session(whatsapp_number=whatsapp_number)
        touch_session_last_message_at(session)

    def _maybe_apply_idle_reset_on_inbound(
        self,
        *,
        session,
        whatsapp_number: str,
        previous_last_activity_at: datetime | None,
        current_inbound_message_time: datetime,
        input_channel: str,
        message_sid: str | None,
    ) -> tuple[bool, int | None]:
        """
        Reset qualification when the customer returns after the idle threshold.

        Uses ``previous_last_activity_at`` before it is updated for this turn.
        """
        inactivity_gap_seconds = compute_inactivity_gap_seconds_from_timestamps(
            previous_last_activity_at=previous_last_activity_at,
            current_inbound_message_time=current_inbound_message_time,
        )
        threshold_seconds = session_idle_reset_threshold_seconds()
        log_qualification_event(
            "qualification_inactivity_gap_observed",
            whatsapp_number_prefix=whatsapp_number_prefix(whatsapp_number),
            message_sid_prefix=message_sid_prefix(message_sid),
            input_channel=input_channel,
            previous_last_activity_at=(
                previous_last_activity_at.isoformat()
                if previous_last_activity_at is not None
                else None
            ),
            current_inbound_message_time=current_inbound_message_time.isoformat(),
            inactivity_gap_seconds=inactivity_gap_seconds,
            session_idle_reset_seconds=threshold_seconds,
            automatic_reset=False,
        )
        if not should_reset_qualification_after_inactivity(inactivity_gap_seconds):
            return False, inactivity_gap_seconds

        state_before_reset = dict(get_accepted_fields(whatsapp_number))
        state_before_reset["booking_link_sent"] = session.booking_link_sent_at is not None
        reset_qualification_progress_after_inactivity(
            whatsapp_number=whatsapp_number,
            session=session,
        )
        session.refresh_from_db()
        log_qualification_event(
            "qualification_idle_reset_triggered",
            whatsapp_number_prefix=whatsapp_number_prefix(whatsapp_number),
            message_sid_prefix=message_sid_prefix(message_sid),
            input_channel=input_channel,
            previous_last_activity_at=previous_last_activity_at.isoformat()
            if previous_last_activity_at is not None
            else None,
            current_inbound_message_time=current_inbound_message_time.isoformat(),
            inactivity_gap_seconds=inactivity_gap_seconds,
            session_idle_reset_seconds=threshold_seconds,
            idle_reset_triggered=True,
            state_before_reset=state_before_reset,
            state_after_reset={},
            booking_link_sent_before=state_before_reset.get("booking_link_sent"),
            booking_link_sent_after=False,
        )
        return True, inactivity_gap_seconds

    def _attach_conversation_state(self, response_payload: dict[str, Any]) -> dict[str, Any]:
        if response_payload.get("conversation_state"):
            return response_payload
        accepted_fields = response_payload.get("accepted_fields")
        if not isinstance(accepted_fields, dict):
            accepted_fields = {}
        response_payload["conversation_state"] = resolve_conversation_state_label(
            accepted_fields=accepted_fields,
            next_field=response_payload.get("next_field"),
            qualification_status=str(response_payload.get("qualification_status") or ""),
            booking_link_sent=bool(response_payload.get("booking_link_sent")),
        )
        return response_payload

    def _log_turn_completed(
        self,
        *,
        input_channel: str,
        response_payload: dict[str, Any],
        state_before: dict[str, Any],
        whatsapp_number: str,
        transcript: str | None = None,
        user_message: str | None = None,
        button_payload: str | None = None,
    ) -> None:
        """Emit turn-completed diagnostics without risking turn failure on log serialization."""
        try:
            accepted_fields = response_payload.get("accepted_fields")
            if not isinstance(accepted_fields, dict):
                accepted_fields = {}
            state_after = get_accepted_fields(whatsapp_number)
            if not isinstance(state_after, dict):
                state_after = {}
            captured_fields = {
                key: accepted_fields.get(key)
                for key in (
                    "customer_type",
                    "referral_source",
                    "business_type",
                    "website_status",
                    "paid_ads",
                    "main_goal",
                    "launch_timeline",
                    "requirements",
                    "whatsapp_confirmed",
                    "preferred_phone",
                )
                if key in accepted_fields
            }
            log_context: dict[str, Any] = {
                "input_channel": input_channel,
                "shared_handler_used": True,
                "conversation_language": response_payload.get("conversation_language"),
                "option_template": response_payload.get("option_template"),
                "selected_option_payload": button_payload,
                "customer_type": accepted_fields.get("customer_type"),
                "referral_source": accepted_fields.get("referral_source"),
                "business_type": accepted_fields.get("business_type"),
                "conversation_state": response_payload.get("conversation_state"),
                "state_before": {
                    key: state_before.get(key)
                    for key in (
                        "customer_type",
                        "referral_source",
                        "business_type",
                        "website_status",
                        "paid_ads",
                        "main_goal",
                        "launch_timeline",
                        "requirements",
                        "whatsapp_confirmed",
                        "preferred_phone",
                        "booking_link_sent",
                    )
                    if key in state_before
                },
                "state_after": {
                    key: state_after.get(key)
                    for key in captured_fields
                    if key in state_after
                },
                "captured_fields": captured_fields,
                "booking_link_sent_before": bool(state_before.get("booking_link_sent")),
                "booking_link_sent": bool(response_payload.get("booking_link_sent")),
                "booking_link_sent_after": bool(response_payload.get("booking_link_sent")),
                "attempted_booking_link_send": bool(
                    response_payload.get("contains_booking_url")
                ),
                "booking_link_send_blocked": bool(
                    response_payload.get("booking_link_sent")
                    and state_before.get("booking_link_sent")
                ),
                "contains_booking_url": bool(
                    response_payload.get("contains_booking_url")
                    or response_payload.get("contains_booking_link")
                ),
                "should_send_text": bool(response_payload.get("should_send_text")),
                "should_send_audio": bool(response_payload.get("should_send_audio")),
                "contains_booking_link": bool(
                    response_payload.get("contains_booking_link")
                ),
                "idle_reset_triggered": bool(response_payload.get("idle_reset_triggered")),
                "inactivity_gap_seconds": response_payload.get("inactivity_gap_seconds"),
                "handoff_triggered": response_payload.get("qualification_status") == "human_handoff",
                "onboarding_sent": (
                    "How to use this chat"
                    in str(response_payload.get("whatsapp_text") or "")
                    or "How to use this chat"
                    in str(response_payload.get("reply_text") or "")
                ),
                "reply_text": str(response_payload.get("reply_text") or "")[:200],
                "spoken_text": str(response_payload.get("spoken_text") or "")[:200],
            }
            if transcript is not None:
                log_context["transcript_text"] = transcript[:200]
            if user_message is not None:
                log_context["normalized_user_message"] = user_message[:200]
            log_qualification_event("qualification_turn_completed", **log_context)
        except Exception:
            return

    def _resolve_inbound_user_message(
        self,
        *,
        validated_data: dict[str, Any],
        input_channel: str,
        message_sid: str | None,
        conversation_language: str,
    ) -> tuple[str | None, str | None, dict[str, Any] | None]:
        """
        Normalize inbound text for the shared qualification handler.

        Voice notes with media always transcribe first; optional Body text is
        ignored when media is present so empty Twilio Body values do not bypass STT.
        """
        media_url = validated_data.get("media_url")
        media_content_type = validated_data.get("media_content_type")
        has_media = bool(media_url)
        log_context = {
            "input_channel": input_channel,
            "has_media": has_media,
            "media_content_type": media_content_type,
            "message_sid_prefix": message_sid_prefix(message_sid),
        }

        if input_channel == "whatsapp_text":
            message = validated_data.get("message")
            log_qualification_event(
                "qualification_inbound_message_resolved",
                normalized_user_message=(message or "")[:120],
                transcription_used=False,
                **log_context,
            )
            return message, None, None

        if has_media:
            log_qualification_event(
                "transcription_started",
                **log_context,
            )
            transcription_started = time.perf_counter()
            try:
                message = self._transcription_service.transcribe(
                    media_url=media_url,
                    media_content_type=media_content_type,
                    message_sid=message_sid,
                    conversation_language=conversation_language,
                )
            except ExtractStepFailure as exc:
                if "empty" in (exc.info.details or "").lower():
                    log_qualification_event(
                        "transcription_success",
                        transcription_success=False,
                        transcript_text_preview="",
                        handoff_triggered=False,
                        **log_context,
                    )
                    return None, None, build_voice_transcription_unclear_response(
                        whatsapp_number=validated_data["whatsapp_number"],
                        language=conversation_language,
                    )
                raise
            log_latency_step(
                "voice_transcription",
                elapsed_ms_since(transcription_started),
                message_sid=message_sid,
            )
            normalized = " ".join((message or "").split())
            if not normalized:
                log_qualification_event(
                    "transcription_success",
                    transcription_success=False,
                    transcript_text_preview="",
                    handoff_triggered=False,
                    **log_context,
                )
                return None, None, build_voice_transcription_unclear_response(
                    whatsapp_number=validated_data["whatsapp_number"],
                    language=conversation_language,
                )
            log_qualification_event(
                "transcription_success",
                transcription_success=True,
                transcript_text_preview=normalized[:120],
                normalized_user_message=normalized[:120],
                **log_context,
            )
            return normalized, normalized, None

        message = validated_data.get("message")
        normalized = " ".join((message or "").split()) or None
        log_qualification_event(
            "qualification_inbound_message_resolved",
            normalized_user_message=(normalized or "")[:120],
            transcription_used=False,
            **log_context,
        )
        return normalized, normalized if normalized else None, None

    def _deliver_booking_link_if_needed(
        self,
        response_payload: dict[str, Any],
        *,
        whatsapp_number: str,
        message_sid: str | None,
        input_channel: str,
    ) -> dict[str, Any]:
        delivery_started = time.perf_counter()
        updated = ensure_booking_link_delivery_on_response(
            response_payload,
            whatsapp_number=whatsapp_number,
            message_sid=message_sid,
            input_channel=input_channel,
        )
        log_latency_step(
            "booking_link_delivery",
            elapsed_ms_since(delivery_started),
            message_sid=message_sid,
            booking_link_sent=updated.get("booking_link_sent"),
        )
        return updated

    def _cache_and_return_gate_response(
        self,
        *,
        response_payload: dict[str, Any],
        message_sid: str | None,
        whatsapp_number: str,
        input_channel: str,
    ) -> dict[str, Any]:
        response_payload = self._deliver_booking_link_if_needed(
            response_payload,
            whatsapp_number=whatsapp_number,
            message_sid=message_sid,
            input_channel=input_channel,
        )
        self._touch_session_activity(whatsapp_number)
        if message_sid:
            cache_started = time.perf_counter()
            cache_turn_response(message_sid, response_payload)
            log_latency_step(
                "idempotency_cache_set",
                elapsed_ms_since(cache_started),
                message_sid=message_sid,
            )
        log_external_api_total(message_sid=message_sid)
        return response_payload

    def _try_early_menu_button_gate(
        self,
        validated_data: dict[str, Any],
        *,
        message_sid: str | None,
        whatsapp_number: str,
    ) -> dict[str, Any] | None:
        if not is_lead_qualification_enabled():
            return None

        menu_id, selection_debug = extract_menu_selection_payload(validated_data)
        if menu_id is None:
            return None

        gate_payload = dict(validated_data)
        gate_payload["button_payload"] = menu_id
        log_whatsapp_menu_event(
            "MENU_SELECTION_EXTRACTED",
            message_sid=message_sid,
            user_id=whatsapp_number,
            selected_menu_id=menu_id,
            resolved_menu_item_id=menu_id,
            channel=validated_data.get("input_channel"),
            raw_body=selection_debug.get("raw_body"),
            raw_button_payload=selection_debug.get("raw_button_payload"),
            fallback_used=selection_debug.get("fallback_used", False),
            **{
                k: v
                for k, v in selection_debug.items()
                if v is not None
                and k
                not in {
                    "raw_body",
                    "raw_button_payload",
                    "resolved_menu_item_id",
                    "fallback_used",
                }
            },
        )

        menu_started = time.perf_counter()
        menu_result = self._menu_service.evaluate_button_payload(gate_payload)
        log_latency_step(
            "whatsapp_menu_button_gate",
            elapsed_ms_since(menu_started),
            message_sid=message_sid,
            handled=menu_result.handled,
        )
        if not menu_result.handled:
            return None
        return self._cache_and_return_gate_response(
            response_payload=menu_result.response_payload or {},
            message_sid=message_sid,
            whatsapp_number=whatsapp_number,
            input_channel=validated_data["input_channel"],
        )

    def _try_menu_gate(
        self,
        validated_data: dict[str, Any],
        *,
        message_sid: str | None,
        transcript: str | None = None,
        whatsapp_number: str,
    ) -> dict[str, Any] | None:
        if not is_lead_qualification_enabled():
            return None
        menu_started = time.perf_counter()
        menu_result = self._menu_service.evaluate_turn(
            validated_data,
            transcript=transcript,
        )
        log_latency_step(
            "whatsapp_menu_gate",
            elapsed_ms_since(menu_started),
            message_sid=message_sid,
            handled=menu_result.handled,
        )
        if not menu_result.handled:
            return None
        return self._cache_and_return_gate_response(
            response_payload=menu_result.response_payload or {},
            message_sid=message_sid,
            whatsapp_number=whatsapp_number,
            input_channel=validated_data["input_channel"],
        )

    def _try_inactivity_menu_gate(
        self,
        validated_data: dict[str, Any],
        *,
        message_sid: str | None,
        transcript: str | None = None,
        whatsapp_number: str,
    ) -> dict[str, Any] | None:
        if not is_lead_qualification_enabled():
            return None
        inactivity_started = time.perf_counter()
        inactivity_result = self._menu_service.evaluate_inactivity(
            validated_data,
            transcript=transcript,
        )
        log_latency_step(
            "whatsapp_inactivity_menu_gate",
            elapsed_ms_since(inactivity_started),
            message_sid=message_sid,
            handled=inactivity_result.handled,
        )
        if not inactivity_result.handled:
            return None
        return self._cache_and_return_gate_response(
            response_payload=inactivity_result.response_payload or {},
            message_sid=message_sid,
            whatsapp_number=whatsapp_number,
            input_channel=validated_data["input_channel"],
        )

    def run_turn(self, validated_data: dict[str, Any]) -> dict[str, Any]:
        """
        Run one qualification turn and return the exact current endpoint
        response payload without any HTTP response object.
        """
        validated_data = dict(validated_data)
        whatsapp_number = normalize_whatsapp_session_number(validated_data["whatsapp_number"])
        validated_data["whatsapp_number"] = whatsapp_number

        message_sid = validated_data.get("message_sid")
        input_channel = validated_data["input_channel"]
        call_sid = validated_data.get("call_sid")
        utterance_id = validated_data.get("utterance_id")
        is_final = validated_data.get("is_final", True)
        reset_external_api_accumulator()
        reset_step_duration_tracker()

        # LiveKit / realtime STT: ignore interim/partial transcripts entirely.
        if is_final is False:
            log_qualification_event(
                "voice_partial_transcript_ignored",
                call_sid=call_sid,
                utterance_id=utterance_id,
                duplicate_detected=False,
                tts_enqueued=False,
            )
            return {
                "accepted_fields": get_accepted_fields(whatsapp_number),
                "rejected_fields": {},
                "human_handoff_requested": False,
                "next_field": None,
                "reply_text": "",
                "spoken_text": "",
                "whatsapp_text": "",
                "actions": [],
                "qualification_status": "in_progress",
                "conversation_language": get_conversation_language(whatsapp_number),
                "preferred_phone": None,
                "reply_mode": "voice" if input_channel == "whatsapp_voice_note" else "text",
                "send_booking_link": False,
                "booking_link_sent": False,
                "booking_link": None,
                "tts_enqueued": False,
                "duplicate_detected": False,
            }

        if message_sid:
            cached_complete = get_cached_turn_response(message_sid)
            if cached_complete is not None:
                response_payload = self._deliver_booking_link_if_needed(
                    dict(cached_complete),
                    whatsapp_number=whatsapp_number,
                    message_sid=message_sid,
                    input_channel=input_channel,
                )
                if response_payload != cached_complete and message_sid:
                    cache_turn_response(message_sid, response_payload)
                log_external_api_total(message_sid=message_sid)
                return response_payload

        lock_key = normalize_conversation_lock_key(whatsapp_number)
        lock_handle = acquire_conversation_turn_lock(lock_key)

        log_qualification_event(
            "qualification_conversation_lock",
            message_sid_prefix=message_sid_prefix(message_sid),
            whatsapp_number_prefix=whatsapp_number_prefix(whatsapp_number),
            lock_key_prefix=lock_key_prefix(lock_key),
            lock_acquired=lock_handle.acquired,
            lock_wait_ms=lock_handle.wait_ms,
            lock_timeout=lock_handle.timed_out,
            input_channel=input_channel,
            media_url_present=bool(validated_data.get("media_url")),
        )
        try:
            if lock_handle.timed_out:
                response_payload = build_conversation_lock_timeout_response(
                    whatsapp_number=whatsapp_number,
                    input_channel=input_channel,
                )
                log_qualification_event(
                    "qualification_conversation_lock",
                    message_sid_prefix=message_sid_prefix(message_sid),
                    whatsapp_number_prefix=whatsapp_number_prefix(whatsapp_number),
                    lock_key_prefix=lock_key_prefix(lock_key),
                    lock_released=True,
                    input_channel=input_channel,
                    media_url_present=bool(validated_data.get("media_url")),
                    response_sent_or_empty=True,
                )
                return response_payload

            return self._run_turn_under_conversation_lock(
                validated_data,
                whatsapp_number=whatsapp_number,
                message_sid=message_sid,
                input_channel=input_channel,
                call_sid=call_sid,
                utterance_id=utterance_id,
                is_final=is_final,
            )
        finally:
            lock_handle.release()
            log_qualification_event(
                "qualification_conversation_lock",
                message_sid_prefix=message_sid_prefix(message_sid),
                whatsapp_number_prefix=whatsapp_number_prefix(whatsapp_number),
                lock_key_prefix=lock_key_prefix(lock_key),
                lock_released=True,
                input_channel=input_channel,
                media_url_present=bool(validated_data.get("media_url")),
            )

    def _run_turn_under_conversation_lock(
        self,
        validated_data: dict[str, Any],
        *,
        whatsapp_number: str,
        message_sid: str | None,
        input_channel: str,
        call_sid: str | None,
        utterance_id: str | None,
        is_final: bool,
    ) -> dict[str, Any]:
        session, _created = get_or_create_conversation_session(
            whatsapp_number=whatsapp_number,
        )
        whatsapp_number = session.whatsapp_number
        validated_data = dict(validated_data)
        validated_data["whatsapp_number"] = whatsapp_number
        reconcile_stale_booking_link_sent_state(whatsapp_number=whatsapp_number)
        from apps.qualification.services.existing_customer_live_agent_service import (
            reconcile_stale_existing_customer_delivery_markers,
        )

        reconcile_stale_existing_customer_delivery_markers(
            whatsapp_number=whatsapp_number,
        )

        if message_sid:
            idempotency_started = time.perf_counter()
            cached_response = begin_idempotent_turn(message_sid)
            log_latency_step(
                "idempotency_lookup",
                elapsed_ms_since(idempotency_started),
                message_sid=message_sid,
                cache_hit=cached_response is not None,
            )
            if cached_response is not None:
                response_payload = self._deliver_booking_link_if_needed(
                    dict(cached_response),
                    whatsapp_number=whatsapp_number,
                    message_sid=message_sid,
                    input_channel=input_channel,
                )
                if response_payload != cached_response and message_sid:
                    cache_turn_response(message_sid, response_payload)
                log_external_api_total(message_sid=message_sid)
                return response_payload

        early_menu_response = self._try_early_menu_button_gate(
            validated_data,
            message_sid=message_sid,
            whatsapp_number=whatsapp_number,
        )
        if early_menu_response is not None:
            return early_menu_response

        # Idle reset must run before the language gate so a returning customer
        # (new or existing) is prompted for language on the same turn that
        # starts the new conversation cycle.
        previous_last_activity_at = session.last_message_at
        current_inbound_message_time = timezone.now()
        booking_link_sent_before = session.booking_link_sent_at is not None
        state_before = dict(get_accepted_fields(whatsapp_number))
        state_before["booking_link_sent"] = booking_link_sent_before
        idle_reset_triggered, inactivity_gap_seconds = self._maybe_apply_idle_reset_on_inbound(
            session=session,
            whatsapp_number=whatsapp_number,
            previous_last_activity_at=previous_last_activity_at,
            current_inbound_message_time=current_inbound_message_time,
            input_channel=input_channel,
            message_sid=message_sid,
        )
        if idle_reset_triggered:
            booking_link_sent_before = False
            state_before = {}
            state_before["booking_link_sent"] = False
            session.refresh_from_db()

        log_qualification_event(
            "language_gate_started",
            message_sid=message_sid,
            whatsapp_number_prefix=whatsapp_number[:6],
            input_channel=input_channel,
        )
        language_gate_started = time.perf_counter()
        gate_result = self._language_gate_service.evaluate_turn(validated_data)
        log_latency_step(
            "language_gate",
            elapsed_ms_since(language_gate_started),
            message_sid=message_sid,
            handled=gate_result.handled,
        )
        if gate_result.handled:
            response_payload = dict(gate_result.response_payload or {})
            if idle_reset_triggered:
                response_payload["idle_reset_triggered"] = True
                response_payload["inactivity_gap_seconds"] = inactivity_gap_seconds
            return self._cache_and_return_gate_response(
                response_payload=response_payload,
                message_sid=message_sid,
                whatsapp_number=whatsapp_number,
                input_channel=input_channel,
            )

        transcript: str | None = None
        conversation_language = get_conversation_language(whatsapp_number)
        session.refresh_from_db()

        message, transcript, unclear_response = self._resolve_inbound_user_message(
            validated_data=validated_data,
            input_channel=input_channel,
            message_sid=message_sid,
            conversation_language=conversation_language,
        )

        if unclear_response is not None:
            turn_response = unclear_response
            if idle_reset_triggered:
                turn_response = dict(turn_response)
                turn_response["idle_reset_triggered"] = True
            response_payload = finalize_turn_response(
                turn_response,
                input_channel=input_channel,
                transcript=transcript,
                conversation_language=conversation_language,
                whatsapp_number=whatsapp_number,
                user_message=message or "",
            )
            response_payload["idle_reset_triggered"] = idle_reset_triggered
            response_payload["inactivity_gap_seconds"] = inactivity_gap_seconds
            response_payload = self._attach_conversation_state(response_payload)
            self._log_turn_completed(
                input_channel=input_channel,
                response_payload=response_payload,
                state_before=state_before,
                whatsapp_number=whatsapp_number,
                transcript=transcript,
                user_message=message or "",
                button_payload=validated_data.get("button_payload"),
            )
            if message_sid:
                cache_turn_response(message_sid, response_payload)
            self._touch_session_activity(whatsapp_number)
            log_external_api_total(message_sid=message_sid)
            return response_payload

        voice_turn_key_active = False
        if call_sid and message and is_final is not False:
            cached_voice = begin_voice_utterance_turn(
                call_sid=call_sid,
                utterance_id=utterance_id,
                transcript=message,
            )
            if cached_voice is not None:
                duplicate = dict(cached_voice)
                duplicate["duplicate_detected"] = True
                duplicate["tts_enqueued"] = False
                log_external_api_total(message_sid=message_sid)
                return duplicate
            voice_turn_key_active = True

        if message:
            menu_payload = dict(validated_data)
            menu_payload["message"] = message
            menu_response = self._try_menu_gate(
                menu_payload,
                message_sid=message_sid,
                transcript=transcript,
                whatsapp_number=whatsapp_number,
            )
            if menu_response is not None:
                return menu_response

            inactivity_response = self._try_inactivity_menu_gate(
                menu_payload,
                message_sid=message_sid,
                transcript=transcript,
                whatsapp_number=whatsapp_number,
            )
            if inactivity_response is not None:
                return inactivity_response

        if not message:
            turn_response = build_voice_transcription_unclear_response(
                whatsapp_number=whatsapp_number,
                language=conversation_language,
            )
        elif is_qualification_complete(get_accepted_fields(whatsapp_number)):
            turn_response = build_completed_retry_response(
                whatsapp_number,
                language=conversation_language,
            )
        else:
            turn_handler_started = time.perf_counter()
            turn_response = self._turn_handler(
                whatsapp_number=whatsapp_number,
                message=message,
                message_sid=message_sid,
                for_voice=input_channel == "whatsapp_voice_note" or bool(call_sid),
                button_payload=validated_data.get("button_payload"),
            )
            log_latency_step(
                "qualification_turn_handler",
                elapsed_ms_since(turn_handler_started),
                message_sid=message_sid,
            )

        if idle_reset_triggered:
            turn_response = dict(turn_response)
            turn_response["idle_reset_triggered"] = True
            turn_response.pop("skip_onboarding_intro", None)

        if turn_response.get("status") == "waiting_for_live_agent":
            response_payload = dict(turn_response)
            response_payload["idle_reset_triggered"] = idle_reset_triggered
            response_payload["inactivity_gap_seconds"] = inactivity_gap_seconds
            response_payload = self._attach_conversation_state(response_payload)
            self._log_turn_completed(
                input_channel=input_channel,
                response_payload=response_payload,
                state_before=state_before,
                whatsapp_number=whatsapp_number,
                transcript=transcript,
                user_message=message or "",
                button_payload=validated_data.get("button_payload"),
            )
            return self._cache_and_return_gate_response(
                response_payload=response_payload,
                message_sid=message_sid,
                whatsapp_number=whatsapp_number,
                input_channel=input_channel,
            )

        finalize_started = time.perf_counter()
        turn_response = maybe_prepend_onboarding_intro(
            turn_response,
            whatsapp_number=whatsapp_number,
            language=conversation_language,
            input_channel=input_channel,
            session=session,
        )
        response_payload = finalize_turn_response(
            turn_response,
            input_channel=input_channel,
            transcript=transcript,
            conversation_language=conversation_language,
            whatsapp_number=whatsapp_number,
            user_message=message,
        )
        log_latency_step(
            "finalize_turn_response",
            elapsed_ms_since(finalize_started),
            message_sid=message_sid,
        )

        response_payload = self._deliver_booking_link_if_needed(
            response_payload,
            whatsapp_number=whatsapp_number,
            message_sid=message_sid,
            input_channel=input_channel,
        )
        response_payload["idle_reset_triggered"] = idle_reset_triggered
        response_payload["inactivity_gap_seconds"] = inactivity_gap_seconds
        response_payload = self._attach_conversation_state(response_payload)

        self._log_turn_completed(
            input_channel=input_channel,
            response_payload=response_payload,
            state_before=state_before,
            whatsapp_number=whatsapp_number,
            transcript=transcript,
            user_message=message,
            button_payload=validated_data.get("button_payload"),
        )

        if call_sid and message:
            # Exactly one TTS payload per successfully processed voice utterance.
            response_payload["tts_enqueued"] = bool(response_payload.get("spoken_text"))
            response_payload["duplicate_detected"] = False
            log_qualification_event(
                "voice_turn_tts_decision",
                call_sid=call_sid,
                utterance_id=utterance_id,
                transcript_hash=build_transcript_hash(message),
                duplicate_detected=False,
                tts_enqueued=response_payload["tts_enqueued"],
            )
            if voice_turn_key_active:
                cache_voice_utterance_response(
                    call_sid=call_sid,
                    utterance_id=utterance_id,
                    transcript=message,
                    response=response_payload,
                )

        if message_sid:
            cache_started = time.perf_counter()
            cache_turn_response(message_sid, response_payload)
            log_latency_step(
                "idempotency_cache_set",
                elapsed_ms_since(cache_started),
                message_sid=message_sid,
            )

        self._touch_session_activity(whatsapp_number)
        log_external_api_total(message_sid=message_sid)
        return response_payload
