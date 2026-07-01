"""Database-backed WhatsApp conversation session helpers."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.qualification.conversation_state import get_accepted_fields
from apps.qualification.domain.language_picker_pending import language_picker_pending_timeout
from apps.qualification.domain.language_selection import LANGUAGE_ENGLISH
from apps.qualification.models import WhatsAppConversationSession


def create_conversation_session(*, whatsapp_number: str) -> WhatsAppConversationSession:
    """Create a new session row with language unset for future language-picker flow."""
    return WhatsAppConversationSession.objects.create(whatsapp_number=whatsapp_number)


def get_or_create_conversation_session(
    *,
    whatsapp_number: str,
) -> tuple[WhatsAppConversationSession, bool]:
    """
    Return an existing session or create one with language=None.

    When Redis already holds qualification progress for this number, treat the
    customer as an existing English conversation so migrated in-flight leads are
    not prompted for language again.
    """
    session, created = WhatsAppConversationSession.objects.get_or_create(
        whatsapp_number=whatsapp_number,
        defaults={
            "language": None,
            "language_selected_at": None,
        },
    )
    if created and session.language is None and get_accepted_fields(whatsapp_number):
        session.language = LANGUAGE_ENGLISH
        session.save(update_fields=["language"])
    return session, created


def persist_selected_language(
    session: WhatsAppConversationSession,
    language: str,
) -> WhatsAppConversationSession:
    """Persist an explicit or first-time typed language selection."""
    with transaction.atomic():
        locked = WhatsAppConversationSession.objects.select_for_update().get(pk=session.pk)
        locked.language = language
        locked.language_selected_at = timezone.now()
        locked.awaiting_language_reselection = False
        locked.language_picker_pending_until = None
        locked.save(
            update_fields=[
                "language",
                "language_selected_at",
                "awaiting_language_reselection",
                "language_picker_pending_until",
            ],
        )
    session.refresh_from_db()
    return session


def mark_session_language_picker_pending(
    session: WhatsAppConversationSession,
    *,
    now=None,
) -> WhatsAppConversationSession:
    """Persist short-lived pending-picker state after a successful picker send."""
    current = now or timezone.now()
    with transaction.atomic():
        locked = WhatsAppConversationSession.objects.select_for_update().get(pk=session.pk)
        locked.language_picker_pending_until = current + language_picker_pending_timeout()
        locked.save(update_fields=["language_picker_pending_until"])
    session.refresh_from_db()
    return session


def set_awaiting_language_reselection(
    session: WhatsAppConversationSession,
    *,
    awaiting: bool,
) -> WhatsAppConversationSession:
    """Legacy flag retained for backward compatibility; prefer pending-until field."""
    with transaction.atomic():
        locked = WhatsAppConversationSession.objects.select_for_update().get(pk=session.pk)
        locked.awaiting_language_reselection = awaiting
        locked.save(update_fields=["awaiting_language_reselection"])
    session.refresh_from_db()
    return session
