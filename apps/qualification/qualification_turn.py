"""Shared qualification turn handler for text and voice WhatsApp input."""

from __future__ import annotations

from apps.qualification.conversation_flow import (
    build_completed_retry_response,
    build_turn_response,
    is_qualification_complete,
    should_ask_phone_confirmation,
    try_handle_preferred_phone_turn,
    try_handle_whatsapp_confirmation_turn,
)
from apps.qualification.conversation_state import (
    append_conversation_turn,
    get_accepted_fields,
    get_recent_conversation_history,
)
from apps.qualification.domain.extract_errors import (
    QUALIFICATION_LLM_REQUEST_FAILED,
    ExtractFailureInfo,
    ExtractStepFailure,
    QualificationTurnProcessingError,
    http_status_from_cause,
)
from apps.qualification.domain.language import get_conversation_language
from apps.qualification.extractor import ExtractionParseError
from apps.qualification.openrouter_client import (
    OpenRouterConfigurationError,
    OpenRouterRequestError,
    OpenRouterResponseError,
    OpenRouterTimeoutError,
    extract_qualification_from_openrouter,
)


class QualificationServiceUnavailableError(QualificationTurnProcessingError):
    """Raised when upstream qualification services are unavailable."""


class QualificationServiceRequestError(QualificationTurnProcessingError):
    """Raised when upstream qualification services return an unusable response."""


def _record_conversation_turn(
    *,
    whatsapp_number: str,
    message: str,
    response: dict,
) -> None:
    append_conversation_turn(
        whatsapp_number,
        user_message=message,
        assistant_reply=response.get("reply_text", ""),
    )


def _raise_llm_request_failure(
    *,
    exc: BaseException,
    message_sid: str | None,
    details: str,
) -> None:
    from apps.qualification.domain.extract_logging import log_extract_step_failed

    elapsed_ms = getattr(extract_qualification_from_openrouter, "last_elapsed_ms", None)
    info = ExtractFailureInfo(
        failure_step="openrouter_call_failed",
        public_message=QUALIFICATION_LLM_REQUEST_FAILED,
        error_type=type(exc).__name__,
        status_code=http_status_from_cause(exc),
        duration_ms=elapsed_ms if isinstance(elapsed_ms, int) else None,
        details=details,
    )
    log_extract_step_failed(info, message_sid=message_sid)
    raise ExtractStepFailure(info, cause=exc) from exc


def handle_qualification_turn(
    *,
    whatsapp_number: str,
    message: str,
    message_sid: str | None = None,
) -> dict:
    """Run one qualification turn using the shared conversation flow."""
    persisted_fields = get_accepted_fields(whatsapp_number)
    conversation_language = get_conversation_language(whatsapp_number)

    if is_qualification_complete(persisted_fields):
        response = build_completed_retry_response(
            whatsapp_number,
            language=conversation_language,
        )
        _record_conversation_turn(
            whatsapp_number=whatsapp_number,
            message=message,
            response=response,
        )
        return response

    confirmation_response = try_handle_whatsapp_confirmation_turn(
        whatsapp_number=whatsapp_number,
        message=message,
        language=conversation_language,
    )
    if confirmation_response is not None:
        _record_conversation_turn(
            whatsapp_number=whatsapp_number,
            message=message,
            response=confirmation_response,
        )
        return confirmation_response

    preferred_phone_response = try_handle_preferred_phone_turn(
        whatsapp_number=whatsapp_number,
        message=message,
        language=conversation_language,
    )
    if preferred_phone_response is not None:
        _record_conversation_turn(
            whatsapp_number=whatsapp_number,
            message=message,
            response=preferred_phone_response,
        )
        return preferred_phone_response

    phone_confirmation_question_asked = should_ask_phone_confirmation(persisted_fields)
    conversation_history = get_recent_conversation_history(whatsapp_number)

    try:
        filter_result = extract_qualification_from_openrouter(
            customer_message=message,
            known_whatsapp_number=whatsapp_number,
            phone_confirmation_question_asked=phone_confirmation_question_asked,
            message_sid=message_sid,
            collected_fields=persisted_fields,
            conversation_history=conversation_history,
            conversation_language=conversation_language,
        )
    except OpenRouterConfigurationError as exc:
        raise QualificationServiceUnavailableError from exc
    except OpenRouterTimeoutError as exc:
        _raise_llm_request_failure(
            exc=exc,
            message_sid=message_sid,
            details="OpenRouter request timed out",
        )
    except OpenRouterRequestError as exc:
        _raise_llm_request_failure(
            exc=exc,
            message_sid=message_sid,
            details="OpenRouter request failed",
        )
    except OpenRouterResponseError as exc:
        _raise_llm_request_failure(
            exc=exc,
            message_sid=message_sid,
            details="OpenRouter response is unusable",
        )
    except ExtractionParseError as exc:
        _raise_llm_request_failure(
            exc=exc,
            message_sid=message_sid,
            details="Extraction response JSON is invalid",
        )

    response = build_turn_response(
        whatsapp_number=whatsapp_number,
        filter_result=filter_result,
        language=conversation_language,
    )
    _record_conversation_turn(
        whatsapp_number=whatsapp_number,
        message=message,
        response=response,
    )
    return response
