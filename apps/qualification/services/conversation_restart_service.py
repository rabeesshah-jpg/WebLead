"""Reset qualification conversation state while preserving language."""

from __future__ import annotations

from apps.qualification.conversation_state import clear_conversation_for_customer
from apps.qualification.domain.menu_picker_pending import clear_menu_pending
from apps.qualification.domain.language_picker_pending import clear_language_picker_pending
from apps.qualification.models import WhatsAppConversationSession
from apps.qualification.services.conversation_session_service import (
    clear_session_human_handoff_requested,
)


def restart_qualification_conversation(
    *,
    whatsapp_number: str,
    session: WhatsAppConversationSession,
) -> None:
    """
    Clear in-flight qualification state for a customer.

    Preserves the WhatsApp session row and selected language. Does not clear
    MessageSid idempotency entries for prior inbound messages.
    """
    clear_conversation_for_customer(whatsapp_number)
    clear_menu_pending(session=session)
    clear_language_picker_pending(session=session)
    clear_session_human_handoff_requested(session=session)
    session.refresh_from_db()
