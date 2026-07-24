"""Tests for phone-confirmation guardrails."""

from __future__ import annotations

from unittest.mock import patch

from apps.qualification.filtering import filter_qualification_fields
from apps.qualification.models import ExtractionConfidence, QualificationExtraction
from apps.qualification.phone_confirmation import apply_phone_confirmation_guard

RESTAURANT_MESSAGE = "I need a new website for my restaurant. I found you on Facebook."
KNOWN_WHATSAPP_NUMBER = "+923001234567"


def _extraction(
    *,
    project_type: str | None = "new_website",
    requirements: str | None = "I need a new website for my restaurant",
    referral_source: str | None = "Facebook",
    whatsapp_confirmed: bool | None = True,
    preferred_phone: str | None = KNOWN_WHATSAPP_NUMBER,
    human_handoff_requested: bool = False,
    confidence_overrides: dict[str, float] | None = None,
) -> QualificationExtraction:
    confidence = {
        "project_type": 0.95,
        "requirements": 0.92,
        "referral_source": 0.9,
        "whatsapp_confirmed": 0.96,
        "preferred_phone": 0.94}
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


def test_restaurant_facebook_regression_strips_unasked_phone_fields():
    extraction = _extraction()

    guarded = apply_phone_confirmation_guard(
        extraction,
        RESTAURANT_MESSAGE,
        KNOWN_WHATSAPP_NUMBER,
        phone_confirmation_question_asked=False,
    )
    result = filter_qualification_fields(guarded)

    assert result.accepted_fields["project_type"] == "new_website"
    assert result.accepted_fields["requirements"] == "I need a new website for my restaurant"
    assert result.accepted_fields["referral_source"] == "Facebook"
    assert "whatsapp_confirmed" not in result.accepted_fields
    assert "preferred_phone" not in result.accepted_fields
    assert {
        rejected.field_name: rejected.reason for rejected in result.rejected_fields
    } == {
        "whatsapp_confirmed": "null value",
        "preferred_phone": "null value"}


def test_known_whatsapp_number_alone_is_not_evidence_of_confirmation():
    extraction = _extraction()

    guarded = apply_phone_confirmation_guard(
        extraction,
        "Please build my website soon.",
        KNOWN_WHATSAPP_NUMBER,
        phone_confirmation_question_asked=False,
    )

    assert guarded.whatsapp_confirmed is None
    assert guarded.preferred_phone is None
    assert guarded.confidence.whatsapp_confirmed == 0.0
    assert guarded.confidence.preferred_phone == 0.0


def test_bare_yes_without_question_context_does_not_accept_phone_fields():
    extraction = _extraction()

    guarded = apply_phone_confirmation_guard(
        extraction,
        "yes",
        KNOWN_WHATSAPP_NUMBER,
        phone_confirmation_question_asked=False,
    )
    result = filter_qualification_fields(guarded)

    assert "whatsapp_confirmed" not in result.accepted_fields
    assert "preferred_phone" not in result.accepted_fields


def test_explicit_confirmation_with_question_context_is_accepted():
    message = "Yes, this WhatsApp number is the best number to reach me."
    extraction = _extraction()

    guarded = apply_phone_confirmation_guard(
        extraction,
        message,
        KNOWN_WHATSAPP_NUMBER,
        phone_confirmation_question_asked=True,
    )
    result = filter_qualification_fields(guarded)

    assert result.accepted_fields["whatsapp_confirmed"] is True
    assert result.accepted_fields["preferred_phone"] == KNOWN_WHATSAPP_NUMBER


def test_explicit_alternative_phone_with_question_context_is_accepted():
    message = "No, please contact me on +923001234567 instead."
    extraction = _extraction(
        whatsapp_confirmed=False,
        preferred_phone="+923001234567",
        confidence_overrides={"whatsapp_confirmed": 0.95, "preferred_phone": 0.94},
    )

    guarded = apply_phone_confirmation_guard(
        extraction,
        message,
        KNOWN_WHATSAPP_NUMBER,
        phone_confirmation_question_asked=True,
    )
    result = filter_qualification_fields(guarded)

    assert result.accepted_fields["whatsapp_confirmed"] is False
    assert result.accepted_fields["preferred_phone"] == "+923001234567"


def test_model_provided_alternate_phone_not_in_message_is_rejected():
    message = "No, please contact me on +923001234567 instead."
    alternate_known_number = "+923009999999"
    extraction = _extraction(
        whatsapp_confirmed=False,
        preferred_phone="+15559876543",
        confidence_overrides={"whatsapp_confirmed": 0.95, "preferred_phone": 0.94},
    )

    guarded = apply_phone_confirmation_guard(
        extraction,
        message,
        alternate_known_number,
        phone_confirmation_question_asked=True,
    )
    result = filter_qualification_fields(guarded)

    assert result.accepted_fields["whatsapp_confirmed"] is False
    assert result.accepted_fields["preferred_phone"] == "+923001234567"
    assert "+15559876543" not in result.accepted_fields.values()


def test_guardrail_does_not_mutate_original_extraction_object():
    extraction = _extraction()
    before = (
        extraction.whatsapp_confirmed,
        extraction.preferred_phone,
        extraction.confidence.whatsapp_confirmed,
        extraction.confidence.preferred_phone,
    )

    apply_phone_confirmation_guard(
        extraction,
        RESTAURANT_MESSAGE,
        KNOWN_WHATSAPP_NUMBER,
        phone_confirmation_question_asked=False,
    )

    after = (
        extraction.whatsapp_confirmed,
        extraction.preferred_phone,
        extraction.confidence.whatsapp_confirmed,
        extraction.confidence.preferred_phone,
    )
    assert before == after


def test_bare_yes_with_question_context_is_accepted():
    extraction = _extraction()

    guarded = apply_phone_confirmation_guard(
        extraction,
        "yes",
        KNOWN_WHATSAPP_NUMBER,
        phone_confirmation_question_asked=True,
    )
    result = filter_qualification_fields(guarded)

    assert result.accepted_fields["whatsapp_confirmed"] is True
    assert result.accepted_fields["preferred_phone"] == KNOWN_WHATSAPP_NUMBER
