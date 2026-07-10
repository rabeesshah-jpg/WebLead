"""Inbound-message idle reset for WhatsApp qualification sessions."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from apps.qualification.models import WhatsAppConversationSession


def session_idle_reset_threshold() -> timedelta:
    seconds = getattr(settings, "SESSION_IDLE_RESET_SECONDS", 300)
    return timedelta(seconds=seconds)


def session_idle_reset_threshold_seconds() -> int:
    return int(session_idle_reset_threshold().total_seconds())


def compute_inactivity_gap_seconds_from_timestamps(
    *,
    previous_last_activity_at: datetime | None,
    current_inbound_message_time: datetime | None = None,
) -> int | None:
    """Return seconds between the previous inbound activity and the current message."""
    if previous_last_activity_at is None:
        return None
    current = current_inbound_message_time or timezone.now()
    return int((current - previous_last_activity_at).total_seconds())


def should_reset_qualification_after_inactivity(
    inactivity_gap_seconds: int | None,
) -> bool:
    """Return True when the gap meets or exceeds the configured idle reset threshold."""
    if inactivity_gap_seconds is None:
        return False
    return inactivity_gap_seconds >= session_idle_reset_threshold_seconds()
