"""OpenRouter client for lead-qualification extraction."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from django.conf import settings

from apps.qualification.extractor import parse_extraction_json
from apps.qualification.filtering import filter_qualification_fields
from apps.qualification.models import QualificationFieldFilterResult
from apps.qualification.phone_confirmation import apply_phone_confirmation_guard
from apps.qualification.prompts import EXTRACTION_SYSTEM_PROMPT, build_extraction_user_message
from apps.qualification.schema import EXTRACTION_JSON_SCHEMA


class OpenRouterConfigurationError(Exception):
    """Raised when OpenRouter client settings are incomplete."""


class OpenRouterRequestError(Exception):
    """Raised when the OpenRouter HTTP request fails."""


class OpenRouterResponseError(Exception):
    """Raised when the OpenRouter response cannot be used."""


def _validate_configuration() -> None:
    if not settings.OPENROUTER_API_KEY:
        raise OpenRouterConfigurationError("OpenRouter API key is not configured")
    if not settings.OPENROUTER_MODEL:
        raise OpenRouterConfigurationError("OpenRouter model is not configured")


def _build_request_payload(
    *,
    customer_message: str,
    known_whatsapp_number: str,
    phone_confirmation_question_asked: bool = False,
) -> dict[str, Any]:
    return {
        "model": settings.OPENROUTER_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_extraction_user_message(
                    customer_message=customer_message,
                    known_whatsapp_number=known_whatsapp_number,
                    phone_confirmation_question_asked=phone_confirmation_question_asked,
                ),
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "lead_qualification_extraction",
                "strict": True,
                "schema": EXTRACTION_JSON_SCHEMA,
            },
        },
    }


def _extract_assistant_content(response_payload: dict[str, Any]) -> str:
    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise OpenRouterResponseError("OpenRouter response is missing choices")

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise OpenRouterResponseError("OpenRouter response is missing message content")

    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise OpenRouterResponseError("OpenRouter response is missing message content")

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise OpenRouterResponseError("OpenRouter response is missing message content")

    return content


def extract_qualification_from_openrouter(
    customer_message: str,
    known_whatsapp_number: str,
    *,
    phone_confirmation_question_asked: bool = False,
) -> QualificationFieldFilterResult:
    """Extract and filter qualification fields from a customer WhatsApp message."""
    _validate_configuration()

    url = f"{settings.OPENROUTER_BASE_URL}/chat/completions"
    payload = _build_request_payload(
        customer_message=customer_message,
        known_whatsapp_number=known_whatsapp_number,
        phone_confirmation_question_asked=phone_confirmation_question_asked,
    )
    encoded_body = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    request = urllib.request.Request(url, data=encoded_body, method="POST", headers=headers)

    try:
        with urllib.request.urlopen(
            request,
            timeout=settings.OPENROUTER_TIMEOUT_SECONDS,
        ) as response:
            if response.status >= 400:
                raise OpenRouterRequestError("OpenRouter request failed")
            raw_body = response.read()
    except urllib.error.HTTPError as exc:
        raise OpenRouterRequestError("OpenRouter request failed") from exc
    except urllib.error.URLError as exc:
        raise OpenRouterRequestError("OpenRouter request failed") from exc

    try:
        response_payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise OpenRouterResponseError("OpenRouter response is not valid JSON") from exc

    if not isinstance(response_payload, dict):
        raise OpenRouterResponseError("OpenRouter response is not valid JSON")

    assistant_content = _extract_assistant_content(response_payload)
    extraction = parse_extraction_json(assistant_content)
    guarded_extraction = apply_phone_confirmation_guard(
        extraction,
        customer_message,
        known_whatsapp_number,
        phone_confirmation_question_asked=phone_confirmation_question_asked,
    )
    return filter_qualification_fields(guarded_extraction)
