"""WhatsApp session inactivity detection for automatic menu display."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from apps.qualification.models import WhatsAppConversationSession


def inactivity_threshold() -> timedelta:
    seconds = getattr(settings, "WHATSAPP_MENU_INACTIVITY_SECONDS", 600)
    return timedelta(seconds=seconds)


def is_session_inactive(
    *,
    session: WhatsAppConversationSession,
    now: datetime | None = None,
) -> bool:
    """
    Return True when the customer has been idle longer than the configured threshold.

    A null ``last_message_at`` means the session has not recorded activity yet and
    is treated as active (not inactive).
    """
    last_message_at = session.last_message_at
    if last_message_at is None:
        return False
    current = now or timezone.now()
    return current - last_message_at >= inactivity_threshold()
