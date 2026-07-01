"""Voice-note transcription orchestration for qualification extract."""

from __future__ import annotations

import logging
import time
from typing import Callable

from apps.qualification.deepgram_client import (
    DeepgramConfigurationError,
    DeepgramRequestError,
    DeepgramResponseError,
    DeepgramTimeoutError,
    normalize_audio_content_type,
    validate_audio_payload,
)
from apps.qualification.domain.deepgram_config import (
    DeepgramTranscriptionConfig,
    get_deepgram_transcription_config,
)
from apps.qualification.domain.extract_errors import (
    TWILIO_MEDIA_DOWNLOAD_FAILED,
    VOICE_TRANSCRIPTION_FAILED,
    ExtractFailureInfo,
    ExtractStepFailure,
    http_status_from_cause,
)
from apps.qualification.domain.extract_logging import log_extract_step_failed
from apps.qualification.domain.language_selection import normalize_conversation_language
from apps.qualification.domain.latency_profiling import elapsed_ms_since, log_latency_step
from apps.qualification.persistence.cache_backend import (
    default_cache_ttl_seconds,
    get_qualification_cache_backend,
    reset_qualification_cache_backend_for_tests,
    twilio_media_cache_key,
)
from apps.qualification.twilio_media import (
    DEFAULT_AUDIO_CONTENT_TYPE,
    TwilioMediaConfigurationError,
    TwilioMediaRequestError,
    TwilioMediaTimeoutError,
    TwilioMediaUnauthorizedError,
)
from apps.qualification.voice_note_config import (
    VoiceNoteConfigurationError,
    validate_voice_note_dependencies,
)
from apps.qualification.voice_note_logging import log_voice_note_event

MediaDownloader = Callable[[str], bytes | tuple[bytes, str]]
TranscriptionClient = Callable[..., str]
DependencyValidator = Callable[[], None]

TWILIO_MEDIA_CACHE_PREFIX = "twilio_media:"


def clear_transcription_media_cache() -> None:
    """Clear cached Twilio media entries. Intended for tests."""
    get_qualification_cache_backend().delete_by_prefix(TWILIO_MEDIA_CACHE_PREFIX)


def _safe_audio_duration_seconds(transcription_client: TranscriptionClient) -> float | None:
    duration = getattr(transcription_client, "last_audio_duration_seconds", None)
    if isinstance(duration, int | float):
        return float(duration)
    return None


def _resolve_audio_content_type(
    downloaded_content_type: str | None,
    request_content_type: str | None,
) -> str:
    for candidate in (downloaded_content_type, request_content_type, DEFAULT_AUDIO_CONTENT_TYPE):
        normalized = normalize_audio_content_type(candidate) if candidate else None
        if normalized:
            return normalized
    return DEFAULT_AUDIO_CONTENT_TYPE


def _unpack_media_download(result: bytes | tuple[bytes, str]) -> tuple[bytes, str]:
    if isinstance(result, tuple):
        audio_bytes, content_type = result
        return audio_bytes, normalize_audio_content_type(content_type)
    return result, DEFAULT_AUDIO_CONTENT_TYPE


def _raise_twilio_download_failure(
    *,
    exc: BaseException,
    message_sid: str | None,
    duration_ms: int,
    details: str,
) -> None:
    info = ExtractFailureInfo(
        failure_step="twilio_media_download_failed",
        public_message=TWILIO_MEDIA_DOWNLOAD_FAILED,
        error_type=type(exc).__name__,
        status_code=http_status_from_cause(exc),
        duration_ms=duration_ms,
        details=details,
    )
    log_extract_step_failed(info, message_sid=message_sid)
    raise ExtractStepFailure(info, cause=exc) from exc


def _raise_voice_transcription_failure(
    *,
    exc: BaseException,
    message_sid: str | None,
    duration_ms: int,
    details: str,
) -> None:
    info = ExtractFailureInfo(
        failure_step="deepgram_transcription_failed",
        public_message=VOICE_TRANSCRIPTION_FAILED,
        error_type=type(exc).__name__,
        status_code=http_status_from_cause(exc),
        duration_ms=duration_ms,
        details=details,
    )
    log_extract_step_failed(info, message_sid=message_sid)
    raise ExtractStepFailure(info, cause=exc) from exc


class VoiceNoteTranscriptionService:
    def __init__(
        self,
        *,
        media_downloader: MediaDownloader | None = None,
        transcription_client: TranscriptionClient | None = None,
        dependency_validator: DependencyValidator | None = None,
    ) -> None:
        if media_downloader is None or transcription_client is None:
            from apps.qualification.core import legacy_compat

            if media_downloader is None:
                media_downloader = legacy_compat.download_twilio_media
            if transcription_client is None:
                transcription_client = legacy_compat.transcribe_audio

        self._media_downloader = media_downloader
        self._transcription_client = transcription_client
        self._dependency_validator = dependency_validator or validate_voice_note_dependencies

    def _log_twilio_download_step(
        self,
        *,
        duration_ms: int,
        message_sid: str | None,
        media_url: str | None,
        media_content_type: str | None,
        audio_size_bytes: int | None,
        status: str,
        cache_hit: bool = False,
    ) -> None:
        log_latency_step(
            "twilio_media_download",
            duration_ms,
            message_sid=message_sid,
            media_url_present=bool(media_url),
            media_content_type=media_content_type,
            audio_size_bytes=audio_size_bytes,
            status=status,
            cache_hit=cache_hit,
        )

    def _download_media(
        self,
        *,
        media_url: str,
        media_content_type: str | None,
        message_sid: str | None,
    ) -> tuple[bytes, str]:
        cache = get_qualification_cache_backend()
        redis_key = twilio_media_cache_key(message_sid=message_sid, media_url=media_url)
        cached_bytes = cache.get(redis_key)
        if isinstance(cached_bytes, bytes):
            effective_content_type = _resolve_audio_content_type(None, media_content_type)
            self._log_twilio_download_step(
                duration_ms=0,
                message_sid=message_sid,
                media_url=media_url,
                media_content_type=effective_content_type,
                audio_size_bytes=len(cached_bytes),
                status="success",
                cache_hit=True,
            )
            return cached_bytes, effective_content_type

        download_started = time.perf_counter()
        try:
            download_result = self._media_downloader(media_url)
        except TwilioMediaUnauthorizedError as exc:
            elapsed = elapsed_ms_since(download_started)
            self._log_twilio_download_step(
                duration_ms=elapsed,
                message_sid=message_sid,
                media_url=media_url,
                media_content_type=media_content_type,
                audio_size_bytes=None,
                status="failure",
            )
            log_voice_note_event(
                "qualification_voice_twilio_download_unauthorized",
                message_sid=message_sid,
                http_status=getattr(exc.__cause__, "code", None),
                elapsed_ms=elapsed,
            )
            _raise_twilio_download_failure(
                exc=exc,
                message_sid=message_sid,
                duration_ms=elapsed,
                details="Twilio media download unauthorized",
            )
        except TwilioMediaTimeoutError as exc:
            elapsed = elapsed_ms_since(download_started)
            self._log_twilio_download_step(
                duration_ms=elapsed,
                message_sid=message_sid,
                media_url=media_url,
                media_content_type=media_content_type,
                audio_size_bytes=None,
                status="failure",
            )
            log_voice_note_event(
                "qualification_voice_twilio_download_timeout",
                message_sid=message_sid,
                elapsed_ms=elapsed,
            )
            _raise_twilio_download_failure(
                exc=exc,
                message_sid=message_sid,
                duration_ms=elapsed,
                details="Twilio media download timed out",
            )
        except TwilioMediaRequestError as exc:
            elapsed = elapsed_ms_since(download_started)
            self._log_twilio_download_step(
                duration_ms=elapsed,
                message_sid=message_sid,
                media_url=media_url,
                media_content_type=media_content_type,
                audio_size_bytes=None,
                status="failure",
            )
            log_voice_note_event(
                "qualification_voice_twilio_download_failed",
                message_sid=message_sid,
                http_status=getattr(exc.__cause__, "code", None),
                elapsed_ms=elapsed,
            )
            _raise_twilio_download_failure(
                exc=exc,
                message_sid=message_sid,
                duration_ms=elapsed,
                details="Twilio media download failed",
            )

        audio_bytes, downloaded_content_type = _unpack_media_download(download_result)
        effective_content_type = _resolve_audio_content_type(
            downloaded_content_type,
            media_content_type,
        )
        cache.set(redis_key, audio_bytes, default_cache_ttl_seconds())
        self._log_twilio_download_step(
            duration_ms=elapsed_ms_since(download_started),
            message_sid=message_sid,
            media_url=media_url,
            media_content_type=effective_content_type,
            audio_size_bytes=len(audio_bytes),
            status="success",
        )
        return audio_bytes, effective_content_type

    def _log_deepgram_step(
        self,
        *,
        duration_ms: int,
        message_sid: str | None,
        media_content_type: str | None,
        audio_size_bytes: int,
        transcript_length: int | None,
        audio_duration_seconds: float | None,
        status: str,
        transcription_config: DeepgramTranscriptionConfig,
        conversation_language: str,
        error_type: str | None = None,
    ) -> None:
        log_latency_step(
            "deepgram_transcription",
            duration_ms,
            message_sid=message_sid,
            direct_audio_bytes=True,
            media_content_type=media_content_type,
            audio_size_bytes=audio_size_bytes,
            audio_duration_seconds=audio_duration_seconds,
            transcript_length=transcript_length,
            deepgram_model=transcription_config.model,
            deepgram_language=transcription_config.language,
            conversation_language=conversation_language,
            status=status,
            error_type=error_type,
        )

    def transcribe(
        self,
        *,
        media_url: str,
        media_content_type: str | None,
        message_sid: str | None,
        conversation_language: str = "en",
    ) -> str:
        """
        Download a WhatsApp voice note, validate it, transcribe it through
        the existing Deepgram integration, emit the existing voice-specific
        logs, and return the normalized transcript text.
        """
        normalized_language = normalize_conversation_language(conversation_language)
        try:
            transcription_config = get_deepgram_transcription_config(
                conversation_language=normalized_language,
            )
        except DeepgramConfigurationError as exc:
            log_voice_note_event(
                "qualification_voice_deepgram_configuration_error",
                message_sid=message_sid,
                media_content_type=media_content_type,
            )
            raise

        try:
            self._dependency_validator()
        except VoiceNoteConfigurationError as exc:
            log_voice_note_event(
                exc.log_event,
                message_sid=message_sid,
                media_content_type=media_content_type,
            )
            if exc.log_event == "qualification_voice_missing_twilio_credentials":
                raise TwilioMediaConfigurationError(str(exc)) from exc
            raise DeepgramConfigurationError(str(exc)) from exc

        audio_bytes, effective_content_type = self._download_media(
            media_url=media_url,
            media_content_type=media_content_type,
            message_sid=message_sid,
        )
        try:
            validate_audio_payload(audio_bytes, content_type=effective_content_type)
        except DeepgramRequestError as exc:
            _raise_voice_transcription_failure(
                exc=exc,
                message_sid=message_sid,
                duration_ms=0,
                details="Downloaded audio payload is invalid",
            )

        transcription_started = time.perf_counter()
        log_voice_note_event(
            "deepgram_transcription_started",
            message_sid=message_sid,
            media_content_type=effective_content_type,
            conversation_language=normalized_language,
            deepgram_model=transcription_config.model,
            deepgram_language=transcription_config.language,
            level=logging.INFO,
        )
        try:
            transcript = self._transcription_client(
                audio_bytes,
                content_type=effective_content_type,
                transcription_config=transcription_config,
            )
        except DeepgramConfigurationError as exc:
            elapsed = elapsed_ms_since(transcription_started)
            self._log_deepgram_step(
                duration_ms=elapsed,
                message_sid=message_sid,
                media_content_type=effective_content_type,
                audio_size_bytes=len(audio_bytes),
                transcript_length=None,
                audio_duration_seconds=_safe_audio_duration_seconds(self._transcription_client),
                status="failure",
                transcription_config=transcription_config,
                conversation_language=normalized_language,
                error_type=type(exc).__name__,
            )
            log_voice_note_event(
                "qualification_voice_deepgram_configuration_error",
                message_sid=message_sid,
                media_content_type=effective_content_type,
                conversation_language=normalized_language,
                deepgram_model=transcription_config.model,
                deepgram_language=transcription_config.language,
                error_type=type(exc).__name__,
                elapsed_ms=elapsed,
            )
            raise
        except DeepgramTimeoutError as exc:
            elapsed = elapsed_ms_since(transcription_started)
            self._log_deepgram_step(
                duration_ms=elapsed,
                message_sid=message_sid,
                media_content_type=effective_content_type,
                audio_size_bytes=len(audio_bytes),
                transcript_length=None,
                audio_duration_seconds=_safe_audio_duration_seconds(self._transcription_client),
                status="failure",
                transcription_config=transcription_config,
                conversation_language=normalized_language,
                error_type=type(exc).__name__,
            )
            log_voice_note_event(
                "deepgram_transcription_failed",
                message_sid=message_sid,
                media_content_type=effective_content_type,
                conversation_language=normalized_language,
                deepgram_model=transcription_config.model,
                deepgram_language=transcription_config.language,
                error_type=type(exc).__name__,
                elapsed_ms=elapsed,
            )
            log_voice_note_event(
                "qualification_voice_deepgram_timeout",
                message_sid=message_sid,
                media_content_type=effective_content_type,
                elapsed_ms=elapsed,
            )
            _raise_voice_transcription_failure(
                exc=exc,
                message_sid=message_sid,
                duration_ms=elapsed,
                details="Deepgram request timed out",
            )
        except DeepgramRequestError as exc:
            elapsed = elapsed_ms_since(transcription_started)
            self._log_deepgram_step(
                duration_ms=elapsed,
                message_sid=message_sid,
                media_content_type=effective_content_type,
                audio_size_bytes=len(audio_bytes),
                transcript_length=None,
                audio_duration_seconds=_safe_audio_duration_seconds(self._transcription_client),
                status="failure",
                transcription_config=transcription_config,
                conversation_language=normalized_language,
                error_type=type(exc).__name__,
            )
            log_voice_note_event(
                "deepgram_transcription_failed",
                message_sid=message_sid,
                media_content_type=effective_content_type,
                conversation_language=normalized_language,
                deepgram_model=transcription_config.model,
                deepgram_language=transcription_config.language,
                error_type=type(exc).__name__,
                elapsed_ms=elapsed,
            )
            log_voice_note_event(
                "qualification_voice_deepgram_request_failed",
                message_sid=message_sid,
                media_content_type=effective_content_type,
                http_status=getattr(exc.__cause__, "code", None),
                elapsed_ms=elapsed,
            )
            _raise_voice_transcription_failure(
                exc=exc,
                message_sid=message_sid,
                duration_ms=elapsed,
                details="Deepgram request failed",
            )
        except DeepgramResponseError as exc:
            elapsed = elapsed_ms_since(transcription_started)
            self._log_deepgram_step(
                duration_ms=elapsed,
                message_sid=message_sid,
                media_content_type=effective_content_type,
                audio_size_bytes=len(audio_bytes),
                transcript_length=None,
                audio_duration_seconds=_safe_audio_duration_seconds(self._transcription_client),
                status="failure",
                transcription_config=transcription_config,
                conversation_language=normalized_language,
                error_type=type(exc).__name__,
            )
            event = (
                "qualification_voice_transcription_empty"
                if "empty" in str(exc).lower()
                else "qualification_voice_deepgram_invalid_response"
            )
            log_voice_note_event(
                "deepgram_transcription_failed",
                message_sid=message_sid,
                media_content_type=effective_content_type,
                conversation_language=normalized_language,
                deepgram_model=transcription_config.model,
                deepgram_language=transcription_config.language,
                error_type=type(exc).__name__,
                elapsed_ms=elapsed,
            )
            log_voice_note_event(
                event,
                message_sid=message_sid,
                media_content_type=effective_content_type,
                elapsed_ms=elapsed,
            )
            details = (
                "Deepgram transcript is empty"
                if "empty" in str(exc).lower()
                else "Deepgram response is unusable"
            )
            _raise_voice_transcription_failure(
                exc=exc,
                message_sid=message_sid,
                duration_ms=elapsed,
                details=details,
            )

        self._log_deepgram_step(
            duration_ms=elapsed_ms_since(transcription_started),
            message_sid=message_sid,
            media_content_type=effective_content_type,
            audio_size_bytes=len(audio_bytes),
            transcript_length=len(transcript),
            audio_duration_seconds=_safe_audio_duration_seconds(self._transcription_client),
            status="success",
            transcription_config=transcription_config,
            conversation_language=normalized_language,
        )

        return transcript


__all__ = [
    "VoiceNoteTranscriptionService",
    "clear_transcription_media_cache",
    "reset_qualification_cache_backend_for_tests",
]
