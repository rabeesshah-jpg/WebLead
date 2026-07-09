"""Tests for the qualification extraction pipeline service."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from apps.qualification.extractor import ExtractionParseError
from apps.qualification.services.extraction_service import ExtractionService
from apps.qualification.tests.test_openrouter_client import (
    CUSTOMER_MESSAGE,
    KNOWN_WHATSAPP_NUMBER,
    _valid_extraction_payload,
)

SERVICE = ExtractionService()


def _provider_text_from_payload(payload: dict[str, object]) -> str:
    return json.dumps(payload)


def test_valid_provider_text_returns_same_filtered_result_as_facade():
    payload = _valid_extraction_payload()
    provider_text = _provider_text_from_payload(payload)

    result = SERVICE.extract_from_provider_text(
        provider_text,
        customer_message=CUSTOMER_MESSAGE,
        known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
    )

    assert result.accepted_fields["project_type"] == "new_website"
    assert result.accepted_fields["requirements"] == "I need a new website for my bakery"
    assert result.accepted_fields["referral_source"] == "Google"
    assert "whatsapp_confirmed" not in result.accepted_fields
    assert "preferred_phone" not in result.accepted_fields
    assert result.human_handoff_requested is False


def test_low_confidence_field_is_rejected():
    payload = _valid_extraction_payload(
        referral_source="Instagram",
        referral_source_confidence=0.5,
    )

    result = SERVICE.extract_from_provider_text(
        _provider_text_from_payload(payload),
        customer_message=CUSTOMER_MESSAGE,
        known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
    )

    assert result.accepted_fields["project_type"] == "new_website"
    assert "referral_source" not in result.accepted_fields
    assert any(rejected.field_name == "referral_source" for rejected in result.rejected_fields)


def test_phone_guardrails_applied_after_parsing_and_before_filtering():
    payload = _valid_extraction_payload(
        whatsapp_confirmed=False,
        preferred_phone="+15559876543",
        whatsapp_confirmed_confidence=0.75,
        preferred_phone_confidence=0.75,
    )

    result = SERVICE.extract_from_provider_text(
        _provider_text_from_payload(payload),
        customer_message="No, please contact me on +15559876543 instead.",
        known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
        phone_confirmation_question_asked=True,
    )

    assert result.accepted_fields["whatsapp_confirmed"] is False
    assert result.accepted_fields["preferred_phone"] == "+15559876543"


def test_invalid_provider_json_propagates_parser_error():
    with pytest.raises(ExtractionParseError, match="Invalid JSON"):
        SERVICE.extract_from_provider_text(
            "not-json",
            customer_message=CUSTOMER_MESSAGE,
            known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
        )


@patch("apps.qualification.integrations.openrouter.urllib.request.urlopen")
def test_service_makes_no_network_calls(mock_urlopen):
    payload = _valid_extraction_payload()
    SERVICE.extract_from_provider_text(
        _provider_text_from_payload(payload),
        customer_message=CUSTOMER_MESSAGE,
        known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
    )
    mock_urlopen.assert_not_called()


def test_pipeline_order_parse_then_phone_guard_then_filter():
    from apps.qualification import extractor, filtering, phone_confirmation

    provider_text = _provider_text_from_payload(_valid_extraction_payload())
    call_order: list[str] = []

    original_parse = extractor.parse_extraction_json
    original_phone = phone_confirmation.apply_phone_confirmation_guard
    original_filter = filtering.filter_qualification_fields

    def _parse(text: str, *, message_sid=None):
        call_order.append("parse")
        return original_parse(text, message_sid=message_sid)

    def _phone(extraction, *args, **kwargs):
        call_order.append("phone")
        return original_phone(extraction, *args, **kwargs)

    def _filter(extraction):
        call_order.append("filter")
        return original_filter(extraction)

    with (
        patch(
            "apps.qualification.services.extraction_service.parse_extraction_json",
            side_effect=_parse,
        ),
        patch(
            "apps.qualification.services.extraction_service.apply_phone_confirmation_guard",
            side_effect=_phone,
        ),
        patch(
            "apps.qualification.services.extraction_service.filter_qualification_fields",
            side_effect=_filter,
        ),
    ):
        SERVICE.extract_from_provider_text(
            provider_text,
            customer_message=CUSTOMER_MESSAGE,
            known_whatsapp_number=KNOWN_WHATSAPP_NUMBER,
        )

    assert call_order == ["parse", "phone", "filter"]
