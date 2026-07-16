"""Shared qualification helpers decoupled from legacy ``views.py``."""

from __future__ import annotations

from dataclasses import dataclass

from apps.qualification.channels import InputChannel
from apps.qualification.deepgram_client import transcribe_audio
from apps.qualification.openrouter_client import OpenRouterTimeoutError
from apps.qualification.twilio_media import download_twilio_media


@dataclass(frozen=True)
class QualificationTurnRequest:
    whatsapp_number: str
    message: str | None
    input_channel: InputChannel
    message_sid: str | None
    media_url: str | None
    media_content_type: str | None
    call_sid: str | None = None
    utterance_id: str | None = None
    is_final: bool = True
    event_source: str | None = None


def is_openrouter_timeout_error(exc: BaseException) -> bool:
    return isinstance(exc.__cause__, OpenRouterTimeoutError)


__all__ = [
    "QualificationTurnRequest",
    "download_twilio_media",
    "is_openrouter_timeout_error",
    "transcribe_audio",
]
