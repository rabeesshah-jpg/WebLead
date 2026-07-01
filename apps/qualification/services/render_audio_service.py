"""Render-audio orchestration for internal qualification APIs."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from apps.qualification.api.logging import log_qualification_event
from apps.qualification.domain.language import get_conversation_language
from apps.qualification.domain.language_selection import LANGUAGE_ENGLISH
from apps.qualification.domain.latency_profiling import elapsed_ms_since, log_latency_step
from apps.qualification.domain.logging_utils import message_sid_prefix
from apps.qualification.domain.supertonic_config import (
    FALLBACK_REASON_ARABIC_TTS_UNAVAILABLE,
    FALLBACK_REASON_ENGLISH_TTS_UNAVAILABLE,
    FALLBACK_REASON_UNSUPPORTED_LANGUAGE,
    SupertonicVoiceConfig,
    get_supertonic_voice_config,
)
from apps.qualification.render_audio_idempotency import (
    cache_render_response,
    get_cached_render_response,
)
from apps.qualification.whatsapp_audio import (
    InvalidRenderAudioRequestError,
    RenderAudioProcessingError,
    RenderAudioServiceUnavailableError,
    render_whatsapp_voice_reply_safe,
    validate_text_length,
)

Renderer = Callable[..., str]

AUDIO_CONTENT_TYPE = "audio/ogg"
logger = logging.getLogger("apps.qualification")


class RenderAudioService:
    def __init__(self, *, renderer: Renderer | None = None) -> None:
        self._renderer = renderer or render_whatsapp_voice_reply_safe

    def render(self, validated_data: dict[str, Any]) -> dict[str, Any]:
        """
        Generate a WhatsApp-compatible voice reply or return a controlled text-fallback
        payload without any HTTP response object.
        """
        text = validated_data["text"]
        validate_text_length(text)
        stripped_text = text.strip()
        request_id = validated_data.get("request_id")
        request_id_prefix = message_sid_prefix(request_id)

        if request_id:
            cached = get_cached_render_response(request_id)
            if cached is not None:
                return dict(cached)

        conversation_language = self._resolve_conversation_language(validated_data)
        voice_config = get_supertonic_voice_config(
            conversation_language=conversation_language,
        )
        self._log_lang_hint_mismatch(validated_data, conversation_language, request_id_prefix)

        log_qualification_event(
            "tts_render_started",
            conversation_language=conversation_language,
            voice_configured=bool(voice_config.voice),
            arabic_tts_enabled=voice_config.language == "ar" and voice_config.enabled,
            request_id_prefix=request_id_prefix,
        )

        if not voice_config.enabled:
            return self._finalize_response(
                self._build_fallback_response(
                    conversation_language=conversation_language,
                    fallback_reason=self._disabled_fallback_reason(voice_config),
                    request_id=request_id,
                ),
                request_id=request_id,
            )

        tts_started = time.perf_counter()
        try:
            media_url = self._renderer(
                text=stripped_text,
                voice=voice_config.voice,
                lang=voice_config.language,
            )
        except InvalidRenderAudioRequestError:
            raise
        except (RenderAudioServiceUnavailableError, RenderAudioProcessingError) as exc:
            log_latency_step(
                "tts_render",
                elapsed_ms_since(tts_started),
                message_sid=request_id,
                text_length=len(stripped_text),
                status="failure",
                error_type=type(exc).__name__,
            )
            log_qualification_event(
                "tts_text_fallback",
                conversation_language=conversation_language,
                fallback_reason=self._failure_fallback_reason(voice_config),
                request_id_prefix=request_id_prefix,
            )
            return self._finalize_response(
                self._build_fallback_response(
                    conversation_language=conversation_language,
                    fallback_reason=self._failure_fallback_reason(voice_config),
                    request_id=request_id,
                ),
                request_id=request_id,
            )

        duration_ms = elapsed_ms_since(tts_started)
        log_latency_step(
            "tts_render",
            duration_ms,
            message_sid=request_id,
            text_length=len(stripped_text),
            output_audio_path=getattr(render_whatsapp_voice_reply_safe, "last_output_path", None),
            output_media_url=media_url,
            output_audio_size_bytes=getattr(
                render_whatsapp_voice_reply_safe,
                "last_output_size_bytes",
                None,
            ),
            status="success",
        )
        log_qualification_event(
            "tts_render_succeeded",
            conversation_language=conversation_language,
            audio_content_type=AUDIO_CONTENT_TYPE,
            request_id_prefix=request_id_prefix,
        )

        return self._finalize_response(
            self._build_success_response(
                media_url=media_url,
                conversation_language=conversation_language,
                request_id=request_id,
            ),
            request_id=request_id,
        )

    @staticmethod
    def _resolve_conversation_language(validated_data: dict[str, Any]) -> str:
        whatsapp_number = validated_data.get("whatsapp_number")
        if whatsapp_number:
            return get_conversation_language(whatsapp_number)
        return LANGUAGE_ENGLISH

    @staticmethod
    def _log_lang_hint_mismatch(
        validated_data: dict[str, Any],
        conversation_language: str,
        request_id_prefix: str | None,
    ) -> None:
        request_lang = validated_data.get("lang")
        if not request_lang or request_lang == conversation_language:
            return
        log_qualification_event(
            "tts_lang_hint_mismatch",
            level=logging.WARNING,
            conversation_language=conversation_language,
            request_lang_hint=request_lang,
            request_id_prefix=request_id_prefix,
        )

    @staticmethod
    def _disabled_fallback_reason(voice_config: SupertonicVoiceConfig) -> str:
        if voice_config.language == "ar":
            return FALLBACK_REASON_ARABIC_TTS_UNAVAILABLE
        if voice_config.language == "en":
            return FALLBACK_REASON_ENGLISH_TTS_UNAVAILABLE
        return FALLBACK_REASON_UNSUPPORTED_LANGUAGE

    @staticmethod
    def _failure_fallback_reason(voice_config: SupertonicVoiceConfig) -> str:
        if voice_config.language == "ar":
            return FALLBACK_REASON_ARABIC_TTS_UNAVAILABLE
        return FALLBACK_REASON_ENGLISH_TTS_UNAVAILABLE

    @staticmethod
    def _build_success_response(
        *,
        media_url: str,
        conversation_language: str,
        request_id: str | None,
    ) -> dict[str, Any]:
        return {
            "status": "rendered",
            "fallback_to_text": False,
            "conversation_language": conversation_language,
            "media_url": media_url,
            "content_type": AUDIO_CONTENT_TYPE,
            "audio_url": media_url,
            "audio_content_type": AUDIO_CONTENT_TYPE,
            "request_id": request_id,
        }

    @staticmethod
    def _build_fallback_response(
        *,
        conversation_language: str,
        fallback_reason: str,
        request_id: str | None,
    ) -> dict[str, Any]:
        return {
            "status": "text_fallback",
            "fallback_to_text": True,
            "conversation_language": conversation_language,
            "fallback_reason": fallback_reason,
            "media_url": None,
            "content_type": None,
            "audio_url": None,
            "audio_content_type": None,
            "request_id": request_id,
        }

    @staticmethod
    def _finalize_response(
        response: dict[str, Any],
        *,
        request_id: str | None,
    ) -> dict[str, Any]:
        if request_id:
            cache_render_response(request_id, response)
        return response
