"""WhatsApp menu and restart routing before qualification extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from django.conf import settings
from django.utils import timezone

from apps.qualification.channels import finalize_turn_response
from apps.qualification.conversation_state import append_conversation_turn, get_accepted_fields
from apps.qualification.domain.language import get_conversation_language
from apps.qualification.domain.menu_picker_pending import (
    clear_menu_pending,
    is_menu_pending,
    mark_menu_pending,
    should_suppress_duplicate_menu_send,
)
from apps.qualification.domain.session_inactivity import is_session_inactive
from apps.qualification.domain.whatsapp_menu_commands import (
    is_language_button_payload,
    parse_menu_button_payload,
    parse_menu_item_id,
    resolve_menu_action,
)
from apps.qualification.domain.whatsapp_menu_config import MENU_INSTANCE_ID, handle_menu_selection
from apps.qualification.domain.whatsapp_menu_logging import log_whatsapp_menu_event
from apps.qualification.domain.whatsapp_menu_payload import extract_menu_selection_payload
from apps.qualification.integrations.twilio_whatsapp_menu import (
    TwilioWhatsAppMenuConfigurationError,
    TwilioWhatsAppMenuSendError,
    send_whatsapp_menu,
)
from apps.qualification.models import WhatsAppConversationSession
from apps.qualification.services.conversation_restart_service import restart_qualification_conversation
from apps.qualification.services.conversation_session_service import (
    get_or_create_conversation_session,
    mark_onboarding_intro_sent,
    mark_session_human_handoff_requested,
)
from apps.qualification.services.language_gate_service import (
    LanguageGateConfigurationError,
    LanguageGateSendError,
    build_qualification_step_response,
    format_whatsapp_recipient_address,
    trigger_language_flow,
)
from apps.qualification.integrations.twilio_language_picker import send_language_picker

AWAITING_MENU_SELECTION_MESSAGE = "Menu sent."

LanguagePickerSender = Callable[..., str]
WhatsAppMenuSender = Callable[..., str]


@dataclass(frozen=True)
class WhatsAppMenuResult:
    handled: bool
    response_payload: dict[str, Any] | None = None


def is_lead_qualification_enabled() -> bool:
    """Return True when WhatsApp qualification menu flows are enabled."""
    return bool(getattr(settings, "LEAD_QUALIFICATION_ENABLED", True))


def build_awaiting_menu_selection_response() -> dict[str, str]:
    """Return the n8n stop signal after Django sends the interactive menu template."""
    return {
        "status": "awaiting_menu_selection",
        "message": AWAITING_MENU_SELECTION_MESSAGE,
    }


def build_restart_intro_response(*, language: str) -> dict[str, Any]:
    """Return a fresh in-progress qualification response after restart."""
    from apps.qualification.domain.messages import get_customer_message

    return {
        "accepted_fields": {},
        "rejected_fields": {},
        "human_handoff_requested": False,
        "next_field": "project_type",
        "reply_text": get_customer_message(language=language, key="restart_intro"),
        "qualification_status": "in_progress",
        "preferred_phone": None,
        "conversation_language": language,
    }


def build_human_handoff_response(*, whatsapp_number: str, language: str) -> dict[str, Any]:
    """Return a human-handoff response without clearing existing lead data."""
    from apps.qualification.domain.messages import get_customer_message

    accepted_fields = get_accepted_fields(whatsapp_number)
    return {
        "accepted_fields": accepted_fields,
        "rejected_fields": {},
        "human_handoff_requested": True,
        "next_field": None,
        "reply_text": get_customer_message(language=language, key="human_handoff"),
        "qualification_status": "human_handoff",
        "preferred_phone": accepted_fields.get("preferred_phone"),
        "conversation_language": language,
    }


def _with_resolved_menu_payload(validated_data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return validated data enriched with a canonical menu selection when found."""
    menu_id, debug = extract_menu_selection_payload(validated_data)
    if menu_id is None:
        return validated_data, debug
    enriched = dict(validated_data)
    enriched["button_payload"] = menu_id
    return enriched, debug


class WhatsAppMenuService:
    def __init__(
        self,
        *,
        language_picker_sender: LanguagePickerSender | None = None,
        whatsapp_menu_sender: WhatsAppMenuSender | None = None,
    ) -> None:
        self._language_picker_sender = language_picker_sender or send_language_picker
        self._whatsapp_menu_sender = whatsapp_menu_sender or send_whatsapp_menu

    def evaluate_button_payload(
        self,
        validated_data: dict[str, Any],
        *,
        transcript: str | None = None,
    ) -> WhatsAppMenuResult:
        """
        Handle Twilio list-picker menu selections before language gate and extraction.

        List-picker ``ButtonPayload`` values are explicit UI actions.
        """
        if not is_lead_qualification_enabled():
            return WhatsAppMenuResult(handled=False)

        validated_data, selection_debug = _with_resolved_menu_payload(validated_data)
        button_payload = validated_data.get("button_payload")
        if not button_payload or is_language_button_payload(button_payload):
            return WhatsAppMenuResult(handled=False)

        whatsapp_number = validated_data["whatsapp_number"]
        input_channel = validated_data["input_channel"]
        message_sid = validated_data.get("message_sid")
        button_text = validated_data.get("button_text")
        now = timezone.now()

        session, _ = get_or_create_conversation_session(whatsapp_number=whatsapp_number)
        session.refresh_from_db()
        language = get_conversation_language(whatsapp_number)

        menu_id = parse_menu_item_id(button_payload=button_payload)
        if menu_id is None:
            if is_menu_pending(session=session, now=now):
                return self._handle_invalid_menu_input(
                    session=session,
                    whatsapp_number=whatsapp_number,
                    validated_data=validated_data,
                    language=language,
                    message=button_text or button_payload,
                    message_sid=message_sid,
                    input_channel=input_channel,
                )
            return WhatsAppMenuResult(handled=False)

        menu_action = handle_menu_selection(menu_id)
        if menu_action is None:
            return WhatsAppMenuResult(handled=False)

        log_whatsapp_menu_event(
            "MENU_CLICKED",
            message_sid=message_sid,
            user_id=whatsapp_number,
            selected_menu_id=menu_id,
            channel=input_channel,
            source="button",
            **{k: v for k, v in selection_debug.items() if v is not None},
        )
        return self._route_menu_option(
            menu_option=menu_action,
            menu_id=menu_id,
            session=session,
            whatsapp_number=whatsapp_number,
            validated_data=validated_data,
            language=language,
            message=button_text or button_payload,
            message_sid=message_sid,
            input_channel=input_channel,
            source="button",
            transcript=transcript,
        )

    def evaluate_turn(
        self,
        validated_data: dict[str, Any],
        *,
        transcript: str | None = None,
    ) -> WhatsAppMenuResult:
        if not is_lead_qualification_enabled():
            return WhatsAppMenuResult(handled=False)

        validated_data, selection_debug = _with_resolved_menu_payload(validated_data)
        button_payload = validated_data.get("button_payload")
        if button_payload and parse_menu_button_payload(button_payload) is not None:
            return self.evaluate_button_payload(validated_data, transcript=transcript)

        whatsapp_number = validated_data["whatsapp_number"]
        input_channel = validated_data["input_channel"]
        message_sid = validated_data.get("message_sid")
        now = timezone.now()

        message = validated_data.get("message")
        normalized_message = str(message).strip() if message is not None else ""
        resolved = resolve_menu_action(
            button_payload=validated_data.get("button_payload"),
            message=normalized_message or None,
        )
        session, _ = get_or_create_conversation_session(whatsapp_number=whatsapp_number)
        session.refresh_from_db()
        if resolved is None:
            if normalized_message and is_menu_pending(session=session, now=now):
                return self._handle_invalid_menu_input(
                    session=session,
                    whatsapp_number=whatsapp_number,
                    validated_data=validated_data,
                    language=get_conversation_language(whatsapp_number),
                    message=normalized_message,
                    message_sid=message_sid,
                    input_channel=input_channel,
                    transcript=transcript,
                )
            return WhatsAppMenuResult(handled=False)

        language = get_conversation_language(whatsapp_number)

        if resolved.kind == "option" and resolved.option is not None:
            log_whatsapp_menu_event(
                "MENU_CLICKED",
                message_sid=message_sid,
                user_id=whatsapp_number,
                selected_menu_id=resolved.menu_id,
                channel=input_channel,
                source=resolved.source,
                **{k: v for k, v in selection_debug.items() if v is not None},
            )
            return self._route_menu_option(
                menu_option=resolved.option,
                menu_id=resolved.menu_id,
                session=session,
                whatsapp_number=whatsapp_number,
                validated_data=validated_data,
                language=language,
                message=normalized_message,
                message_sid=message_sid,
                input_channel=input_channel,
                transcript=transcript,
                source=resolved.source,
            )

        if resolved.kind == "command" and resolved.command == "restart":
            return self._handle_restart(
                session=session,
                whatsapp_number=whatsapp_number,
                validated_data=validated_data,
                language=language,
                message=normalized_message,
                message_sid=message_sid,
                input_channel=input_channel,
                log_event="whatsapp_restart_command",
                transcript=transcript,
            )

        if resolved.kind == "command" and resolved.command == "show_menu":
            return self._handle_show_menu(
                session=session,
                whatsapp_number=whatsapp_number,
                validated_data=validated_data,
                language=language,
                message=normalized_message,
                message_sid=message_sid,
                input_channel=input_channel,
                log_event="whatsapp_menu_command",
                transcript=transcript,
            )

        return WhatsAppMenuResult(handled=False)

    def evaluate_inactivity(
        self,
        validated_data: dict[str, Any],
        *,
        transcript: str | None = None,
    ) -> WhatsAppMenuResult:
        """
        Show the menu only for explicit inactivity-timer jobs.

        Normal ``whatsapp_text`` / ``whatsapp_voice_note`` inbound messages must
        never auto-open the menu after idle; idle customers get welcome-back
        re-intro via onboarding instead. Callers must pass
        ``event_source == "inactivity_timer"``.
        """
        if not is_lead_qualification_enabled():
            return WhatsAppMenuResult(handled=False)

        if validated_data.get("event_source") != "inactivity_timer":
            return WhatsAppMenuResult(handled=False)

        message = validated_data.get("message")
        if message is None or not str(message).strip():
            return WhatsAppMenuResult(handled=False)

        whatsapp_number = validated_data["whatsapp_number"]
        input_channel = validated_data["input_channel"]
        message_sid = validated_data.get("message_sid")
        now = timezone.now()

        session, _ = get_or_create_conversation_session(whatsapp_number=whatsapp_number)
        session.refresh_from_db()
        if not is_session_inactive(session=session, now=now):
            return WhatsAppMenuResult(handled=False)

        language = get_conversation_language(whatsapp_number)
        return self._handle_show_menu(
            session=session,
            whatsapp_number=whatsapp_number,
            validated_data=validated_data,
            language=language,
            message=str(message).strip(),
            message_sid=message_sid,
            input_channel=input_channel,
            log_event="whatsapp_inactivity_menu",
            transcript=transcript,
            suppress_duplicate_send=True,
        )

    def _finalize(
        self,
        *,
        response: dict[str, Any],
        validated_data: dict[str, Any],
        language: str,
        transcript: str | None = None,
    ) -> dict[str, Any]:
        return finalize_turn_response(
            response,
            input_channel=validated_data["input_channel"],
            transcript=transcript,
            conversation_language=language,
        )

    def _dispatch_whatsapp_menu(
        self,
        *,
        to_number: str,
        whatsapp_number: str,
        message_sid: str | None,
        input_channel: str,
    ) -> str:
        try:
            return self._whatsapp_menu_sender(to_number=to_number)
        except TwilioWhatsAppMenuConfigurationError as exc:
            log_whatsapp_menu_event(
                "MENU_SEND_FAILED",
                message_sid=message_sid,
                user_id=whatsapp_number,
                channel=input_channel,
                error_type=type(exc).__name__,
                reason="configuration_error",
            )
            raise LanguageGateConfigurationError(str(exc)) from exc
        except TwilioWhatsAppMenuSendError as exc:
            log_whatsapp_menu_event(
                "MENU_SEND_FAILED",
                message_sid=message_sid,
                user_id=whatsapp_number,
                channel=input_channel,
                error_type=type(exc).__name__,
                reason="send_failed",
            )
            raise LanguageGateSendError("Twilio WhatsApp menu send failed.") from exc

    def _handle_show_menu(
        self,
        *,
        session: WhatsAppConversationSession,
        whatsapp_number: str,
        validated_data: dict[str, Any],
        language: str,
        message: str,
        message_sid: str | None,
        input_channel: str,
        log_event: str,
        transcript: str | None = None,
        suppress_duplicate_send: bool = False,
    ) -> WhatsAppMenuResult:
        if suppress_duplicate_send and should_suppress_duplicate_menu_send(session=session):
            append_conversation_turn(
                whatsapp_number,
                user_message=message,
                assistant_reply="",
            )
            log_whatsapp_menu_event(
                log_event,
                message_sid=message_sid,
                user_id=whatsapp_number,
                channel=input_channel,
                menu_delivery="duplicate_suppressed",
            )
            return WhatsAppMenuResult(
                handled=True,
                response_payload=build_awaiting_menu_selection_response(),
            )

        mark_menu_pending(session=session, menu_id=MENU_INSTANCE_ID)
        mark_onboarding_intro_sent(session)
        session.refresh_from_db()

        to_number = format_whatsapp_recipient_address(whatsapp_number)
        self._dispatch_whatsapp_menu(
            to_number=to_number,
            whatsapp_number=whatsapp_number,
            message_sid=message_sid,
            input_channel=input_channel,
        )
        append_conversation_turn(
            whatsapp_number,
            user_message=message,
            assistant_reply="",
        )
        log_whatsapp_menu_event(
            log_event,
            message_sid=message_sid,
            user_id=whatsapp_number,
            channel=input_channel,
            menu_delivery="interactive_list",
        )
        return WhatsAppMenuResult(
            handled=True,
            response_payload=build_awaiting_menu_selection_response(),
        )

    def _handle_invalid_menu_input(
        self,
        *,
        session: WhatsAppConversationSession,
        whatsapp_number: str,
        validated_data: dict[str, Any],
        language: str,
        message: str,
        message_sid: str | None,
        input_channel: str,
        transcript: str | None = None,
    ) -> WhatsAppMenuResult:
        log_whatsapp_menu_event(
            "MENU_CLICKED",
            message_sid=message_sid,
            user_id=whatsapp_number,
            channel=input_channel,
            selected_menu_id="invalid",
        )
        return self._handle_show_menu(
            session=session,
            whatsapp_number=whatsapp_number,
            validated_data=validated_data,
            language=language,
            message=message,
            message_sid=message_sid,
            input_channel=input_channel,
            log_event="whatsapp_menu_invalid_selection",
            transcript=transcript,
        )

    def _handle_restart(
        self,
        *,
        session: WhatsAppConversationSession,
        whatsapp_number: str,
        validated_data: dict[str, Any],
        language: str,
        message: str,
        message_sid: str | None,
        input_channel: str,
        log_event: str,
        transcript: str | None = None,
    ) -> WhatsAppMenuResult:
        log_whatsapp_menu_event(
            "MENU_ACTION_EXECUTED",
            message_sid=message_sid,
            user_id=whatsapp_number,
            selected_menu_id="restart",
            action="restart",
            channel=input_channel,
        )
        restart_qualification_conversation(
            whatsapp_number=whatsapp_number,
            session=session,
        )
        response = self._finalize(
            response=build_restart_intro_response(language=language),
            validated_data=validated_data,
            language=language,
            transcript=transcript,
        )
        append_conversation_turn(
            whatsapp_number,
            user_message=message,
            assistant_reply=response.get("reply_text", ""),
        )
        log_whatsapp_menu_event(
            log_event,
            message_sid=message_sid,
            user_id=whatsapp_number,
            channel=input_channel,
        )
        return WhatsAppMenuResult(handled=True, response_payload=response)

    def _route_menu_option(
        self,
        *,
        menu_option: str,
        menu_id: str | None,
        session: WhatsAppConversationSession,
        whatsapp_number: str,
        validated_data: dict[str, Any],
        language: str,
        message: str,
        message_sid: str | None,
        input_channel: str,
        source: str,
        transcript: str | None = None,
    ) -> WhatsAppMenuResult:
        log_whatsapp_menu_event(
            "MENU_ACTION_EXECUTED",
            message_sid=message_sid,
            user_id=whatsapp_number,
            selected_menu_id=menu_id or menu_option,
            action=menu_option,
            channel=input_channel,
            source=source,
        )
        clear_menu_pending(session=session)
        session.refresh_from_db()

        if menu_option == "continue":
            response = self._finalize(
                response=build_qualification_step_response(
                    whatsapp_number=whatsapp_number,
                    language=language,
                ),
                validated_data=validated_data,
                language=language,
                transcript=transcript,
            )
            append_conversation_turn(
                whatsapp_number,
                user_message=message,
                assistant_reply=response.get("reply_text", ""),
            )
            return WhatsAppMenuResult(handled=True, response_payload=response)

        if menu_option == "restart":
            return self._handle_restart(
                session=session,
                whatsapp_number=whatsapp_number,
                validated_data=validated_data,
                language=language,
                message=message,
                message_sid=message_sid,
                input_channel=input_channel,
                log_event="whatsapp_menu_restart",
                transcript=transcript,
            )

        if menu_option == "change_language":
            return self._trigger_language_flow_from_menu(
                session=session,
                whatsapp_number=whatsapp_number,
                validated_data=validated_data,
                language=language,
                message=message,
                message_sid=message_sid,
                input_channel=input_channel,
            )

        mark_session_human_handoff_requested(session)
        session.refresh_from_db()
        response = self._finalize(
            response=build_human_handoff_response(
                whatsapp_number=whatsapp_number,
                language=language,
            ),
            validated_data=validated_data,
            language=language,
            transcript=transcript,
        )
        append_conversation_turn(
            whatsapp_number,
            user_message=message,
            assistant_reply=response.get("reply_text", ""),
        )
        return WhatsAppMenuResult(handled=True, response_payload=response)

    def _trigger_language_flow_from_menu(
        self,
        *,
        session: WhatsAppConversationSession,
        whatsapp_number: str,
        validated_data: dict[str, Any],
        language: str,
        message: str,
        message_sid: str | None,
        input_channel: str,
    ) -> WhatsAppMenuResult:
        gate_result = trigger_language_flow(
            session=session,
            whatsapp_number=whatsapp_number,
            validated_data=validated_data,
            message_sid=message_sid,
            input_channel=input_channel,
            language_picker_sender=self._language_picker_sender,
            language_command_action="picker_sent",
            log_event="whatsapp_menu_language_picker",
            entry_source="main_menu",
        )
        append_conversation_turn(
            whatsapp_number,
            user_message=message,
            assistant_reply="",
        )
        return WhatsAppMenuResult(handled=True, response_payload=gate_result.response_payload)
