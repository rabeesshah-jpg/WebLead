"""Reset qualification conversation state for a new conversation cycle."""

from __future__ import annotations

from apps.qualification.conversation_state import clear_conversation_for_customer
from apps.qualification.domain.menu_picker_pending import clear_menu_pending
from apps.qualification.domain.language_picker_pending import clear_language_picker_pending
from apps.qualification.models import WhatsAppConversationSession
from apps.qualification.services.conversation_session_service import (
    clear_existing_customer_live_agent_state,
    clear_session_human_handoff_requested,
    clear_session_language,
    reset_onboarding_intro_sent,
)


def _clear_qualification_progress(
    *,
    whatsapp_number: str,
    session: WhatsAppConversationSession,
) -> None:
    """Clear qualification fields, language, and in-flight session flags."""
    clear_conversation_for_customer(whatsapp_number)
    clear_menu_pending(session=session)
    clear_language_picker_pending(session=session)
    clear_session_human_handoff_requested(session=session)
    clear_session_language(session)
    clear_existing_customer_live_agent_state(session)


def restart_qualification_conversation(
    *,
    whatsapp_number: str,
    session: WhatsAppConversationSession,
) -> None:
    """
    Clear in-flight qualification state for a new conversation.

    Preserves the WhatsApp session row and durable existing-customer markers
    (``qualified_at``). Clears language so the language-selection gate runs
    again. Does not clear MessageSid idempotency entries for prior inbound
    messages. Resets onboarding so the next qualification start can show the
    first-contact intro again.

    Clears per-conversation delivery markers and bumps ``conversation_cycle``
    via ``clear_conversation_for_customer``.
    """
    _clear_qualification_progress(whatsapp_number=whatsapp_number, session=session)
    reset_onboarding_intro_sent(session)
    session.refresh_from_db()


def reset_qualification_progress_after_inactivity(
    *,
    whatsapp_number: str,
    session: WhatsAppConversationSession,
) -> None:
    """
    Reset qualification progress when a customer returns after idle timeout.

    Clears accepted fields, language, booking-link delivery flags, and
    onboarding state while preserving the WhatsApp session row and durable
    existing-customer markers.
    """
    restart_qualification_conversation(
        whatsapp_number=whatsapp_number,
        session=session,
    )
