"""Shared language constants for WhatsApp conversation language selection."""

from __future__ import annotations

from apps.qualification.domain.language_selection import (
    LANGUAGE_ARABIC,
    LANGUAGE_BUTTONS,
    LANGUAGE_ENGLISH,
    normalize_conversation_language,
)
from apps.qualification.models import WhatsAppConversationSession

# Backward-compatible alias used by the foundation phase.
LANGUAGE_BUTTON_PAYLOADS = LANGUAGE_BUTTONS

SUPPORTED_CONVERSATION_LANGUAGES = frozenset({LANGUAGE_ENGLISH, LANGUAGE_ARABIC})

# Model choice values mirror domain language codes.
assert LANGUAGE_ENGLISH == WhatsAppConversationSession.Language.ENGLISH
assert LANGUAGE_ARABIC == WhatsAppConversationSession.Language.ARABIC


def get_conversation_language(whatsapp_number: str) -> str:
    """Load the persisted conversation language for a WhatsApp number."""
    from apps.qualification.services.conversation_session_service import (
        get_or_create_conversation_session,
    )

    session, _ = get_or_create_conversation_session(whatsapp_number=whatsapp_number)
    return normalize_conversation_language(session.language)
