"""Language-gate routing before qualification extraction and external integrations."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

from django.utils import timezone

from apps.qualification.channels import finalize_turn_response
from apps.qualification.conversation_flow import (
    get_active_next_field,
    is_qualification_complete,
)
from apps.qualification.conversation_state import append_conversation_turn, get_accepted_fields
from apps.qualification.domain.language_commands import LanguageCommand, parse_language_command
from apps.qualification.domain.language_picker_pending import resolve_pending_picker_body_selection
from apps.qualification.domain.language_selection import (
    LANGUAGE_ENGLISH,
    normalize_conversation_language,
    resolve_selected_language,
)
from apps.qualification.domain.messages import (
    get_customer_message,
    get_language_changed_confirmation_message,
    get_qualification_question,
)
from apps.qualification.integrations.twilio_language_picker import (
    TwilioLanguagePickerConfigurationError,
    send_language_picker,
)
from apps.qualification.models import WhatsAppConversationSession
from apps.qualification.services.conversation_session_service import (
    get_or_create_conversation_session,
    mark_session_language_picker_pending,
    persist_selected_language,
)

logger = logging.getLogger("apps.qualification")

AWAITING_LANGUAGE_SELECTION_MESSAGE = "Language selector sent."

LanguagePickerSender = Callable[..., str]


class LanguageGateConfigurationError(Exception):
    """Raised when language-picker outbound configuration is incomplete."""


class LanguageGateSendError(Exception):
    """Raised when the Twilio language picker send fails."""


@dataclass(frozen=True)
class LanguageGateResult:
    handled: bool
    response_payload: dict[str, Any] | None = None


def build_awaiting_language_selection_response(
    *,
    language_command_action: str | None = None,
) -> dict[str, str]:
    payload = {
        "status": "awaiting_language_selection",
        "message": AWAITING_LANGUAGE_SELECTION_MESSAGE,
    }
    if language_command_action is not None:
        payload["language_command_action"] = language_command_action
    return payload


def build_qualification_start_response(
    *,
    whatsapp_number: str,
    language: str,
) -> dict[str, Any]:
    """Return the first local qualification question without calling OpenRouter."""
    return build_qualification_step_response(
        whatsapp_number=whatsapp_number,
        language=language,
    )


def build_qualification_step_response(
    *,
    whatsapp_number: str,
    language: str,
) -> dict[str, Any]:
    """Return the next qualification step in the chosen language without resetting lead data."""
    persisted_fields = get_accepted_fields(whatsapp_number)
    normalized_language = normalize_conversation_language(language)
    next_field = get_active_next_field(persisted_fields)

    if is_qualification_complete(persisted_fields):
        from apps.qualification.domain.post_booking_link_response import (
            build_post_booking_link_reply,
        )
        from apps.qualification.services.booking_link_delivery_service import (
            booking_link_already_sent,
        )
        from apps.qualification.services.conversation_session_service import (
            get_or_create_conversation_session,
        )

        session, _ = get_or_create_conversation_session(whatsapp_number=whatsapp_number)
        if booking_link_already_sent(session=session):
            reply_text = build_post_booking_link_reply(message="", language=normalized_language)
            return {
                "accepted_fields": persisted_fields,
                "rejected_fields": {},
                "human_handoff_requested": False,
                "next_field": None,
                "reply_text": reply_text,
                "qualification_status": "completed",
                "preferred_phone": persisted_fields.get("preferred_phone"),
                "conversation_language": normalized_language,
                "booking_link_sent": True,
                "conversation_state": "BOOKING_LINK_SENT",
            }

        from apps.qualification.domain.booking_completion import (
            build_booking_completion_reply,
        )

        booking_fields = build_booking_completion_reply(language=normalized_language)
        return {
            "accepted_fields": persisted_fields,
            "rejected_fields": {},
            "human_handoff_requested": False,
            "next_field": None,
            "reply_text": booking_fields["reply_text"],
            "qualification_status": "completed",
            "preferred_phone": persisted_fields.get("preferred_phone"),
            "conversation_language": normalized_language,
        }

    return {
        "accepted_fields": persisted_fields,
        "rejected_fields": {},
        "human_handoff_requested": False,
        "next_field": next_field,
        "reply_text": get_qualification_question(
            language=normalized_language,
            field=next_field or "project_type",
        ),
        "qualification_status": "in_progress",
        "preferred_phone": persisted_fields.get("preferred_phone"),
        "conversation_language": normalized_language,
    }


def build_language_change_continuation_response(
    *,
    whatsapp_number: str,
    language: str,
) -> dict[str, Any]:
    """Confirm language change and continue from the current pending question."""
    persisted_fields = get_accepted_fields(whatsapp_number)
    normalized_language = normalize_conversation_language(language)
    next_field = get_active_next_field(persisted_fields)
    confirmation = get_language_changed_confirmation_message(language=normalized_language)

    if is_qualification_complete(persisted_fields):
        return {
            "accepted_fields": persisted_fields,
            "rejected_fields": {},
            "human_handoff_requested": False,
            "next_field": None,
            "reply_text": confirmation,
            "qualification_status": "completed",
            "preferred_phone": persisted_fields.get("preferred_phone"),
            "conversation_language": normalized_language,
        }

    question = get_qualification_question(
        language=normalized_language,
        field=next_field or "project_type",
    )
    return {
        "accepted_fields": persisted_fields,
        "rejected_fields": {},
        "human_handoff_requested": False,
        "next_field": next_field,
        "reply_text": f"{confirmation}\n\n{question}",
        "qualification_status": "in_progress",
        "preferred_phone": persisted_fields.get("preferred_phone"),
        "conversation_language": normalized_language,
    }


def format_whatsapp_recipient_address(whatsapp_number: str) -> str:
    if whatsapp_number.startswith("whatsapp:"):
        return whatsapp_number
    return f"whatsapp:{whatsapp_number}"


def trigger_language_flow(
    *,
    session: WhatsAppConversationSession,
    whatsapp_number: str,
    validated_data: dict[str, Any],
    message_sid: str | None,
    input_channel: str,
    language_picker_sender: LanguagePickerSender | None = None,
    language_command_action: str | None = None,
    log_event: str = "language_selector_sent",
    entry_source: str | None = None,
) -> LanguageGateResult:
    """
    Shared entry point for opening the Twilio language picker.

    Used by ``/language`` and the main-menu ``language`` list-picker action.
    """
    sender = language_picker_sender or send_language_picker
    to_number = format_whatsapp_recipient_address(whatsapp_number)
    try:
        sender(to_number=to_number)
    except TwilioLanguagePickerConfigurationError as exc:
        _log_language_gate_event(
            "language_selector_configuration_error",
            whatsapp_number=whatsapp_number,
            message_sid=message_sid,
            error_type=type(exc).__name__,
        )
        raise LanguageGateConfigurationError(str(exc)) from exc
    except Exception as exc:
        _log_language_gate_event(
            "language_selector_send_failed",
            whatsapp_number=whatsapp_number,
            message_sid=message_sid,
            error_type=type(exc).__name__,
        )
        raise LanguageGateSendError("Twilio language picker send failed.") from exc

    mark_session_language_picker_pending(session)
    session.refresh_from_db()

    _log_language_gate_event(
        log_event,
        whatsapp_number=whatsapp_number,
        message_sid=message_sid,
        input_channel=input_channel,
        entry_source=entry_source,
    )
    return LanguageGateResult(
        handled=True,
        response_payload=build_awaiting_language_selection_response(
            language_command_action=language_command_action,
        ),
    )


def _log_language_gate_event(event: str, **context: object) -> None:
    logger.info(json.dumps({"event": event, **context}, separators=(",", ":")))


class LanguageGateService:
    def __init__(
        self,
        *,
        language_picker_sender: LanguagePickerSender | None = None,
    ) -> None:
        self._language_picker_sender = language_picker_sender or send_language_picker

    def evaluate_turn(self, validated_data: dict[str, Any]) -> LanguageGateResult:
        whatsapp_number = validated_data["whatsapp_number"]
        button_payload = validated_data.get("button_payload")
        message = validated_data.get("message")
        input_channel = validated_data["input_channel"]
        message_sid = validated_data.get("message_sid")
        now = timezone.now()

        session, _ = get_or_create_conversation_session(whatsapp_number=whatsapp_number)
        session.refresh_from_db()

        language_command = parse_language_command(message)
        if language_command is not None:
            return self._handle_language_command(
                language_command=language_command,
                session=session,
                whatsapp_number=whatsapp_number,
                validated_data=validated_data,
                message_sid=message_sid,
                input_channel=input_channel,
            )

        button_language = resolve_selected_language(button_payload=button_payload, body=message)
        if button_language is not None:
            return self._apply_language_selection(
                session=session,
                whatsapp_number=whatsapp_number,
                validated_data=validated_data,
                message_sid=message_sid,
                language=button_language,
                via_button=True,
                user_message=message or button_payload or "",
            )

        pending_body_language = resolve_pending_picker_body_selection(
            body=message,
            session=session,
            now=now,
        )
        if pending_body_language is not None:
            return self._apply_language_selection(
                session=session,
                whatsapp_number=whatsapp_number,
                validated_data=validated_data,
                message_sid=message_sid,
                language=pending_body_language,
                via_button=False,
                user_message=message or "",
            )

        if session.language is None:
            return trigger_language_flow(
                session=session,
                whatsapp_number=whatsapp_number,
                validated_data=validated_data,
                message_sid=message_sid,
                input_channel=input_channel,
                language_picker_sender=self._language_picker_sender,
            )

        return LanguageGateResult(handled=False)

    def _send_language_picker(
        self,
        *,
        session: WhatsAppConversationSession,
        whatsapp_number: str,
        message_sid: str | None,
        input_channel: str,
        language_command_action: str | None = None,
        log_event: str = "language_selector_sent",
    ) -> LanguageGateResult:
        return trigger_language_flow(
            session=session,
            whatsapp_number=whatsapp_number,
            validated_data={},
            message_sid=message_sid,
            input_channel=input_channel,
            language_picker_sender=self._language_picker_sender,
            language_command_action=language_command_action,
            log_event=log_event,
        )

    def _apply_language_selection(
        self,
        *,
        session: WhatsAppConversationSession,
        whatsapp_number: str,
        validated_data: dict[str, Any],
        message_sid: str | None,
        language: str,
        via_button: bool,
        user_message: str,
    ) -> LanguageGateResult:
        was_unset = session.language is None
        previous_language = session.language
        persist_selected_language(session, language)
        session.refresh_from_db()

        if was_unset:
            response = self._start_qualification_flow(
                whatsapp_number=whatsapp_number,
                validated_data=validated_data,
                user_message=user_message,
                language=language,
            )
            _log_language_gate_event(
                "language_selection_accepted",
                whatsapp_number=whatsapp_number,
                language=language,
                via_button=via_button,
                message_sid=message_sid,
            )
        else:
            response = self._continue_after_language_change(
                whatsapp_number=whatsapp_number,
                validated_data=validated_data,
                language=language,
                language_command_action="language_changed",
            )
            _log_language_gate_event(
                "language_change_accepted",
                whatsapp_number=whatsapp_number,
                previous_language=previous_language,
                language=language,
                via_button=via_button,
                message_sid=message_sid,
            )

        return LanguageGateResult(handled=True, response_payload=response)

    def _handle_language_command(
        self,
        *,
        language_command: LanguageCommand,
        session: WhatsAppConversationSession,
        whatsapp_number: str,
        validated_data: dict[str, Any],
        message_sid: str | None,
        input_channel: str,
    ) -> LanguageGateResult:
        if language_command.action == "show_picker":
            return trigger_language_flow(
                session=session,
                whatsapp_number=whatsapp_number,
                validated_data=validated_data,
                message_sid=message_sid,
                input_channel=input_channel,
                language_picker_sender=self._language_picker_sender,
                language_command_action="picker_sent",
                log_event="language_command_picker_sent",
            )

        previous_language = session.language
        persist_selected_language(session, language_command.language or LANGUAGE_ENGLISH)
        session.refresh_from_db()
        response = self._continue_after_language_change(
            whatsapp_number=whatsapp_number,
            validated_data=validated_data,
            language=language_command.language or LANGUAGE_ENGLISH,
            language_command_action="language_changed",
        )
        _log_language_gate_event(
            "language_command_set_language",
            whatsapp_number=whatsapp_number,
            previous_language=previous_language,
            language=language_command.language,
            message_sid=message_sid,
        )
        return LanguageGateResult(handled=True, response_payload=response)

    @staticmethod
    def _continue_after_language_change(
        *,
        whatsapp_number: str,
        validated_data: dict[str, Any],
        language: str,
        language_command_action: str | None = None,
    ) -> dict[str, Any]:
        response = build_language_change_continuation_response(
            whatsapp_number=whatsapp_number,
            language=language,
        )
        finalized = finalize_turn_response(
            response,
            input_channel=validated_data["input_channel"],
            transcript=None,
            conversation_language=language,
            whatsapp_number=whatsapp_number,
            user_message=validated_data.get("message") or "",
        )
        if language_command_action is not None:
            finalized["language_command_action"] = language_command_action
        return finalized

    @staticmethod
    def _start_qualification_flow(
        *,
        whatsapp_number: str,
        validated_data: dict[str, Any],
        user_message: str,
        language: str,
    ) -> dict[str, Any]:
        from apps.qualification.domain.onboarding import maybe_prepend_onboarding_intro

        response = build_qualification_start_response(
            whatsapp_number=whatsapp_number,
            language=language,
        )
        response = maybe_prepend_onboarding_intro(
            response,
            whatsapp_number=whatsapp_number,
            language=language,
            input_channel=validated_data["input_channel"],
        )
        finalized = finalize_turn_response(
            response,
            input_channel=validated_data["input_channel"],
            transcript=None,
            conversation_language=language,
            whatsapp_number=whatsapp_number,
            user_message=validated_data.get("message") or "",
        )
        if user_message:
            append_conversation_turn(
                whatsapp_number,
                user_message=user_message,
                assistant_reply=finalized.get("reply_text", ""),
            )
        return finalized
