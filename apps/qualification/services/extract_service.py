"""Qualification extract turn orchestration."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from django.utils import timezone

from apps.qualification.channels import finalize_turn_response
from apps.qualification.conversation_flow import (
    build_completed_retry_response,
    is_qualification_complete,
)
from apps.qualification.conversation_state import get_accepted_fields
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
from apps.qualification.domain.onboarding import (
    compute_inactivity_gap_seconds,
    maybe_prepend_onboarding_intro,
    should_reset_qualification_after_inactivity,
)
from apps.qualification.message_idempotency import (
    begin_idempotent_turn,
    cache_turn_response,
    get_cached_turn_response,
)
from apps.qualification.qualification_turn import handle_qualification_turn
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
        self._turn_handler = turn_handler or handle_qualification_turn
        self._language_gate_service = language_gate_service or LanguageGateService()
        self._menu_service = menu_service or WhatsAppMenuService()

    def _touch_session_activity(self, whatsapp_number: str) -> None:
        session, _ = get_or_create_conversation_session(whatsapp_number=whatsapp_number)
        touch_session_last_message_at(session)

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
            from apps.qualification.api.logging import log_qualification_event

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
        from apps.qualification.api.logging import log_qualification_event

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

        language_gate_started = time.perf_counter()
        gate_result = self._language_gate_service.evaluate_turn(validated_data)
        log_latency_step(
            "language_gate",
            elapsed_ms_since(language_gate_started),
            message_sid=message_sid,
            handled=gate_result.handled,
        )
        if gate_result.handled:
            return self._cache_and_return_gate_response(
                response_payload=gate_result.response_payload or {},
                message_sid=message_sid,
                whatsapp_number=whatsapp_number,
                input_channel=input_channel,
            )

        transcript: str | None = None
        conversation_language = get_conversation_language(whatsapp_number)

        if input_channel == "whatsapp_text":
            message = validated_data.get("message")
        elif validated_data.get("message"):
            message = validated_data["message"]
        else:
            transcription_started = time.perf_counter()
            message = self._transcription_service.transcribe(
                media_url=validated_data["media_url"],
                media_content_type=validated_data["media_content_type"],
                message_sid=message_sid,
                conversation_language=conversation_language,
            )
            log_latency_step(
                "voice_transcription",
                elapsed_ms_since(transcription_started),
                message_sid=message_sid,
            )

        if input_channel == "whatsapp_voice_note" and message:
            transcript = message

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

        session, _ = get_or_create_conversation_session(whatsapp_number=whatsapp_number)
        session.refresh_from_db()
        previous_last_activity_at = session.last_message_at
        inactivity_gap_seconds = compute_inactivity_gap_seconds(session)
        idle_reset_triggered = should_reset_qualification_after_inactivity(session)
        state_before_reset = dict(get_accepted_fields(whatsapp_number))
        if idle_reset_triggered:
            from apps.qualification.api.logging import log_qualification_event

            reset_qualification_progress_after_inactivity(
                whatsapp_number=whatsapp_number,
                session=session,
            )
            session.refresh_from_db()
            log_qualification_event(
                "qualification_idle_reset",
                whatsapp_number_prefix=whatsapp_number_prefix(whatsapp_number),
                message_sid_prefix=message_sid_prefix(message_sid),
                previous_last_activity_at=(
                    previous_last_activity_at.isoformat()
                    if previous_last_activity_at is not None
                    else None
                ),
                current_message_time=timezone.now().isoformat(),
                inactivity_gap_seconds=inactivity_gap_seconds,
                idle_reset_triggered=True,
                state_before_reset=state_before_reset,
                state_after_reset={},
                onboarding_allowed=True,
            )
            log_qualification_event(
                "qualification_reset_after_inactivity",
                whatsapp_number_prefix=whatsapp_number_prefix(whatsapp_number),
                message_sid_prefix=message_sid_prefix(message_sid),
            )

        if is_qualification_complete(get_accepted_fields(whatsapp_number)):
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

        if call_sid and message:
            from apps.qualification.api.logging import log_qualification_event

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
