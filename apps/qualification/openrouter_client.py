"""
Compatibility facade for OpenRouter qualification extraction.

TODO: Migrate callers to import transport from
``apps.qualification.integrations.openrouter`` and extraction from
``apps.qualification.services.extraction_service`` directly, then remove
this module once patch paths and imports are updated.
"""

from __future__ import annotations

import urllib.request  # noqa: F401 — retained for test patch paths
from typing import Any

from apps.qualification.integrations.openrouter import (
    OpenRouterConfigurationError,
    OpenRouterRequestError,
    OpenRouterResponseError,
    OpenRouterTimeoutError,
    request_openrouter_completion,
)
from apps.qualification.models import QualificationFieldFilterResult
from apps.qualification.services.extraction_service import ExtractionService

__all__ = [
    "OpenRouterConfigurationError",
    "OpenRouterRequestError",
    "OpenRouterResponseError",
    "OpenRouterTimeoutError",
    "extract_qualification_from_openrouter",
]

_extraction_service = ExtractionService()


def extract_qualification_from_openrouter(
    customer_message: str,
    known_whatsapp_number: str,
    *,
    phone_confirmation_question_asked: bool = False,
    message_sid: str | None = None,
    collected_fields: dict[str, Any] | None = None,
    conversation_history: list[dict[str, str]] | None = None,
    conversation_language: str = "en",
) -> QualificationFieldFilterResult:
    """Extract and filter qualification fields from a customer WhatsApp message."""
    provider_text = request_openrouter_completion(
        customer_message,
        known_whatsapp_number,
        phone_confirmation_question_asked=phone_confirmation_question_asked,
        message_sid=message_sid,
        collected_fields=collected_fields,
        conversation_history=conversation_history,
        conversation_language=conversation_language,
        urlopen=urllib.request.urlopen,
    )
    extract_qualification_from_openrouter.last_elapsed_ms = (  # type: ignore[attr-defined]
        request_openrouter_completion.last_elapsed_ms
    )
    return _extraction_service.extract_from_provider_text(
        provider_text,
        customer_message=customer_message,
        known_whatsapp_number=known_whatsapp_number,
        phone_confirmation_question_asked=phone_confirmation_question_asked,
        message_sid=message_sid,
    )


extract_qualification_from_openrouter.last_elapsed_ms = 0
