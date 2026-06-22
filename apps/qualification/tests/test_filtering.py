"""Tests for per-field qualification confidence filtering."""

from __future__ import annotations

from django.test import override_settings

from apps.qualification.filtering import filter_qualification_fields
from apps.qualification.models import ExtractionConfidence, QualificationExtraction


def _extraction(
    *,
    project_type: str | None = "new_website",
    requirements: str | None = "I need a new website",
    referral_source: str | None = "Google",
    whatsapp_confirmed: bool | None = True,
    preferred_phone: str | None = "+15551234567",
    human_handoff_requested: bool = False,
    confidence_overrides: dict[str, float] | None = None,
) -> QualificationExtraction:
    confidence = {
        "project_type": 0.95,
        "requirements": 0.92,
        "referral_source": 0.9,
        "whatsapp_confirmed": 0.96,
        "preferred_phone": 0.94,
    }
    if confidence_overrides:
        confidence.update(confidence_overrides)

    return QualificationExtraction(
        project_type=project_type,
        requirements=requirements,
        referral_source=referral_source,
        whatsapp_confirmed=whatsapp_confirmed,
        preferred_phone=preferred_phone,
        human_handoff_requested=human_handoff_requested,
        confidence=ExtractionConfidence(**confidence),
    )


def test_field_at_exactly_threshold_is_accepted():
    extraction = _extraction(
        requirements="Upgrade homepage",
        confidence_overrides={"requirements": 0.75},
    )
    result = filter_qualification_fields(extraction)
    assert result.accepted_fields["requirements"] == "Upgrade homepage"


def test_field_below_threshold_is_not_accepted():
    extraction = _extraction(
        referral_source="Instagram",
        confidence_overrides={"referral_source": 0.74},
    )
    result = filter_qualification_fields(extraction)
    assert "referral_source" not in result.accepted_fields
    assert any(
        rejected.field_name == "referral_source"
        and rejected.reason == "confidence below threshold"
        for rejected in result.rejected_fields
    )


def test_null_field_with_zero_confidence_is_not_accepted():
    extraction = _extraction(
        referral_source=None,
        confidence_overrides={"referral_source": 0.0},
    )
    result = filter_qualification_fields(extraction)
    assert "referral_source" not in result.accepted_fields
    assert any(
        rejected.field_name == "referral_source" and rejected.reason == "null value"
        for rejected in result.rejected_fields
    )


def test_multiple_fields_are_processed_independently():
    extraction = _extraction(
        requirements="Need ecommerce",
        referral_source="Friend",
        preferred_phone="+15557654321",
        confidence_overrides={
            "requirements": 0.95,
            "referral_source": 0.74,
            "preferred_phone": 0.8,
        },
    )
    result = filter_qualification_fields(extraction)
    assert result.accepted_fields["requirements"] == "Need ecommerce"
    assert result.accepted_fields["preferred_phone"] == "+15557654321"
    assert "referral_source" not in result.accepted_fields


def test_high_confidence_field_accepted_when_another_is_low():
    extraction = _extraction(
        project_type="website_upgrade",
        requirements="Add booking",
        confidence_overrides={"project_type": 0.98, "requirements": 0.5},
    )
    result = filter_qualification_fields(extraction)
    assert result.accepted_fields["project_type"] == "website_upgrade"
    assert "requirements" not in result.accepted_fields
    assert any(rejected.field_name == "requirements" for rejected in result.rejected_fields)


def test_whatsapp_confirmed_false_at_threshold_is_accepted():
    extraction = _extraction(
        whatsapp_confirmed=False,
        preferred_phone="+15559876543",
        confidence_overrides={"whatsapp_confirmed": 0.75, "preferred_phone": 0.75},
    )
    result = filter_qualification_fields(extraction)
    assert result.accepted_fields["whatsapp_confirmed"] is False
    assert result.accepted_fields["preferred_phone"] == "+15559876543"


def test_filtered_output_contains_only_accepted_updates():
    extraction = _extraction(confidence_overrides={"referral_source": 0.6})
    result = filter_qualification_fields(extraction)
    assert set(result.accepted_fields) == {
        "project_type",
        "requirements",
        "whatsapp_confirmed",
        "preferred_phone",
    }
    assert "referral_source" not in result.accepted_fields


def test_original_extraction_object_remains_unchanged():
    extraction = _extraction(
        referral_source="Low trust",
        confidence_overrides={"referral_source": 0.2},
    )
    before = (
        extraction.project_type,
        extraction.referral_source,
        extraction.confidence.referral_source,
        extraction.human_handoff_requested,
    )
    filter_qualification_fields(extraction)
    after = (
        extraction.project_type,
        extraction.referral_source,
        extraction.confidence.referral_source,
        extraction.human_handoff_requested,
    )
    assert before == after


@override_settings(QUALIFICATION_CONFIDENCE_THRESHOLD=0.9)
def test_changed_threshold_is_respected():
    extraction = _extraction(
        requirements="Need blog",
        confidence_overrides={"requirements": 0.89},
    )
    result = filter_qualification_fields(extraction)
    assert "requirements" not in result.accepted_fields

    extraction_accepted = _extraction(
        requirements="Need blog",
        confidence_overrides={"requirements": 0.9},
    )
    accepted_result = filter_qualification_fields(extraction_accepted)
    assert accepted_result.accepted_fields["requirements"] == "Need blog"


def test_human_handoff_requested_is_returned_separately():
    extraction = _extraction(
        human_handoff_requested=True,
        confidence_overrides={"requirements": 0.5},
    )
    result = filter_qualification_fields(extraction)
    assert result.human_handoff_requested is True
    assert "human_handoff_requested" not in result.accepted_fields
