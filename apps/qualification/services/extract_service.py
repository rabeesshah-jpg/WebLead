"""Qualification extract turn orchestration."""

from __future__ import annotations

import time
from typing import Any, Callable

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
from apps.qualification.message_idempotency import (
    begin_idempotent_turn,
    cache_turn_response,
)
from apps.qualification.qualification_turn import handle_qualification_turn
from apps.qualification.services.language_gate_service import LanguageGateService
from apps.qualification.services.transcription_service import VoiceNoteTranscriptionService

TurnHandler = Callable[..., dict[str, Any]]


class ExtractService:
    def __init__(
        self,
        *,
        transcription_service: VoiceNoteTranscriptionService | None = None,
        turn_handler: TurnHandler | None = None,
        language_gate_service: LanguageGateService | None = None,
    ) -> None:
        self._transcription_service = transcription_service or VoiceNoteTranscriptionService()
        self._turn_handler = turn_handler or handle_qualification_turn
        self._language_gate_service = language_gate_service or LanguageGateService()

    def run_turn(self, validated_data: dict[str, Any]) -> dict[str, Any]:
        """
        Run one qualification turn and return the exact current endpoint
        response payload without any HTTP response object.
        """
        message_sid = validated_data.get("message_sid")
        whatsapp_number = validated_data["whatsapp_number"]
        input_channel = validated_data["input_channel"]
        reset_external_api_accumulator()
        reset_step_duration_tracker()

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
                log_external_api_total(message_sid=message_sid)
                return cached_response

        language_gate_started = time.perf_counter()
        gate_result = self._language_gate_service.evaluate_turn(validated_data)
        log_latency_step(
            "language_gate",
            elapsed_ms_since(language_gate_started),
            message_sid=message_sid,
            handled=gate_result.handled,
        )
        if gate_result.handled:
            response_payload = gate_result.response_payload or {}
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

        transcript: str | None = None
        conversation_language = get_conversation_language(whatsapp_number)

        if is_qualification_complete(get_accepted_fields(whatsapp_number)):
            turn_response = build_completed_retry_response(
                whatsapp_number,
                language=conversation_language,
            )
        else:
            if input_channel == "whatsapp_text":
                message = validated_data["message"]
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

            if input_channel == "whatsapp_voice_note":
                transcript = message

            turn_handler_started = time.perf_counter()
            turn_response = self._turn_handler(
                whatsapp_number=whatsapp_number,
                message=message,
                message_sid=message_sid,
            )
            log_latency_step(
                "qualification_turn_handler",
                elapsed_ms_since(turn_handler_started),
                message_sid=message_sid,
            )

        finalize_started = time.perf_counter()
        response_payload = finalize_turn_response(
            turn_response,
            input_channel=input_channel,
            transcript=transcript,
            conversation_language=conversation_language,
        )
        log_latency_step(
            "finalize_turn_response",
            elapsed_ms_since(finalize_started),
            message_sid=message_sid,
        )

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
