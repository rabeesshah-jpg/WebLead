"""Shared helpers for internal qualification API endpoint tests."""

from __future__ import annotations

from typing import Any

from apps.qualification.internal_auth import QUALIFICATION_SECRET_HEADER_NAME

API_SECRET = "test-n8n-qualification-api-secret"
MOCK_VOICE_AUDIO_BYTES = b"\x00" * 128
MOCK_VOICE_AUDIO_DOWNLOAD = (MOCK_VOICE_AUDIO_BYTES, "audio/ogg")
INTERNAL_API_SECRET_META_KEY = "HTTP_" + QUALIFICATION_SECRET_HEADER_NAME.upper().replace("-", "_")

ERROR_CONTRACT_400 = {"error": "Invalid request."}
ERROR_CONTRACT_403 = {"error": "Forbidden."}
ERROR_CONTRACT_500 = {"error": "Internal server error."}
ERROR_CONTRACT_502 = {"error": "Qualification service request failed."}
ERROR_CONTRACT_502_TWILIO = {"error": "Twilio media download failed."}
ERROR_CONTRACT_502_TRANSCRIPTION = {"error": "Voice transcription failed."}
ERROR_CONTRACT_502_LLM = {"error": "Qualification LLM request failed."}
ERROR_CONTRACT_503 = {"error": "Qualification service is unavailable."}

EXTRACT_SUCCESS_FIELD_NAMES = frozenset(
    {
        "accepted_fields",
        "rejected_fields",
        "human_handoff_requested",
        "next_field",
        "reply_text",
        "qualification_status",
        "conversation_language",
        "preferred_phone",
        "reply_mode",
        "send_booking_link",
        "booking_link",
    },
)

RENDER_AUDIO_SUCCESS_FIELD_NAMES = frozenset(
    {
        "status",
        "fallback_to_text",
        "conversation_language",
        "media_url",
        "content_type",
        "audio_url",
        "audio_content_type",
        "request_id",
    },
)


def internal_api_auth_headers(*, secret: str | None = API_SECRET) -> dict[str, str]:
    headers: dict[str, str] = {}
    if secret is not None:
        headers[INTERNAL_API_SECRET_META_KEY] = secret
    return headers


def assert_public_error_contract(response: Any, *, status_code: int, body: dict[str, str]) -> None:
    """Assert exact public error JSON without DRF ``detail`` leakage."""
    assert response.status_code == status_code
    payload = response.json()
    assert payload == body
    assert "detail" not in payload
