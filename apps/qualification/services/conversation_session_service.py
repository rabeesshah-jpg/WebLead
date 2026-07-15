"""Database-backed WhatsApp conversation session helpers."""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

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
    "qualified_at": None,
    "existing_customer_connecting_sent_at": None,
    "existing_customer_followup_due_at": None,
    "existing_customer_noura_sent_at": None,
    "existing_customer_followup_sent_at": None,
    "existing_customer_business_type_picker_sent_at": None,
    "accepted_fields": {},
    "conversation_cycle": 1,
    "onboarding_intro_sent": False,
    "last_onboarding_intro_at": None,
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

    When the fast overlay already holds qualification progress for this number,
    treat the customer as an existing English conversation so migrated in-flight
    leads are not prompted for language again.
    """
    from apps.qualification.persistence.backends import get_persistence_backend

    canonical_number = normalize_whatsapp_session_number(whatsapp_number)
    session, created = WhatsAppConversationSession.objects.get_or_create(
        whatsapp_number=canonical_number,
        defaults=FRESH_SESSION_DEFAULTS,
    )
    if created and session.language is None:
        overlay_fields = get_persistence_backend().get_conversation_fields(canonical_number)
        if overlay_fields:
            session.language = LANGUAGE_ENGLISH
            session.onboarding_intro_sent = True
            session.save(update_fields=["language", "onboarding_intro_sent"])
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


def clear_session_language(
    session: WhatsAppConversationSession,
) -> WhatsAppConversationSession:
    """Clear language so the next turn must run the language-selection gate."""
    with transaction.atomic():
        locked = WhatsAppConversationSession.objects.select_for_update().get(pk=session.pk)
        locked.language = None
        locked.language_selected_at = None
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
    """Record that the booking link WhatsApp text was delivered for this session.

    Also stamps the durable ``qualified_at`` marker (once) so returning customers
    are auto-detected as existing even after booking-link / idle-reset clears.
    """
    current = now or timezone.now()
    with transaction.atomic():
        locked = WhatsAppConversationSession.objects.select_for_update().get(pk=session.pk)
        locked.booking_link_sent_at = current
        update_fields = ["booking_link_sent_at"]
        if locked.qualified_at is None:
            locked.qualified_at = current
            update_fields.append("qualified_at")
        locked.save(update_fields=update_fields)
    session.refresh_from_db()
    return session


def clear_existing_customer_live_agent_state(
    session: WhatsAppConversationSession,
) -> WhatsAppConversationSession:
    """Clear connecting/follow-up markers when a conversation cycle restarts."""
    if (
        session.existing_customer_connecting_sent_at is None
        and session.existing_customer_followup_due_at is None
        and session.existing_customer_noura_sent_at is None
        and session.existing_customer_followup_sent_at is None
        and session.existing_customer_business_type_picker_sent_at is None
    ):
        return session
    with transaction.atomic():
        locked = WhatsAppConversationSession.objects.select_for_update().get(pk=session.pk)
        locked.existing_customer_connecting_sent_at = None
        locked.existing_customer_followup_due_at = None
        locked.existing_customer_noura_sent_at = None
        locked.existing_customer_followup_sent_at = None
        locked.existing_customer_business_type_picker_sent_at = None
        locked.save(
            update_fields=[
                "existing_customer_connecting_sent_at",
                "existing_customer_followup_due_at",
                "existing_customer_noura_sent_at",
                "existing_customer_followup_sent_at",
                "existing_customer_business_type_picker_sent_at",
            ],
        )
    session.refresh_from_db()
    return session


def bump_conversation_cycle(
    session: WhatsAppConversationSession,
) -> WhatsAppConversationSession:
    """Advance the conversation cycle id for a fresh qualification attempt."""
    with transaction.atomic():
        locked = WhatsAppConversationSession.objects.select_for_update().get(pk=session.pk)
        locked.conversation_cycle = int(locked.conversation_cycle or 1) + 1
        locked.accepted_fields = {}
        locked.save(update_fields=["conversation_cycle", "accepted_fields"])
    session.refresh_from_db()
    return session


def persist_accepted_fields_to_session(
    *,
    whatsapp_number: str,
    accepted_fields: dict,
) -> WhatsAppConversationSession:
    """Persist qualification accepted_fields to the durable session row."""
    canonical_number = normalize_whatsapp_session_number(whatsapp_number)
    session, _ = get_or_create_conversation_session(whatsapp_number=canonical_number)
    with transaction.atomic():
        locked = WhatsAppConversationSession.objects.select_for_update().get(pk=session.pk)
        locked.accepted_fields = dict(accepted_fields)
        locked.save(update_fields=["accepted_fields"])
    session.refresh_from_db()
    return session


def load_accepted_fields_from_session(whatsapp_number: str) -> dict:
    """Return durable accepted_fields from the session row (empty dict if none)."""
    canonical_number = normalize_whatsapp_session_number(whatsapp_number)
    session = WhatsAppConversationSession.objects.filter(
        whatsapp_number=canonical_number,
    ).first()
    if session is None:
        return {}
    raw = session.accepted_fields
    if isinstance(raw, dict):
        return dict(raw)
    return {}


def clear_session_accepted_fields(
    session: WhatsAppConversationSession,
) -> WhatsAppConversationSession:
    """Clear durable accepted_fields for the current conversation cycle."""
    with transaction.atomic():
        locked = WhatsAppConversationSession.objects.select_for_update().get(pk=session.pk)
        locked.accepted_fields = {}
        locked.save(update_fields=["accepted_fields"])
    session.refresh_from_db()
    return session


def claim_existing_customer_connecting(
    session: WhatsAppConversationSession,
    *,
    followup_delay_seconds: int,
    now=None,
) -> tuple[WhatsAppConversationSession, bool]:
    """
    Persist connecting-message state once per conversation cycle.

    Returns ``(session, claimed)`` where ``claimed`` is True only on the first
    successful claim so delayed jobs are scheduled exactly once.
    """
    current = now or timezone.now()
    with transaction.atomic():
        locked = WhatsAppConversationSession.objects.select_for_update().get(pk=session.pk)
        if locked.existing_customer_connecting_sent_at is not None:
            session.refresh_from_db()
            return session, False
        locked.existing_customer_connecting_sent_at = current
        locked.existing_customer_followup_due_at = current + timedelta(
            seconds=max(0, int(followup_delay_seconds)),
        )
        locked.existing_customer_noura_sent_at = None
        locked.existing_customer_followup_sent_at = None
        locked.existing_customer_business_type_picker_sent_at = None
        locked.save(
            update_fields=[
                "existing_customer_connecting_sent_at",
                "existing_customer_followup_due_at",
                "existing_customer_noura_sent_at",
                "existing_customer_followup_sent_at",
                "existing_customer_business_type_picker_sent_at",
            ],
        )
    session.refresh_from_db()
    return session, True


def claim_existing_customer_noura_send(
    session: WhatsAppConversationSession,
    *,
    now=None,
) -> tuple[WhatsAppConversationSession, bool]:
    """Claim the Noura welcome send exactly once (before Business Type list picker)."""
    current = now or timezone.now()
    with transaction.atomic():
        locked = WhatsAppConversationSession.objects.select_for_update().get(pk=session.pk)
        if locked.existing_customer_noura_sent_at is not None:
            session.refresh_from_db()
            return session, False
        locked.existing_customer_noura_sent_at = current
        locked.save(update_fields=["existing_customer_noura_sent_at"])
    session.refresh_from_db()
    return session, True


def claim_existing_customer_business_type_picker_send(
    session: WhatsAppConversationSession,
    *,
    now=None,
) -> tuple[WhatsAppConversationSession, bool]:
    """Claim the Business Type list-picker send exactly once."""
    current = now or timezone.now()
    with transaction.atomic():
        locked = WhatsAppConversationSession.objects.select_for_update().get(pk=session.pk)
        if locked.existing_customer_business_type_picker_sent_at is not None:
            session.refresh_from_db()
            return session, False
        if locked.existing_customer_noura_sent_at is None:
            session.refresh_from_db()
            return session, False
        locked.existing_customer_business_type_picker_sent_at = current
        locked.save(update_fields=["existing_customer_business_type_picker_sent_at"])
    session.refresh_from_db()
    return session, True


def claim_existing_customer_followup_send(
    session: WhatsAppConversationSession,
    *,
    now=None,
) -> tuple[WhatsAppConversationSession, bool]:
    """
    Claim completion of the existing-customer Noura follow-up once.

    Call after the connecting message was claimed and the Noura WhatsApp text
    send succeeds. Does not require a Business Type list-picker send.
    """
    current = now or timezone.now()
    with transaction.atomic():
        locked = WhatsAppConversationSession.objects.select_for_update().get(pk=session.pk)
        if locked.existing_customer_followup_sent_at is not None:
            session.refresh_from_db()
            return session, False
        if locked.existing_customer_connecting_sent_at is None:
            session.refresh_from_db()
            return session, False
        locked.existing_customer_followup_sent_at = current
        locked.save(update_fields=["existing_customer_followup_sent_at"])
    session.refresh_from_db()
    return session, True


def mark_onboarding_intro_sent(
    session: WhatsAppConversationSession,
    *,
    now=None,
) -> WhatsAppConversationSession:
    """Mark that an onboarding / welcome-back intro was delivered for this turn."""
    current = now or timezone.now()
    with transaction.atomic():
        locked = WhatsAppConversationSession.objects.select_for_update().get(pk=session.pk)
        locked.onboarding_intro_sent = True
        locked.last_onboarding_intro_at = current
        locked.save(update_fields=["onboarding_intro_sent", "last_onboarding_intro_at"])
    session.refresh_from_db()
    return session


def reset_onboarding_intro_sent(
    session: WhatsAppConversationSession,
) -> WhatsAppConversationSession:
    """Clear onboarding so the next inbound message shows the intro again."""
    if not session.onboarding_intro_sent and session.last_onboarding_intro_at is None:
        return session
    with transaction.atomic():
        locked = WhatsAppConversationSession.objects.select_for_update().get(pk=session.pk)
        locked.onboarding_intro_sent = False
        locked.last_onboarding_intro_at = None
        locked.save(update_fields=["onboarding_intro_sent", "last_onboarding_intro_at"])
    session.refresh_from_db()
    return session
