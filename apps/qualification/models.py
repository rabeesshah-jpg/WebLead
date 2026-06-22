"""Lead-qualification extraction models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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
