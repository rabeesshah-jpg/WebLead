"""Tests for raw JSON extraction parsing."""

from __future__ import annotations

import json

import pytest

from apps.qualification.extractor import ExtractionParseError, parse_extraction_json, parse_extraction_payload
from apps.qualification.schema import EXTRACTION_JSON_SCHEMA


def _valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "project_type": "new_website",
        "requirements": "I need a new website",
        "referral_source": None,
        "whatsapp_confirmed": None,
        "preferred_phone": None,
        "human_handoff_requested": False,
        "confidence": {
            "project_type": 0.95,
            "requirements": 0.92,
            "referral_source": 0.0,
            "whatsapp_confirmed": 0.0,
            "preferred_phone": 0.0,
        },
    }
    payload.update(overrides)
    return payload


def test_valid_raw_json_response_parses_successfully():
    raw_json = json.dumps(_valid_payload())
    result = parse_extraction_json(raw_json)
    assert result.project_type == "new_website"
    assert result.requirements == "I need a new website"
    assert result.confidence.project_type == 0.95


def test_malformed_json_is_rejected():
    with pytest.raises(ExtractionParseError, match="Invalid JSON in extraction response"):
        parse_extraction_json("{not valid json")


@pytest.mark.parametrize(
    "raw_json",
    [
        "[]",
        '"string"',
        "1",
        "true",
        "null",
    ],
)
def test_non_object_json_root_is_rejected(raw_json: str):
    with pytest.raises(ExtractionParseError, match="Extraction response must be a JSON object"):
        parse_extraction_json(raw_json)


def test_missing_required_root_field_is_rejected():
    payload = _valid_payload()
    del payload["requirements"]
    with pytest.raises(ExtractionParseError, match="Missing required field: requirements"):
        parse_extraction_payload(payload)


def test_missing_confidence_field_is_rejected():
    payload = _valid_payload()
    confidence = dict(payload["confidence"])
    del confidence["preferred_phone"]
    payload["confidence"] = confidence
    with pytest.raises(ExtractionParseError, match="Missing required field: preferred_phone"):
        parse_extraction_payload(payload)


def test_extra_root_field_is_rejected():
    payload = _valid_payload(unexpected=True)
    with pytest.raises(ExtractionParseError, match="Unexpected fields"):
        parse_extraction_payload(payload)


def test_extra_confidence_field_is_rejected():
    confidence = dict(_valid_payload()["confidence"])
    confidence["extra"] = 0.5
    payload = _valid_payload(confidence=confidence)
    with pytest.raises(ExtractionParseError, match="Unexpected confidence fields"):
        parse_extraction_payload(payload)


def test_invalid_project_type_is_rejected():
    payload = _valid_payload(project_type="mobile_app")
    with pytest.raises(ExtractionParseError, match="project_type must be"):
        parse_extraction_payload(payload)


def test_website_repair_project_type_is_rejected():
    confidence = dict(_valid_payload()["confidence"])
    confidence["project_type"] = 0.95
    payload = _valid_payload(project_type="website_repair", confidence=confidence)

    with pytest.raises(
        ExtractionParseError,
        match="project_type must be new_website, website_upgrade, or null",
    ):
        parse_extraction_payload(payload)

    allowed_values = EXTRACTION_JSON_SCHEMA["properties"]["project_type"]["enum"]
    assert set(allowed_values) == {"new_website", "website_upgrade", None}
    assert "website_repair" not in allowed_values


def test_invalid_data_type_is_rejected():
    payload = _valid_payload(human_handoff_requested="yes")
    with pytest.raises(ExtractionParseError, match="human_handoff_requested must be a boolean"):
        parse_extraction_payload(payload)


@pytest.mark.parametrize("score", [-0.1, 1.1])
def test_confidence_out_of_range_is_rejected(score: float):
    confidence = dict(_valid_payload()["confidence"])
    confidence["project_type"] = score
    payload = _valid_payload(confidence=confidence)
    with pytest.raises(ExtractionParseError, match="must be between 0.0 and 1.0"):
        parse_extraction_payload(payload)


def test_boolean_confidence_is_rejected():
    confidence = dict(_valid_payload()["confidence"])
    confidence["requirements"] = True
    payload = _valid_payload(confidence=confidence)
    with pytest.raises(ExtractionParseError, match="confidence.requirements must be a number"):
        parse_extraction_payload(payload)


def test_invalid_e164_phone_is_rejected():
    payload = _valid_payload(
        preferred_phone="555-1234",
        confidence={
            "project_type": 0.95,
            "requirements": 0.92,
            "referral_source": 0.0,
            "whatsapp_confirmed": 0.0,
            "preferred_phone": 0.9,
        },
    )
    with pytest.raises(ExtractionParseError, match="preferred_phone must be a valid E.164"):
        parse_extraction_payload(payload)


def test_valid_e164_phone_is_accepted():
    payload = _valid_payload(
        preferred_phone="+44 7911 123456",
        confidence={
            "project_type": 0.95,
            "requirements": 0.92,
            "referral_source": 0.0,
            "whatsapp_confirmed": 0.0,
            "preferred_phone": 0.88,
        },
    )
    result = parse_extraction_payload(payload)
    assert result.preferred_phone == "+447911123456"


def test_explicit_whatsapp_confirmed_false_is_accepted():
    payload = _valid_payload(
        whatsapp_confirmed=False,
        preferred_phone="+15559876543",
        confidence={
            "project_type": 0.95,
            "requirements": 0.92,
            "referral_source": 0.0,
            "whatsapp_confirmed": 0.95,
            "preferred_phone": 0.92,
        },
    )
    result = parse_extraction_json(json.dumps(payload))
    assert result.whatsapp_confirmed is False


def test_null_field_with_non_zero_confidence_is_rejected():
    payload = _valid_payload(
        referral_source=None,
        confidence={
            "project_type": 0.95,
            "requirements": 0.92,
            "referral_source": 0.5,
            "whatsapp_confirmed": 0.0,
            "preferred_phone": 0.0,
        },
    )
    with pytest.raises(
        ExtractionParseError,
        match="confidence.referral_source must be 0.0 when referral_source is null",
    ):
        parse_extraction_payload(payload)
