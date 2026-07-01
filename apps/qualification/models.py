"""Lead-qualification extraction models and persistent conversation session ORM."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from django.db import models

ProjectType = Literal["new_website", "website_upgrade"]


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

    class Meta:
        db_table = "qualification_whatsapp_conversation_session"
        verbose_name = "WhatsApp conversation session"
        verbose_name_plural = "WhatsApp conversation sessions"

    def __str__(self) -> str:
        return self.whatsapp_number
