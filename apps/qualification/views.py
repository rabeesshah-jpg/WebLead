"""Internal qualification API views."""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.parse import urlparse

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.qualification.api.logging import log_qualification_request_event
from apps.qualification.channels import (
    VALID_INPUT_CHANNELS,
    finalize_turn_response,
    InputChannel,
)
from apps.qualification.core.legacy_compat import (
    QualificationTurnRequest,
    download_twilio_media,
    transcribe_audio,
)
from apps.qualification.deepgram_client import (
    DeepgramConfigurationError,
    DeepgramRequestError,
    DeepgramResponseError,
    DeepgramTimeoutError,
    normalize_audio_content_type,
)
from apps.qualification.domain.constants import TWILIO_INBOUND_MESSAGE_SID_PATTERN
from apps.qualification.domain.logging_utils import message_sid_prefix
from apps.qualification.domain.validators import is_valid_e164_phone_number
from apps.qualification.internal_auth import is_internal_qualification_authorized
from apps.qualification.domain.extract_errors import ExtractStepFailure
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
from apps.qualification.twilio_media import (
    TwilioMediaConfigurationError,
    TwilioMediaRequestError,
    TwilioMediaTimeoutError,
    TwilioMediaUnauthorizedError,
)
from apps.qualification.voice_note_config import VoiceNoteConfigurationError, validate_voice_note_dependencies
from apps.qualification.voice_note_logging import log_voice_note_event

logger = logging.getLogger("apps.qualification")

ALLOWED_REQUEST_FIELDS = frozenset(
    {
        "message",
        "whatsapp_number",
        "input_channel",
        "message_sid",
        "media_url",
        "media_content_type",
        "button_payload",
        "button_text",
        "button_type",
    },
)
class InvalidExtractRequestError(ValueError):
    """Raised when the internal extract request body is invalid."""


def _normalize_optional_string(value: Any) -> str | None:
    """Normalize optional string fields; JSON null becomes None."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidExtractRequestError
    stripped = value.strip()
    return stripped if stripped else None


def _log_event(request: HttpRequest, event: str, *, level: int = logging.INFO) -> None:
    log_qualification_request_event(request, event, level=level)


def _safe_failure_type(exc: BaseException) -> str:
    """Return a safe exception label for internal logs without sensitive details."""
    cause = exc.__cause__
    if cause is not None:
        return f"{type(exc).__name__}:{type(cause).__name__}"
    return type(exc).__name__


def _message_sid_prefix(message_sid: str | None) -> str | None:
    return message_sid_prefix(message_sid)


def _log_service_unavailable(
    request: HttpRequest,
    exc: BaseException,
    *,
    turn_request: QualificationTurnRequest | None = None,
) -> None:
    payload: dict[str, Any] = {
        "event": "qualification_internal_service_unavailable",
        "timestamp": timezone.now().isoformat(),
        "request_path": request.path,
        "failure_type": _safe_failure_type(exc),
    }
    if turn_request is not None:
        payload["input_channel"] = turn_request.input_channel
        sid_prefix = _message_sid_prefix(turn_request.message_sid)
        if sid_prefix:
            payload["message_sid_prefix"] = sid_prefix
    logger.error(json.dumps(payload, separators=(",", ":")))


def _log_upstream_request_failed(
    request: HttpRequest,
    exc: BaseException,
    *,
    turn_request: QualificationTurnRequest | None = None,
) -> None:
    payload: dict[str, Any] = {
        "event": "qualification_internal_upstream_failed",
        "timestamp": timezone.now().isoformat(),
        "request_path": request.path,
        "failure_type": _safe_failure_type(exc),
    }
    if turn_request is not None:
        payload["input_channel"] = turn_request.input_channel
        sid_prefix = _message_sid_prefix(turn_request.message_sid)
        if sid_prefix:
            payload["message_sid_prefix"] = sid_prefix
    logger.error(json.dumps(payload, separators=(",", ":")))


def _has_voice_media_url(payload: dict[str, Any]) -> bool:
    return _normalize_optional_string(payload.get("media_url")) is not None


def _parse_input_channel(payload: dict[str, Any]) -> InputChannel:
    if "input_channel" in payload:
        raw_channel = payload["input_channel"]
        if not isinstance(raw_channel, str) or raw_channel not in VALID_INPUT_CHANNELS:
            raise InvalidExtractRequestError
        return raw_channel  # type: ignore[return-value]

    if _has_voice_media_url(payload) and not _parse_optional_message(payload):
        return "whatsapp_voice_note"
    return "whatsapp_text"


def _parse_message_sid(payload: dict[str, Any]) -> str | None:
    if "message_sid" not in payload:
        return None

    message_sid = payload["message_sid"]
    if message_sid is None:
        return None
    if not isinstance(message_sid, str) or not TWILIO_INBOUND_MESSAGE_SID_PATTERN.fullmatch(message_sid):
        raise InvalidExtractRequestError
    return message_sid


def _parse_media_url(payload: dict[str, Any], *, required: bool) -> str | None:
    if "media_url" not in payload:
        if required:
            raise InvalidExtractRequestError
        return None

    media_url = _normalize_optional_string(payload["media_url"])
    if media_url is None:
        if required:
            raise InvalidExtractRequestError
        return None

    parsed = urlparse(media_url)
    if parsed.scheme != "https":
        raise InvalidExtractRequestError
    return media_url


def _parse_media_content_type(payload: dict[str, Any], *, required: bool) -> str | None:
    if "media_content_type" not in payload:
        if required:
            raise InvalidExtractRequestError
        return None

    media_content_type = _normalize_optional_string(payload["media_content_type"])
    if media_content_type is None:
        if required:
            raise InvalidExtractRequestError
        return None

    if not media_content_type.startswith("audio/"):
        raise InvalidExtractRequestError
    return media_content_type


def _parse_optional_message(payload: dict[str, Any]) -> str | None:
    if "message" not in payload:
        return None

    message = payload["message"]
    if message is None:
        return None
    if not isinstance(message, str):
        raise InvalidExtractRequestError
    return message.strip() or None


def _parse_extract_request(raw_body: bytes) -> QualificationTurnRequest:
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise InvalidExtractRequestError from exc

    if not isinstance(payload, dict):
        raise InvalidExtractRequestError

    extra_keys = set(payload) - ALLOWED_REQUEST_FIELDS
    if extra_keys:
        raise InvalidExtractRequestError

    if "whatsapp_number" not in payload:
        raise InvalidExtractRequestError

    whatsapp_number = payload["whatsapp_number"]
    if not isinstance(whatsapp_number, str):
        raise InvalidExtractRequestError

    normalized_phone = "".join(whatsapp_number.split())
    if not is_valid_e164_phone_number(normalized_phone):
        raise InvalidExtractRequestError

    input_channel = _parse_input_channel(payload)
    message_sid = _parse_message_sid(payload)
    normalized_message = _parse_optional_message(payload)
    has_media_url = _has_voice_media_url(payload)

    if input_channel == "whatsapp_text":
        if not normalized_message:
            if has_media_url:
                raise InvalidExtractRequestError
            raise InvalidExtractRequestError
        return QualificationTurnRequest(
            whatsapp_number=normalized_phone,
            message=normalized_message,
            input_channel=input_channel,
            message_sid=message_sid,
            media_url=None,
            media_content_type=None,
        )

    media_url = _parse_media_url(payload, required=True)
    if media_url is None:
        if not normalized_message:
            raise InvalidExtractRequestError
        raise InvalidExtractRequestError
    if message_sid is None:
        raise InvalidExtractRequestError

    media_content_type = _parse_media_content_type(payload, required=False) or "audio/ogg"

    return QualificationTurnRequest(
        whatsapp_number=normalized_phone,
        message=normalized_message,
        input_channel=input_channel,
        message_sid=message_sid,
        media_url=media_url,
        media_content_type=media_content_type,
    )


def _resolve_turn_message(turn_request: QualificationTurnRequest) -> str:
    if turn_request.input_channel == "whatsapp_text":
        assert turn_request.message is not None
        return turn_request.message

    if turn_request.message:
        return turn_request.message

    assert turn_request.media_url is not None
    assert turn_request.media_content_type is not None

    try:
        validate_voice_note_dependencies()
    except VoiceNoteConfigurationError as exc:
        log_voice_note_event(
            exc.log_event,
            message_sid=turn_request.message_sid,
            media_content_type=turn_request.media_content_type,
        )
        if exc.log_event == "qualification_voice_missing_twilio_credentials":
            raise TwilioMediaConfigurationError(str(exc)) from exc
        raise DeepgramConfigurationError(str(exc)) from exc

    download_started = time.perf_counter()
    try:
        audio_bytes, downloaded_content_type = download_twilio_media(turn_request.media_url)
    except TwilioMediaUnauthorizedError as exc:
        log_voice_note_event(
            "qualification_voice_twilio_download_unauthorized",
            message_sid=turn_request.message_sid,
            media_content_type=turn_request.media_content_type,
            http_status=getattr(exc.__cause__, "code", None),
            elapsed_ms=int((time.perf_counter() - download_started) * 1000),
        )
        raise
    except TwilioMediaTimeoutError:
        log_voice_note_event(
            "qualification_voice_twilio_download_timeout",
            message_sid=turn_request.message_sid,
            media_content_type=turn_request.media_content_type,
            elapsed_ms=int((time.perf_counter() - download_started) * 1000),
        )
        raise
    except TwilioMediaRequestError as exc:
        log_voice_note_event(
            "qualification_voice_twilio_download_failed",
            message_sid=turn_request.message_sid,
            media_content_type=turn_request.media_content_type,
            http_status=getattr(exc.__cause__, "code", None),
            elapsed_ms=int((time.perf_counter() - download_started) * 1000),
        )
        raise

    effective_content_type = normalize_audio_content_type(
        downloaded_content_type or turn_request.media_content_type,
    )
    try:
        transcription_started = time.perf_counter()
        transcript = transcribe_audio(
            audio_bytes,
            content_type=effective_content_type,
        )
    except DeepgramTimeoutError:
        log_voice_note_event(
            "qualification_voice_deepgram_timeout",
            message_sid=turn_request.message_sid,
            media_content_type=effective_content_type,
            elapsed_ms=int((time.perf_counter() - transcription_started) * 1000),
        )
        raise
    except DeepgramRequestError as exc:
        log_voice_note_event(
            "qualification_voice_deepgram_request_failed",
            message_sid=turn_request.message_sid,
            media_content_type=effective_content_type,
            http_status=getattr(exc.__cause__, "code", None),
            elapsed_ms=int((time.perf_counter() - transcription_started) * 1000),
        )
        raise
    except DeepgramResponseError as exc:
        event = (
            "qualification_voice_transcription_empty"
            if "empty" in str(exc).lower()
            else "qualification_voice_deepgram_invalid_response"
        )
        log_voice_note_event(
            event,
            message_sid=turn_request.message_sid,
            media_content_type=effective_content_type,
            elapsed_ms=int((time.perf_counter() - transcription_started) * 1000),
        )
        raise

    return transcript


def _build_success_response(
    *,
    turn_request: QualificationTurnRequest,
    turn_response: dict[str, Any],
    transcript: str | None,
) -> dict[str, Any]:
    return finalize_turn_response(
        turn_response,
        input_channel=turn_request.input_channel,
        transcript=transcript,
    )


def _validated_data_from_turn_request(turn_request: QualificationTurnRequest) -> dict[str, Any]:
    return {
        "whatsapp_number": turn_request.whatsapp_number,
        "message": turn_request.message,
        "input_channel": turn_request.input_channel,
        "message_sid": turn_request.message_sid,
        "media_url": turn_request.media_url,
        "media_content_type": turn_request.media_content_type,
    }


@csrf_exempt
@require_POST
def internal_qualification_extract(request: HttpRequest) -> JsonResponse:
    if not settings.N8N_QUALIFICATION_API_SECRET:
        _log_event(request, "qualification_internal_service_unavailable", level=logging.ERROR)
        return JsonResponse(
            {"error": "Qualification service is unavailable."},
            status=503,
        )

    if not is_internal_qualification_authorized(request):
        _log_event(request, "qualification_internal_auth_failed", level=logging.WARNING)
        return JsonResponse({"error": "Forbidden."}, status=403)

    try:
        turn_request = _parse_extract_request(request.body)
    except InvalidExtractRequestError:
        _log_event(request, "qualification_internal_invalid_request", level=logging.WARNING)
        return JsonResponse({"error": "Invalid request."}, status=400)

    try:
        response_payload = ExtractService().run_turn(_validated_data_from_turn_request(turn_request))
    except (
        TwilioMediaConfigurationError,
        DeepgramConfigurationError,
        QualificationServiceUnavailableError,
        LanguageGateConfigurationError,
    ) as exc:
        _log_service_unavailable(request, exc, turn_request=turn_request)
        return JsonResponse(
            {"error": "Qualification service is unavailable."},
            status=503,
        )
    except LanguageGateSendError as exc:
        _log_upstream_request_failed(request, exc, turn_request=turn_request)
        return JsonResponse(
            {"error": "Qualification service request failed."},
            status=502,
        )
    except ExtractStepFailure as exc:
        return JsonResponse({"error": exc.info.public_message}, status=502)
    except QualificationServiceRequestError as exc:
        _log_upstream_request_failed(request, exc, turn_request=turn_request)
        return JsonResponse(
            {"error": "Qualification service request failed."},
            status=502,
        )
    except QualificationTurnProcessingError:
        _log_event(request, "qualification_internal_unexpected_error", level=logging.ERROR)
        return JsonResponse({"error": "Internal server error."}, status=500)
    except Exception:
        _log_event(request, "qualification_internal_unexpected_error", level=logging.ERROR)
        return JsonResponse({"error": "Internal server error."}, status=500)

    return JsonResponse(response_payload, status=200)
