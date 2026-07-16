"""Pending Twilio language-picker state and safe visible-body fallback."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from apps.qualification.domain.language_selection import LANGUAGE_ARABIC, LANGUAGE_ENGLISH
from apps.qualification.models import WhatsAppConversationSession

PENDING_PICKER_VISIBLE_BODY_ENGLISH = "English"
PENDING_PICKER_VISIBLE_BODY_ARABIC = "العربية"

_PENDING_PICKER_VISIBLE_BODIES: dict[str, str] = {
    PENDING_PICKER_VISIBLE_BODY_ENGLISH: LANGUAGE_ENGLISH,
    PENDING_PICKER_VISIBLE_BODY_ARABIC: LANGUAGE_ARABIC,
}


def normalize_visible_picker_body(body: str | None) -> str:
    """Normalize customer Body text for exact pending-picker matching."""
    if body is None:
        return ""
    return " ".join(body.strip().split())


def language_picker_pending_timeout() -> timedelta:
    seconds = getattr(settings, "LANGUAGE_PICKER_PENDING_TIMEOUT_SECONDS", 900)
    return timedelta(seconds=seconds)


def is_language_picker_pending(
    *,
    session: WhatsAppConversationSession,
    now: datetime | None = None,
) -> bool:
    """Return True when a picker was sent recently and body fallback is allowed."""
    current = now or timezone.now()
    pending_until = session.language_picker_pending_until
    if pending_until is None:
        return False
    return pending_until >= current


def mark_language_picker_pending(
    *,
    session: WhatsAppConversationSession,
    now: datetime | None = None,
) -> datetime:
    """Persist short-lived pending-picker state after a successful picker send."""
    current = now or timezone.now()
    pending_until = current + language_picker_pending_timeout()
    session.language_picker_pending_until = pending_until
    session.save(update_fields=["language_picker_pending_until"])
    return pending_until


def clear_language_picker_pending(*, session: WhatsAppConversationSession) -> None:
    """Clear pending-picker state after a valid language selection."""
    if session.language_picker_pending_until is None:
        return
    session.language_picker_pending_until = None
    session.save(update_fields=["language_picker_pending_until"])


def resolve_pending_picker_body_selection(
    *,
    body: str | None,
    session: WhatsAppConversationSession,
    now: datetime | None = None,
) -> str | None:
    """
    Resolve language from visible Quick Reply body text only while picker is pending.

    Matches exact full-message values ``English`` or ``العربية`` after whitespace
    normalization. Never uses substring matching.
    """
    if not is_language_picker_pending(session=session, now=now):
        return None

    normalized_body = normalize_visible_picker_body(body)
    if not normalized_body:
        return None

    return _PENDING_PICKER_VISIBLE_BODIES.get(normalized_body)
