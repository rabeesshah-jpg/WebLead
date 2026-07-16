"""Shared qualification turn handler for text and voice WhatsApp input."""

from __future__ import annotations

from apps.qualification.conversation_flow import (
    build_completed_retry_response,
    build_turn_response,
    is_qualification_complete,
    try_handle_help_request_turn,
    try_handle_qualification_step_turn,
    try_handle_rich_inbound_qualification_turn,
    try_handle_small_talk_qualification_turn,
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
from apps.qualification.domain.llm_parse_fallback import build_llm_parse_failure_response
from apps.qualification.domain.voice_note_responses import (
    build_voice_transcription_unclear_response,
)
from apps.qualification.extractor import ExtractionParseError
from apps.qualification.services.existing_customer_detection import (
    maybe_auto_detect_existing_customer,
)
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


def run_qualification_turn(
    *,
    whatsapp_number: str,
    message: str,
    message_sid: str | None = None,
    for_voice: bool = False,
    button_payload: str | None = None,
) -> dict:
    """Run one shared qualification turn for text and transcribed voice input."""
    return handle_qualification_turn(
        whatsapp_number=whatsapp_number,
        message=message,
        message_sid=message_sid,
        for_voice=for_voice,
        button_payload=button_payload,
    )


def handle_qualification_turn(
    *,
    whatsapp_number: str,
    message: str,
    message_sid: str | None = None,
    for_voice: bool = False,
    button_payload: str | None = None,
) -> dict:
    """Run one qualification turn using the shared conversation flow."""
    normalized_message = " ".join((message or "").split())
    if for_voice and not normalized_message:
        conversation_language = get_conversation_language(whatsapp_number)
        response = build_voice_transcription_unclear_response(
            whatsapp_number=whatsapp_number,
            language=conversation_language,
        )
        _record_conversation_turn(
            whatsapp_number=whatsapp_number,
            message=message or "",
            response=response,
        )
        return response

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

    from apps.qualification.services.existing_customer_live_agent_service import (
        maybe_handle_existing_customer_live_agent_turn,
    )

    live_agent_response = maybe_handle_existing_customer_live_agent_turn(
        whatsapp_number=whatsapp_number,
        language=conversation_language,
        message=message,
    )
    if live_agent_response is not None:
        _record_conversation_turn(
            whatsapp_number=whatsapp_number,
            message=message,
            response=live_agent_response,
        )
        return live_agent_response

    help_response = try_handle_help_request_turn(
        whatsapp_number=whatsapp_number,
        message=message,
        language=conversation_language,
    )
    if help_response is not None:
        _record_conversation_turn(
            whatsapp_number=whatsapp_number,
            message=message,
            response=help_response,
        )
        return help_response

    # Auto-resolve customer_type from the inbound WhatsApp number instead of ever
    # asking the customer_type question. Existing/returning numbers get the sync
    # Twilio connecting → sleep(5) → Noura handoff; unknown numbers are treated
    # as new customers and routed to referral_source. Runs before small talk so
    # a greeting like "Hello" does not preempt this step.
    auto_customer_response = maybe_auto_detect_existing_customer(
        whatsapp_number=whatsapp_number,
        language=conversation_language,
        input_channel="whatsapp_voice_note" if for_voice else "whatsapp_text",
    )
    if auto_customer_response is not None:
        _record_conversation_turn(
            whatsapp_number=whatsapp_number,
            message=message,
            response=auto_customer_response,
        )
        return auto_customer_response

    small_talk_response = try_handle_small_talk_qualification_turn(
        whatsapp_number=whatsapp_number,
        message=message,
        language=conversation_language,
    )
    if small_talk_response is not None:
        _record_conversation_turn(
            whatsapp_number=whatsapp_number,
            message=message,
            response=small_talk_response,
        )
        return small_talk_response

    # Phone confirmation and alternative-phone collection were removed from the
    # flow. The contact number is taken from the inbound WhatsApp number.
    #
    # Menu option steps (customer_type, referral_source, numbered questions) are
    # captured deterministically from numbered or keyword answers so that text
    # and transcribed voice notes follow the identical client-approved flow. The
    # free-text requirements step falls through to the rich-inbound / OpenRouter
    # handlers below.
    step_response = try_handle_qualification_step_turn(
        whatsapp_number=whatsapp_number,
        message=message,
        language=conversation_language,
        for_voice=for_voice,
        button_payload=button_payload,
    )
    if step_response is not None:
        _record_conversation_turn(
            whatsapp_number=whatsapp_number,
            message=message,
            response=step_response,
        )
        return step_response

    rich_inbound_response = try_handle_rich_inbound_qualification_turn(
        whatsapp_number=whatsapp_number,
        message=message,
        language=conversation_language,
    )
    if rich_inbound_response is not None:
        _record_conversation_turn(
            whatsapp_number=whatsapp_number,
            message=message,
            response=rich_inbound_response,
        )
        return rich_inbound_response

    conversation_history = get_recent_conversation_history(whatsapp_number)

    try:
        filter_result = extract_qualification_from_openrouter(
            customer_message=message,
            known_whatsapp_number=whatsapp_number,
            phone_confirmation_question_asked=False,
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
    except ExtractionParseError:
        response = build_llm_parse_failure_response(
            whatsapp_number=whatsapp_number,
            language=conversation_language,
        )
        _record_conversation_turn(
            whatsapp_number=whatsapp_number,
            message=message,
            response=response,
        )
        return response

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
