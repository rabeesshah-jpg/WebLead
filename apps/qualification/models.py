"""Lead-qualification extraction models and persistent conversation session ORM."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from django.db import models

ProjectType = Literal["new_website", "website_upgrade", "new_and_upgrade"]


@dataclass(frozen=True)
class ExtractionConfidence:
    project_type: float
    requirements: float
    referral_source: float
    whatsapp_confirmed: float
    preferred_phone: float


@dataclass(frozen=True)
class QualificationExtraction:
    project_type: ProjectType | None
    requirements: str | None
    referral_source: str | None
    whatsapp_confirmed: bool | None
    preferred_phone: str | None
    human_handoff_requested: bool
    confidence: ExtractionConfidence


@dataclass(frozen=True)
class RejectedQualificationField:
    field_name: str
    reason: str


@dataclass(frozen=True)
class QualificationFieldFilterResult:
    accepted_fields: dict[str, object]
    rejected_fields: tuple[RejectedQualificationField, ...]
    human_handoff_requested: bool


class WhatsAppConversationSession(models.Model):
    """Persistent WhatsApp customer session metadata (language selection, etc.)."""

    class Language(models.TextChoices):
        ENGLISH = "en", "English"
        ARABIC = "ar", "Arabic"

    whatsapp_number = models.CharField(max_length=32, unique=True, db_index=True)
    language = models.CharField(
        max_length=5,
        choices=Language.choices,
        null=True,
        blank=True,
        db_index=True,
    )
    language_selected_at = models.DateTimeField(null=True, blank=True)
    awaiting_language_reselection = models.BooleanField(default=False, db_index=True)
    language_picker_pending_until = models.DateTimeField(null=True, blank=True, db_index=True)
    menu_pending = models.BooleanField(default=False, db_index=True)
    menu_pending_until = models.DateTimeField(null=True, blank=True, db_index=True)
    last_menu_sent = models.BooleanField(default=False, db_index=True)
    last_menu_id = models.CharField(max_length=64, null=True, blank=True)
    last_menu_timestamp = models.DateTimeField(null=True, blank=True, db_index=True)
    # last_message_at is the last inbound customer activity timestamp (last_inbound_at).
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)
    human_handoff_requested_at = models.DateTimeField(null=True, blank=True, db_index=True)
    booking_link_sent_at = models.DateTimeField(null=True, blank=True, db_index=True)
    # Durable "this number is a qualified/existing customer" marker. Set once when
    # qualification completes and deliberately preserved across restart / idle
    # reset so returning customers can be auto-detected and skip customer_type.
    qualified_at = models.DateTimeField(null=True, blank=True, db_index=True)
    # Existing-customer live-agent connect + delayed Noura follow-up (once per cycle).
    existing_customer_connecting_sent_at = models.DateTimeField(
        null=True, blank=True, db_index=True
    )
    existing_customer_followup_due_at = models.DateTimeField(
        null=True, blank=True, db_index=True
    )
    existing_customer_noura_sent_at = models.DateTimeField(
        null=True, blank=True, db_index=True
    )
    existing_customer_followup_sent_at = models.DateTimeField(
        null=True, blank=True, db_index=True
    )
    existing_customer_business_type_picker_sent_at = models.DateTimeField(
        null=True, blank=True, db_index=True
    )
    # Durable in-progress qualification fields. Cache/Redis remains a fast overlay;
    # this JSON blob is the restart-safe source of truth for the active cycle.
    accepted_fields = models.JSONField(default=dict, blank=True)
    # Bumped on idle reset / menu restart so delivery markers belong to one cycle.
    conversation_cycle = models.PositiveIntegerField(default=1, db_index=True)
    onboarding_intro_sent = models.BooleanField(default=True, db_index=True)
    last_onboarding_intro_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "qualification_whatsapp_conversation_session"
        verbose_name = "WhatsApp conversation session"
        verbose_name_plural = "WhatsApp conversation sessions"

    def __str__(self) -> str:
        return self.whatsapp_number
