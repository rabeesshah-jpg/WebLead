"""Internal render-audio API view."""

from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.qualification.internal_auth import is_internal_qualification_authorized
from apps.qualification.whatsapp_audio import (
    DEFAULT_LANG,
    DEFAULT_VOICE,
    InvalidRenderAudioRequestError,
    RenderAudioProcessingError,
    RenderAudioServiceUnavailableError,
    render_whatsapp_voice_reply_safe,
    sanitize_request_id,
    validate_text_length,
)

logger = logging.getLogger("apps.qualification")

ALLOWED_RENDER_AUDIO_FIELDS = frozenset({"text", "voice", "lang", "request_id"})


def _log_event(request: HttpRequest, event: str, *, level: int = logging.INFO) -> None:
    payload = {
        "event": event,
        "timestamp": timezone.now().isoformat(),
        "request_path": request.path,
    }
    logger.log(level, json.dumps(payload, separators=(",", ":")))


def _parse_render_audio_request(raw_body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise InvalidRenderAudioRequestError from exc

    if not isinstance(payload, dict):
        raise InvalidRenderAudioRequestError

    extra_keys = set(payload) - ALLOWED_RENDER_AUDIO_FIELDS
    if extra_keys:
        raise InvalidRenderAudioRequestError

    if "text" not in payload:
        raise InvalidRenderAudioRequestError

    text = payload["text"]
    if not isinstance(text, str):
        raise InvalidRenderAudioRequestError
    validate_text_length(text)

    voice = payload.get("voice", DEFAULT_VOICE)
    lang = payload.get("lang", DEFAULT_LANG)
    if not isinstance(voice, str) or not voice.strip():
        raise InvalidRenderAudioRequestError
    if not isinstance(lang, str) or not lang.strip():
        raise InvalidRenderAudioRequestError

    request_id = sanitize_request_id(payload.get("request_id"))

    return {
        "text": text.strip(),
        "voice": voice.strip(),
        "lang": lang.strip(),
        "request_id": request_id,
    }


@csrf_exempt
@require_POST
def internal_render_audio(request: HttpRequest) -> JsonResponse:
    if not settings.N8N_QUALIFICATION_API_SECRET:
        _log_event(request, "qualification_render_audio_service_unavailable", level=logging.ERROR)
        return JsonResponse(
            {"error": "Qualification service is unavailable."},
            status=503,
        )

    if not is_internal_qualification_authorized(request):
        _log_event(request, "qualification_render_audio_auth_failed", level=logging.WARNING)
        return JsonResponse({"error": "Forbidden."}, status=403)

    try:
        render_request = _parse_render_audio_request(request.body)
    except InvalidRenderAudioRequestError:
        _log_event(request, "qualification_render_audio_invalid_request", level=logging.WARNING)
        return JsonResponse({"error": "Invalid request."}, status=400)

    try:
        media_url = render_whatsapp_voice_reply_safe(
            text=render_request["text"],
            voice=render_request["voice"],
            lang=render_request["lang"],
        )
    except RenderAudioServiceUnavailableError:
        _log_event(request, "qualification_render_audio_upstream_unavailable", level=logging.ERROR)
        return JsonResponse(
            {"error": "Qualification service is unavailable."},
            status=503,
        )
    except RenderAudioProcessingError:
        _log_event(request, "qualification_render_audio_processing_failed", level=logging.ERROR)
        return JsonResponse(
            {"error": "Qualification service request failed."},
            status=502,
        )
    except Exception:
        _log_event(request, "qualification_render_audio_unexpected_error", level=logging.ERROR)
        return JsonResponse({"error": "Internal server error."}, status=500)

    response_payload = {
        "media_url": media_url,
        "content_type": "audio/ogg",
        "request_id": render_request["request_id"],
    }
    return JsonResponse(response_payload, status=200)
