"""Typed failures for the qualification extract pipeline."""

from __future__ import annotations

from dataclasses import dataclass

TWILIO_MEDIA_DOWNLOAD_FAILED = "Twilio media download failed."
VOICE_TRANSCRIPTION_FAILED = "Voice transcription failed."
QUALIFICATION_LLM_REQUEST_FAILED = "Qualification LLM request failed."


class QualificationTurnProcessingError(Exception):
    """Raised when qualification turn processing fails."""


@dataclass(frozen=True)
class ExtractFailureInfo:
    failure_step: str
    public_message: str
    error_type: str
    status_code: int | None = None
    duration_ms: int | None = None
    details: str | None = None


class ExtractStepFailure(QualificationTurnProcessingError):
    """Extract pipeline failure with a safe public message and structured log metadata."""

    def __init__(self, info: ExtractFailureInfo, *, cause: BaseException | None = None) -> None:
        self.info = info
        super().__init__(info.public_message)
        if cause is not None:
            self.__cause__ = cause


def http_status_from_cause(exc: BaseException) -> int | None:
    cause = exc.__cause__
    if cause is not None:
        code = getattr(cause, "code", None)
        if isinstance(code, int):
            return code
    return None
