"""Shared qualification turn handler for text and voice WhatsApp input."""

from __future__ import annotations

from apps.qualification.conversation_flow import (
    build_completed_retry_response,
    build_turn_response,
    is_qualification_complete,
    should_ask_phone_confirmation,
    try_handle_whatsapp_confirmation_turn,
)
from apps.qualification.conversation_state import get_accepted_fields
from apps.qualification.extractor import ExtractionParseError
from apps.qualification.openrouter_client import (
    OpenRouterConfigurationError,
    OpenRouterRequestError,
    OpenRouterResponseError,
    extract_qualification_from_openrouter,
)


class QualificationTurnProcessingError(Exception):
    """Raised when qualification turn processing fails."""


class QualificationServiceUnavailableError(QualificationTurnProcessingError):
    """Raised when upstream qualification services are unavailable."""


class QualificationServiceRequestError(QualificationTurnProcessingError):
    """Raised when upstream qualification services return an unusable response."""


def handle_qualification_turn(*, whatsapp_number: str, message: str) -> dict:
    """Run one qualification turn using the shared conversation flow."""
    persisted_fields = get_accepted_fields(whatsapp_number)

    if is_qualification_complete(persisted_fields):
        return build_completed_retry_response(whatsapp_number)

    confirmation_response = try_handle_whatsapp_confirmation_turn(
        whatsapp_number=whatsapp_number,
        message=message,
    )
    if confirmation_response is not None:
        return confirmation_response

    phone_confirmation_question_asked = should_ask_phone_confirmation(persisted_fields)

    try:
        filter_result = extract_qualification_from_openrouter(
            customer_message=message,
            known_whatsapp_number=whatsapp_number,
            phone_confirmation_question_asked=phone_confirmation_question_asked,
        )
    except OpenRouterConfigurationError as exc:
        raise QualificationServiceUnavailableError from exc
    except (OpenRouterRequestError, OpenRouterResponseError, ExtractionParseError) as exc:
        raise QualificationServiceRequestError from exc

    return build_turn_response(
        whatsapp_number=whatsapp_number,
        filter_result=filter_result,
    )
