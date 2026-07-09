"""DRF views for qualification internal APIs."""

from __future__ import annotations

import logging
import time
from typing import Any

from django.conf import settings
from rest_framework.exceptions import ParseError, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.qualification.api.authentication import QualificationInternalAuthentication
from apps.qualification.api.exceptions import (
    FORBIDDEN_ERROR,
    INTERNAL_SERVER_ERROR,
    INVALID_REQUEST_ERROR,
    QUALIFICATION_LLM_REQUEST_FAILED_ERROR,
    SERVICE_REQUEST_FAILED_ERROR,
    SERVICE_UNAVAILABLE_ERROR,
    error_response,
)
from apps.qualification.api.logging import (
    log_qualification_request_event,
    log_service_unavailable,
    log_upstream_request_failed,
)
from apps.qualification.api.permissions import InternalWebhookSecretPermission, VoiceEventSecretPermission
from apps.qualification.api.serializers import (
    ExtractRequestSerializer,
    ExtractResponseSerializer,
    RenderAudioRequestSerializer,
    RenderAudioResponseSerializer,
    VoiceCallCompletedRequestSerializer,
    VoiceCallCompletedResponseSerializer,
)
from apps.qualification.deepgram_client import DeepgramConfigurationError
from apps.qualification.core.legacy_compat import QualificationTurnRequest
from apps.qualification.domain.extract_errors import ExtractStepFailure
from apps.qualification.domain.latency_profiling import (
    elapsed_ms_since,
    get_tracked_step_durations,
    log_latency_step,
    log_voice_turn_latency_summary,
    store_pending_voice_turn_summary,
)
from apps.qualification.qualification_turn import (
    QualificationServiceRequestError,
    QualificationServiceUnavailableError,
    QualificationTurnProcessingError,
)
from apps.qualification.services.extract_service import ExtractService
from apps.qualification.services.language_gate_service import (
    LanguageGateConfigurationError,
    LanguageGateSendError,
)
from apps.qualification.services.render_audio_service import RenderAudioService
from apps.qualification.services.voice_call_completed_service import (
    VoiceCallCompletedSendError,
    VoiceCallCompletedService,
)
from apps.qualification.twilio_media import TwilioMediaConfigurationError
from apps.qualification.whatsapp_audio import InvalidRenderAudioRequestError


class ExtractAPIView(APIView):
    authentication_classes = [QualificationInternalAuthentication]
    permission_classes = [InternalWebhookSecretPermission]
    service_class = ExtractService

    def get_service(self) -> ExtractService:
        return self.service_class()

    @staticmethod
    def _turn_request_from_validated(validated_data: dict[str, Any]) -> QualificationTurnRequest:
        return QualificationTurnRequest(
            whatsapp_number=validated_data["whatsapp_number"],
            message=validated_data.get("message"),
            input_channel=validated_data["input_channel"],
            message_sid=validated_data.get("message_sid"),
            media_url=validated_data.get("media_url"),
            media_content_type=validated_data.get("media_content_type"),
            call_sid=validated_data.get("call_sid"),
            utterance_id=validated_data.get("utterance_id"),
            is_final=validated_data.get("is_final", True),
            event_source=validated_data.get("event_source"),
        )

    def dispatch(self, request, *args, **kwargs):
        if not settings.N8N_QUALIFICATION_API_SECRET:
            log_qualification_request_event(
                request,
                "qualification_internal_service_unavailable",
                level=logging.ERROR,
            )
            request = self.initialize_request(request, *args, **kwargs)
            self.request = request
            self.headers = self.default_response_headers
            return self.finalize_response(
                request,
                error_response(SERVICE_UNAVAILABLE_ERROR, 503),
                *args,
                **kwargs,
            )
        return super().dispatch(request, *args, **kwargs)

    def permission_denied(self, request, message=None, code=None):
        log_qualification_request_event(request, "qualification_internal_auth_failed", level=logging.WARNING)
        raise PermissionDenied(detail=FORBIDDEN_ERROR)

    def http_method_not_allowed(self, request, *args, **kwargs):
        return Response(status=405)

    def post(self, request: Request) -> Response:
        api_started = time.perf_counter()
        message_sid: str | None = None

        try:
            payload = request.data
        except ParseError:
            log_qualification_request_event(request, "qualification_internal_invalid_request", level=logging.WARNING)
            return error_response(INVALID_REQUEST_ERROR, 400)

        if not isinstance(payload, dict):
            log_qualification_request_event(request, "qualification_internal_invalid_request", level=logging.WARNING)
            return error_response(INVALID_REQUEST_ERROR, 400)

        validation_started = time.perf_counter()
        serializer = ExtractRequestSerializer(data=payload)
        if not serializer.is_valid():
            raw_message_sid = payload.get("message_sid") if isinstance(payload.get("message_sid"), str) else None
            log_qualification_request_event(
                request,
                "qualification_internal_invalid_request",
                level=logging.WARNING,
                message_sid=raw_message_sid,
                validation_error_fields=sorted(serializer.errors.keys()),
            )
            return error_response(INVALID_REQUEST_ERROR, 400)

        validated_data = serializer.validated_data
        message_sid = validated_data.get("message_sid")
        log_latency_step(
            "serializer_validation",
            elapsed_ms_since(validation_started),
            message_sid=message_sid,
        )
        turn_request = self._turn_request_from_validated(validated_data)

        try:
            service_started = time.perf_counter()
            result = self.get_service().run_turn(validated_data)
            log_latency_step(
                "extract_service_run_turn",
                elapsed_ms_since(service_started),
                message_sid=message_sid,
            )
        except (
            TwilioMediaConfigurationError,
            DeepgramConfigurationError,
            QualificationServiceUnavailableError,
            LanguageGateConfigurationError,
        ) as exc:
            log_service_unavailable(request, exc, turn_request=turn_request)
            return error_response(SERVICE_UNAVAILABLE_ERROR, 503)
        except LanguageGateSendError as exc:
            log_upstream_request_failed(request, exc, turn_request=turn_request)
            return error_response(SERVICE_REQUEST_FAILED_ERROR, 502)
        except ExtractStepFailure as exc:
            return error_response(exc.info.public_message, 502)
        except QualificationServiceRequestError as exc:
            log_upstream_request_failed(request, exc, turn_request=turn_request)
            return error_response(QUALIFICATION_LLM_REQUEST_FAILED_ERROR, 502)
        except QualificationTurnProcessingError:
            log_qualification_request_event(request, "qualification_internal_unexpected_error", level=logging.ERROR)
            return error_response(INTERNAL_SERVER_ERROR, 500)
        except Exception:
            log_qualification_request_event(request, "qualification_internal_unexpected_error", level=logging.ERROR)
            return error_response(INTERNAL_SERVER_ERROR, 500)

        response_serializer = ExtractResponseSerializer(instance=result)
        api_total_ms = elapsed_ms_since(api_started)
        log_latency_step(
            "api_total",
            api_total_ms,
            message_sid=message_sid,
        )
        if result.get("status") in ("awaiting_language_selection", "awaiting_menu_selection"):
            return Response(result, status=200)

        if (
            validated_data.get("input_channel") == "whatsapp_voice_note"
            and message_sid
        ):
            store_pending_voice_turn_summary(
                message_sid,
                step_durations=get_tracked_step_durations(),
                extract_api_total_ms=api_total_ms,
            )
        return Response(response_serializer.data, status=200)


class RenderAudioAPIView(APIView):
    authentication_classes = [QualificationInternalAuthentication]
    permission_classes = [InternalWebhookSecretPermission]
    service_class = RenderAudioService

    def get_service(self) -> RenderAudioService:
        return self.service_class()

    def dispatch(self, request, *args, **kwargs):
        if not settings.N8N_QUALIFICATION_API_SECRET:
            log_qualification_request_event(
                request,
                "qualification_render_audio_service_unavailable",
                level=logging.ERROR,
            )
            request = self.initialize_request(request, *args, **kwargs)
            self.request = request
            self.headers = self.default_response_headers
            return self.finalize_response(
                request,
                error_response(SERVICE_UNAVAILABLE_ERROR, 503),
                *args,
                **kwargs,
            )
        return super().dispatch(request, *args, **kwargs)

    def permission_denied(self, request, message=None, code=None):
        log_qualification_request_event(request, "qualification_render_audio_auth_failed", level=logging.WARNING)
        raise PermissionDenied(detail=FORBIDDEN_ERROR)

    def http_method_not_allowed(self, request, *args, **kwargs):
        return Response(status=405)

    def post(self, request: Request) -> Response:
        api_started = time.perf_counter()

        try:
            payload = request.data
        except ParseError:
            log_qualification_request_event(
                request,
                "qualification_render_audio_invalid_request",
                level=logging.WARNING,
            )
            return error_response(INVALID_REQUEST_ERROR, 400)

        if not isinstance(payload, dict):
            log_qualification_request_event(
                request,
                "qualification_render_audio_invalid_request",
                level=logging.WARNING,
            )
            return error_response(INVALID_REQUEST_ERROR, 400)

        validation_started = time.perf_counter()
        serializer = RenderAudioRequestSerializer(data=payload)
        if not serializer.is_valid():
            log_qualification_request_event(
                request,
                "qualification_render_audio_invalid_request",
                level=logging.WARNING,
            )
            return error_response(INVALID_REQUEST_ERROR, 400)

        log_latency_step("serializer_validation", elapsed_ms_since(validation_started))

        try:
            render_started = time.perf_counter()
            result = self.get_service().render(serializer.validated_data)
            tts_generation_ms = elapsed_ms_since(render_started)
            log_latency_step(
                "tts_generation",
                tts_generation_ms,
                message_sid=serializer.validated_data.get("request_id"),
            )
        except InvalidRenderAudioRequestError:
            log_qualification_request_event(
                request,
                "qualification_render_audio_invalid_request",
                level=logging.WARNING,
            )
            return error_response(INVALID_REQUEST_ERROR, 400)
        except Exception:
            log_qualification_request_event(
                request,
                "qualification_render_audio_unexpected_error",
                level=logging.ERROR,
            )
            return error_response(INTERNAL_SERVER_ERROR, 500)

        response_serializer = RenderAudioResponseSerializer(instance=result)
        render_api_total_ms = elapsed_ms_since(api_started)
        log_latency_step("api_total", render_api_total_ms)
        request_id = serializer.validated_data.get("request_id")
        if request_id:
            log_voice_turn_latency_summary(
                request_id,
                tts_generation_ms=tts_generation_ms,
                render_api_total_ms=render_api_total_ms,
            )
        return Response(response_serializer.data, status=200)


class VoiceCallCompletedAPIView(APIView):
    authentication_classes = [QualificationInternalAuthentication]
    permission_classes = [VoiceEventSecretPermission]
    service_class = VoiceCallCompletedService

    def get_service(self) -> VoiceCallCompletedService:
        return self.service_class()

    def dispatch(self, request, *args, **kwargs):
        if not settings.WEBLEAD_VOICE_EVENT_SECRET:
            log_qualification_request_event(
                request,
                "voice_call_completed_service_unavailable",
                level=logging.ERROR,
            )
            request = self.initialize_request(request, *args, **kwargs)
            self.request = request
            self.headers = self.default_response_headers
            return self.finalize_response(
                request,
                error_response(SERVICE_UNAVAILABLE_ERROR, 503),
                *args,
                **kwargs,
            )
        return super().dispatch(request, *args, **kwargs)

    def permission_denied(self, request, message=None, code=None):
        log_qualification_request_event(request, "voice_call_completed_auth_failed", level=logging.WARNING)
        raise PermissionDenied(detail=FORBIDDEN_ERROR)

    def http_method_not_allowed(self, request, *args, **kwargs):
        return Response(status=405)

    def post(self, request: Request) -> Response:
        try:
            payload = request.data
        except ParseError:
            log_qualification_request_event(
                request,
                "voice_call_completed_invalid_request",
                level=logging.WARNING,
            )
            return error_response(INVALID_REQUEST_ERROR, 400)

        if not isinstance(payload, dict):
            log_qualification_request_event(
                request,
                "voice_call_completed_invalid_request",
                level=logging.WARNING,
            )
            return error_response(INVALID_REQUEST_ERROR, 400)

        serializer = VoiceCallCompletedRequestSerializer(data=payload)
        if not serializer.is_valid():
            event_id = payload.get("event_id") if isinstance(payload.get("event_id"), str) else None
            call_id = payload.get("call_id") if isinstance(payload.get("call_id"), str) else None
            whatsapp_errors = serializer.errors.get("whatsapp_number")
            log_qualification_request_event(
                request,
                "voice_call_completed_invalid_request",
                level=logging.WARNING,
                event_id=event_id,
                call_id=call_id,
                validation_error_fields=sorted(serializer.errors.keys()),
                whatsapp_number_invalid=bool(whatsapp_errors),
            )
            return error_response(INVALID_REQUEST_ERROR, 400)

        validated_data = serializer.validated_data
        try:
            result = self.get_service().process(validated_data)
        except VoiceCallCompletedSendError:
            log_qualification_request_event(
                request,
                "voice_call_completed_send_failed",
                level=logging.ERROR,
                event_id=validated_data["event_id"],
                call_id=validated_data["call_id"],
            )
            return error_response(SERVICE_REQUEST_FAILED_ERROR, 502)
        except Exception:
            log_qualification_request_event(
                request,
                "voice_call_completed_unexpected_error",
                level=logging.ERROR,
                event_id=validated_data["event_id"],
                call_id=validated_data["call_id"],
            )
            return error_response(INTERNAL_SERVER_ERROR, 500)

        response_serializer = VoiceCallCompletedResponseSerializer(instance=result)
        return Response(response_serializer.data, status=200)
