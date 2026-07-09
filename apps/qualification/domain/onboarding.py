"""First-contact and return-after-idle onboarding intro for WhatsApp qualification."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from django.conf import settings
from django.utils import timezone

from apps.qualification.conversation_state import get_accepted_fields
from apps.qualification.conversation_flow import qualification_has_started
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.models import WhatsAppConversationSession
from apps.qualification.services.conversation_session_service import (
    get_or_create_conversation_session,
    mark_onboarding_intro_sent,
)

OnboardingIntroKind = Literal["first_contact", "welcome_back"]


def onboarding_reintro_threshold() -> timedelta:
    """Idle gap after which the next inbound message starts a fresh qualification session."""
    seconds = int(getattr(settings, "ONBOARDING_REINTRO_AFTER_SECONDS", 60))
    return timedelta(seconds=seconds)


def compute_inactivity_gap_seconds(
    session: WhatsAppConversationSession,
    *,
    now: datetime | None = None,
) -> int | None:
    """Return seconds since the previous inbound message, or None when unknown."""
    last_inbound_at = session.last_message_at
    if last_inbound_at is None:
        return None
    current = now or timezone.now()
    return int((current - last_inbound_at).total_seconds())


def should_reset_qualification_after_inactivity(
    session: WhatsAppConversationSession,
    *,
    now: datetime | None = None,
) -> bool:
    """Return True when idle time exceeds the welcome-back threshold."""
    last_inbound_at = session.last_message_at
    if last_inbound_at is None:
        return False
    current = now or timezone.now()
    return current - last_inbound_at >= onboarding_reintro_threshold()


def resolve_onboarding_intro_kind(
    session: WhatsAppConversationSession,
    *,
    now: datetime | None = None,
) -> OnboardingIntroKind | None:
    """
    Decide whether to prepend first-contact onboarding text.

    Full help/menu instructions are not prepended after idle gaps or persona
    interactions. Welcome-back re-intros are handled separately when needed.
    """
    if not session.onboarding_intro_sent:
        return "first_contact"
    return None


def _text_intro_message_key(*, kind: OnboardingIntroKind) -> str:
    if kind == "welcome_back":
        return "onboarding_welcome_back"
    return "onboarding_intro"


def _voice_intro_message_key(*, kind: OnboardingIntroKind) -> str:
    if kind == "welcome_back":
        return "onboarding_welcome_back_voice"
    return "onboarding_intro_voice"


def _resolve_voice_spoken_text_after_onboarding(
    *,
    intro_voice: str,
    body: str,
    language: str,
    kind: OnboardingIntroKind,
) -> str:
    """
    Keep TTS short on voice turns.

    Full onboarding copy is delivered in ``whatsapp_text``. For first contact,
    spoken copy may include a substantive qualification reply when the user
    already provided project details. Welcome-back turns always speak only the
    short re-intro line so stale qualification questions are not read aloud.
    """
    if kind == "welcome_back":
        return intro_voice

    body = body.strip()
    if not body:
        return intro_voice

    ack = get_customer_message(language=language, key="requirement_acknowledged")
    if ack in body:
        return body

    return intro_voice


def maybe_prepend_onboarding_intro(
    response: dict[str, Any],
    *,
    whatsapp_number: str,
    language: str,
    input_channel: str,
    session: WhatsAppConversationSession | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Prepend first-contact or welcome-back intro when needed.

    Does nothing when the response is a non-text status payload (language picker /
    menu awaiting), there is no reply body, or the idle gap is below threshold.
    Does not clear saved qualification fields or restart the conversation.
    """
    if response.get("status") in {
        "awaiting_language_selection",
        "awaiting_menu_selection",
    }:
        return response

    if response.get("skip_onboarding_intro") and not response.get("idle_reset_triggered"):
        return response

    reply_text = str(response.get("reply_text") or "")
    if not reply_text.strip():
        return response

    idle_reset_triggered = bool(response.get("idle_reset_triggered"))
    response_fields = response.get("accepted_fields")
    qualification_started = (
        isinstance(response_fields, dict) and qualification_has_started(response_fields)
    ) or qualification_has_started(get_accepted_fields(whatsapp_number))

    active_session = session
    if active_session is None:
        active_session, _ = get_or_create_conversation_session(
            whatsapp_number=whatsapp_number,
        )
        active_session.refresh_from_db()

    if qualification_started and not idle_reset_triggered:
        if not active_session.onboarding_intro_sent:
            mark_onboarding_intro_sent(active_session, now=now)
        return response

    kind = resolve_onboarding_intro_kind(active_session, now=now)
    if kind is None:
        return response

    body = reply_text.strip()
    intro_text = get_customer_message(
        language=language,
        key=_text_intro_message_key(kind=kind),
    )
    full_text = f"{intro_text}\n\n{body}".strip()

    enriched = dict(response)
    enriched["reply_text"] = full_text

    if input_channel == "whatsapp_voice_note":
        intro_voice = get_customer_message(
            language=language,
            key=_voice_intro_message_key(kind=kind),
        )
        enriched["whatsapp_text"] = full_text
        enriched["spoken_text"] = _resolve_voice_spoken_text_after_onboarding(
            intro_voice=intro_voice,
            body=body,
            language=language,
            kind=kind,
        )
    mark_onboarding_intro_sent(active_session, now=now)
    return enriched
