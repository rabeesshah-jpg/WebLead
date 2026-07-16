"""Pending WhatsApp menu state and numeric option handling."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from apps.qualification.domain.whatsapp_menu_config import MENU_INSTANCE_ID
from apps.qualification.models import WhatsAppConversationSession


def menu_pending_timeout() -> timedelta:
    seconds = getattr(settings, "WHATSAPP_MENU_PENDING_SECONDS", 600)
    return timedelta(seconds=seconds)


def duplicate_menu_suppression_window() -> timedelta:
    seconds = getattr(settings, "WHATSAPP_MENU_DUPLICATE_SUPPRESS_SECONDS", 30)
    return timedelta(seconds=seconds)


def is_menu_pending(
    *,
    session: WhatsAppConversationSession,
    now: datetime | None = None,
) -> bool:
    """Return True when a menu was shown recently and menu replies are allowed."""
    if not session.menu_pending:
        return False
    current = now or timezone.now()
    pending_until = session.menu_pending_until
    if pending_until is None:
        return False
    return pending_until >= current


def should_suppress_duplicate_menu_send(
    *,
    session: WhatsAppConversationSession,
    menu_id: str = MENU_INSTANCE_ID,
    now: datetime | None = None,
) -> bool:
    """Return True when an identical menu was sent within the suppression window."""
    if not session.last_menu_sent:
        return False
    if session.last_menu_id != menu_id:
        return False
    sent_at = session.last_menu_timestamp
    if sent_at is None:
        return False
    current = now or timezone.now()
    return sent_at + duplicate_menu_suppression_window() >= current


def mark_menu_pending(
    *,
    session: WhatsAppConversationSession,
    menu_id: str = MENU_INSTANCE_ID,
    now: datetime | None = None,
) -> datetime:
    """Persist short-lived menu-pending state after showing the menu."""
    current = now or timezone.now()
    pending_until = current + menu_pending_timeout()
    session.menu_pending = True
    session.menu_pending_until = pending_until
    session.last_menu_sent = True
    session.last_menu_id = menu_id
    session.last_menu_timestamp = current
    session.save(
        update_fields=[
            "menu_pending",
            "menu_pending_until",
            "last_menu_sent",
            "last_menu_id",
            "last_menu_timestamp",
        ]
    )
    return pending_until


def clear_menu_pending(*, session: WhatsAppConversationSession) -> None:
    """Clear menu-pending state after a valid menu selection or restart."""
    fields_to_clear = []
    if session.menu_pending:
        session.menu_pending = False
        fields_to_clear.append("menu_pending")
    if session.menu_pending_until is not None:
        session.menu_pending_until = None
        fields_to_clear.append("menu_pending_until")
    if session.last_menu_sent:
        session.last_menu_sent = False
        fields_to_clear.append("last_menu_sent")
    if session.last_menu_id is not None:
        session.last_menu_id = None
        fields_to_clear.append("last_menu_id")
    if session.last_menu_timestamp is not None:
        session.last_menu_timestamp = None
        fields_to_clear.append("last_menu_timestamp")
    if fields_to_clear:
        session.save(update_fields=fields_to_clear)
