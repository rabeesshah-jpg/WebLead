"""Database-backed WhatsApp conversation session helpers."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.qualification.conversation_state import get_accepted_fields
from apps.qualification.domain.language_picker_pending import language_picker_pending_timeout
from apps.qualification.domain.language_selection import LANGUAGE_ENGLISH
from apps.qualification.domain.validators import normalize_whatsapp_session_number
from apps.qualification.models import WhatsAppConversationSession

FRESH_SESSION_DEFAULTS: dict[str, object] = {
    "language": None,
    "language_selected_at": None,
    "awaiting_language_reselection": False,
    "language_picker_pending_until": None,
    "menu_pending": False,
    "menu_pending_until": None,
    "last_menu_sent": False,
    "last_menu_id": None,
    "last_menu_timestamp": None,
    "last_message_at": None,
    "human_handoff_requested_at": None,
    "booking_link_sent_at": None,
}


def create_conversation_session(*, whatsapp_number: str) -> WhatsAppConversationSession:
    """Create a new isolated session row with language unset for the language picker."""
    canonical_number = normalize_whatsapp_session_number(whatsapp_number)
    return WhatsAppConversationSession.objects.create(
        whatsapp_number=canonical_number,
        **FRESH_SESSION_DEFAULTS,
    )


def get_or_create_conversation_session(
    *,
    whatsapp_number: str,
) -> tuple[WhatsAppConversationSession, bool]:
    """
    Return an existing session or create a fresh isolated row for this number.

    When Redis already holds qualification progress for this number, treat the
    customer as an existing English conversation so migrated in-flight leads are
    not prompted for language again.
    """
    canonical_number = normalize_whatsapp_session_number(whatsapp_number)
    session, created = WhatsAppConversationSession.objects.get_or_create(
        whatsapp_number=canonical_number,
        defaults=FRESH_SESSION_DEFAULTS,
    )
    if created and session.language is None and get_accepted_fields(canonical_number):
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


def touch_session_last_message_at(
    session: WhatsAppConversationSession,
    *,
    now=None,
) -> WhatsAppConversationSession:
    """Record the latest inbound customer activity timestamp."""
    current = now or timezone.now()
    with transaction.atomic():
        locked = WhatsAppConversationSession.objects.select_for_update().get(pk=session.pk)
        locked.last_message_at = current
        locked.save(update_fields=["last_message_at"])
    session.refresh_from_db()
    return session


def mark_session_human_handoff_requested(
    session: WhatsAppConversationSession,
    *,
    now=None,
) -> WhatsAppConversationSession:
    """Persist a human-handoff request on the WhatsApp session row."""
    current = now or timezone.now()
    with transaction.atomic():
        locked = WhatsAppConversationSession.objects.select_for_update().get(pk=session.pk)
        locked.human_handoff_requested_at = current
        locked.save(update_fields=["human_handoff_requested_at"])
    session.refresh_from_db()
    return session


def clear_session_human_handoff_requested(
    session: WhatsAppConversationSession,
) -> WhatsAppConversationSession:
    """Clear human-handoff state when a conversation restarts."""
    if session.human_handoff_requested_at is None:
        return session
    with transaction.atomic():
        locked = WhatsAppConversationSession.objects.select_for_update().get(pk=session.pk)
        locked.human_handoff_requested_at = None
        locked.save(update_fields=["human_handoff_requested_at"])
    session.refresh_from_db()
    return session


def mark_booking_link_sent(
    session: WhatsAppConversationSession,
    *,
    now=None,
) -> WhatsAppConversationSession:
    """Record that the booking link WhatsApp text was delivered for this session."""
    current = now or timezone.now()
    with transaction.atomic():
        locked = WhatsAppConversationSession.objects.select_for_update().get(pk=session.pk)
        locked.booking_link_sent_at = current
        locked.save(update_fields=["booking_link_sent_at"])
    session.refresh_from_db()
    return session
