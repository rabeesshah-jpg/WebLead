"""Per-field confidence filtering for qualification extractions."""

from __future__ import annotations

from apps.qualification.config import get_qualification_confidence_threshold
from apps.qualification.models import (
    QualificationExtraction,
    QualificationFieldFilterResult,
    RejectedQualificationField,
)
from apps.qualification.schema import QUALIFICATION_FIELD_NAMES


def filter_qualification_fields(
    extraction: QualificationExtraction,
) -> QualificationFieldFilterResult:
    """Return only qualification fields that pass the shared confidence threshold."""
    threshold = get_qualification_confidence_threshold()
    accepted_fields: dict[str, object] = {}
    rejected_fields: list[RejectedQualificationField] = []

    for field in QUALIFICATION_FIELD_NAMES:
        value = getattr(extraction, field)
        confidence = getattr(extraction.confidence, field)

        if value is None:
            rejected_fields.append(
                RejectedQualificationField(field_name=field, reason="null value")
            )
            continue

        if confidence < threshold:
            rejected_fields.append(
                RejectedQualificationField(
                    field_name=field,
                    reason="confidence below threshold",
                )
            )
            continue

        accepted_fields[field] = value

    return QualificationFieldFilterResult(
        accepted_fields=accepted_fields,
        rejected_fields=tuple(rejected_fields),
        human_handoff_requested=extraction.human_handoff_requested,
    )
