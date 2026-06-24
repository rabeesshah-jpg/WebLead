"""Tests for lead-qualification extraction prompt and schema."""

from __future__ import annotations

import json

import pytest

from apps.qualification.extractor import ExtractionParseError, parse_extraction_payload
from apps.qualification.prompts import EXTRACTION_SYSTEM_PROMPT, build_extraction_user_message
from apps.qualification.schema import (
    CONFIDENCE_FIELD_NAMES,
    EXTRACTION_JSON_SCHEMA,
    QUALIFICATION_FIELD_NAMES,
)


def test_system_prompt_contains_core_rules():
    assert "Never invent, assume, or complete missing information" in EXTRACTION_SYSTEM_PROMPT
    assert '"new_website"' in EXTRACTION_SYSTEM_PROMPT
    assert '"website_upgrade"' in EXTRACTION_SYSTEM_PROMPT
    assert "human_handoff_requested" in EXTRACTION_SYSTEM_PROMPT
    assert "0.00: the field value is null" in EXTRACTION_SYSTEM_PROMPT
    assert "known WhatsApp number is context only" in EXTRACTION_SYSTEM_PROMPT
    assert "phone_confirmation_question_asked=false" in EXTRACTION_SYSTEM_PROMPT


def test_user_message_includes_phone_confirmation_context():
    message = build_extraction_user_message(
        customer_message="I need a redesign",
        known_whatsapp_number="+15551234567",
        phone_confirmation_question_asked=True,
    )
    assert "Known WhatsApp number: +15551234567" in message
    assert "Phone confirmation question asked: yes" in message
    assert "Customer message:\nI need a redesign" in message


def test_user_message_defaults_phone_confirmation_context_to_no():
    message = build_extraction_user_message(
        customer_message="I need a redesign",
        known_whatsapp_number="+15551234567",
    )
    assert "Phone confirmation question asked: no" in message


def test_json_schema_required_fields():
    required = set(EXTRACTION_JSON_SCHEMA["required"])
    assert required == {
        "project_type",
        "requirements",
        "referral_source",
        "whatsapp_confirmed",
        "preferred_phone",
        "human_handoff_requested",
        "confidence",
    }
    assert EXTRACTION_JSON_SCHEMA["additionalProperties"] is False

    confidence_required = set(EXTRACTION_JSON_SCHEMA["properties"]["confidence"]["required"])
    assert confidence_required == set(CONFIDENCE_FIELD_NAMES)
    assert set(QUALIFICATION_FIELD_NAMES) == set(CONFIDENCE_FIELD_NAMES)


def test_parse_valid_extraction_payload():
    payload = {
        "project_type": "website_upgrade",
        "requirements": "Redesign with ecommerce",
        "referral_source": "Google",
        "whatsapp_confirmed": True,
        "preferred_phone": "+15551234567",
        "human_handoff_requested": False,
        "confidence": {
            "project_type": 0.98,
            "requirements": 0.94,
            "referral_source": 0.97,
            "whatsapp_confirmed": 0.96,
            "preferred_phone": 0.96,
        },
    }
    result = parse_extraction_payload(payload)
    assert result.project_type == "website_upgrade"
    assert result.requirements == "Redesign with ecommerce"
    assert result.whatsapp_confirmed is True
    assert result.human_handoff_requested is False
    assert result.confidence.project_type == 0.98


def test_parse_rejects_extra_fields():
    payload = {
        "project_type": None,
        "requirements": None,
        "referral_source": None,
        "whatsapp_confirmed": None,
        "preferred_phone": None,
        "human_handoff_requested": False,
        "confidence": {
            "project_type": 0.0,
            "requirements": 0.0,
            "referral_source": 0.0,
            "whatsapp_confirmed": 0.0,
            "preferred_phone": 0.0,
        },
        "unexpected": True,
    }
    with pytest.raises(ExtractionParseError, match="Unexpected fields"):
        parse_extraction_payload(payload)


def test_parse_accepts_explicit_false_whatsapp_confirmed():
    payload = {
        "project_type": None,
        "requirements": None,
        "referral_source": None,
        "whatsapp_confirmed": False,
        "preferred_phone": "+15559876543",
        "human_handoff_requested": False,
        "confidence": {
            "project_type": 0.0,
            "requirements": 0.0,
            "referral_source": 0.0,
            "whatsapp_confirmed": 0.95,
            "preferred_phone": 0.92,
        },
    }
    result = parse_extraction_payload(payload)
    assert result.whatsapp_confirmed is False
    assert result.preferred_phone == "+15559876543"


def test_schema_is_json_serializable():
    json.dumps(EXTRACTION_JSON_SCHEMA)
