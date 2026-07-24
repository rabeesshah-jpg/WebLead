"""DRF exception helpers for qualification internal APIs."""

from __future__ import annotations

from typing import Any

from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import exception_handler

INVALID_REQUEST_ERROR = "Invalid request."
FORBIDDEN_ERROR = "Forbidden."
SERVICE_REQUEST_FAILED_ERROR = "Qualification service request failed."
TWILIO_MEDIA_DOWNLOAD_FAILED_ERROR = "WhatsApp media download failed."

VOICE_TRANSCRIPTION_FAILED_ERROR = "Voice transcription failed."
QUALIFICATION_LLM_REQUEST_FAILED_ERROR = "Qualification LLM request failed."
SERVICE_UNAVAILABLE_ERROR = "Qualification service is unavailable."
INTERNAL_SERVER_ERROR = "Internal server error."

QUALIFICATION_SERVICE_REQUEST_FAILED_ERROR = SERVICE_REQUEST_FAILED_ERROR
QUALIFICATION_SERVICE_UNAVAILABLE_ERROR = SERVICE_UNAVAILABLE_ERROR


def error_response(message: str, status_code: int) -> Response:
    """
    Return the stable JSON error contract used by internal qualification APIs.
    """
    return Response(
        {"error": message},
        status=status_code,
    )


def qualification_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Map DRF default ``detail`` errors to contract-shaped ``error`` responses."""
    response = exception_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, PermissionDenied):
        response.data = {"error": FORBIDDEN_ERROR}
        response.status_code = 403
        return response

    if isinstance(response.data, dict) and set(response.data.keys()) == {"detail"}:
        response.data = {"error": str(response.data["detail"])}

    return response
