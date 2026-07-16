"""Legacy render-audio request parser and logging helpers."""

from __future__ import annotations

import json
import logging
from typing import Any

from django.http import HttpRequest

from apps.qualification.api.logging import log_qualification_request_event
from apps.qualification.domain.validators import is_valid_e164_phone_number
from apps.qualification.whatsapp_audio import (
    DEFAULT_LANG,
    DEFAULT_VOICE,
    InvalidRenderAudioRequestError,
    sanitize_request_id,
    validate_text_length,
)

ALLOWED_RENDER_AUDIO_FIELDS = frozenset(
    {
        "text",
        "voice",
        "lang",
        "request_id",
        "whatsapp_number",
        "conversation_language",
    },
)


def _log_event(request: HttpRequest, event: str, *, level: int = logging.INFO) -> None:
    # TODO: remove after callers migrate to apps.qualification.api.logging directly.
    log_qualification_request_event(request, event, level=level)


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

    whatsapp_number = payload.get("whatsapp_number")
    if whatsapp_number is not None:
        if not isinstance(whatsapp_number, str):
            raise InvalidRenderAudioRequestError
        whatsapp_number = "".join(whatsapp_number.split())
        if not whatsapp_number or not is_valid_e164_phone_number(whatsapp_number):
            raise InvalidRenderAudioRequestError
    else:
        whatsapp_number = None

    conversation_language = payload.get("conversation_language")
    if conversation_language is not None:
        if not isinstance(conversation_language, str) or not conversation_language.strip():
            raise InvalidRenderAudioRequestError
        conversation_language = conversation_language.strip()

    return {
        "text": text.strip(),
        "voice": voice.strip(),
        "lang": lang.strip(),
        "request_id": request_id,
        "whatsapp_number": whatsapp_number,
        "conversation_language": conversation_language,
    }
