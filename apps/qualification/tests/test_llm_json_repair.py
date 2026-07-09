"""Tests for LLM extraction JSON repair and parse-failure fallback."""

from __future__ import annotations

import json
import logging
from unittest.mock import patch

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from apps.qualification.conversation_state import clear_conversations
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.domain.llm_json_repair import (
    extract_first_json_object,
    strip_markdown_code_fences,
)
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.extractor import ExtractionParseError, parse_extraction_json
from apps.qualification.models import WhatsAppConversationSession
from apps.qualification.qualification_turn import handle_qualification_turn
from apps.qualification.services.extraction_service import ExtractionService
from apps.qualification.tests.internal_api_test_helpers import (
    API_SECRET,
    OPENROUTER_FALLBACK_MESSAGE,
    internal_api_auth_headers,
)
from apps.qualification.tests.test_parse_json import _valid_payload

pytestmark = pytest.mark.django_db

ENDPOINT_PATH = "/api/internal/qualification/extract/"
VALID_WHATSAPP_NUMBER = "+923001234567"
OPENROUTER_PATCH = "apps.qualification.openrouter_client.request_openrouter_completion"


@pytest.fixture(autouse=True)
def _reset_conversation_state():
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()
    yield
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()


def _referral_payload(referral_source: str) -> dict[str, object]:
    return _valid_payload(
        referral_source=referral_source,
        confidence={
            "project_type": 0.95,
            "requirements": 0.92,
            "referral_source": 0.9,
            "whatsapp_confirmed": 0.0,
            "preferred_phone": 0.0,
        },
    )


def _english_session() -> None:
    WhatsAppConversationSession.objects.create(
        whatsapp_number=VALID_WHATSAPP_NUMBER,
        language="en",
        language_selected_at=timezone.now(),
    )


def test_strip_markdown_code_fences_removes_json_fence():
    payload = json.dumps(_valid_payload())
    wrapped = f"```json\n{payload}\n```"
    assert strip_markdown_code_fences(wrapped) == payload


def test_extract_first_json_object_from_extra_text():
    payload = _valid_payload()
    wrapped = f"Here is the extraction:\n{json.dumps(payload)}\nThanks."
    extracted = extract_first_json_object(wrapped)
    assert extracted is not None
    assert json.loads(extracted)["project_type"] == "new_website"


def test_parse_extraction_json_accepts_markdown_wrapped_json():
    payload = json.dumps(_valid_payload())
    wrapped = f"```json\n{payload}\n```"
    result = parse_extraction_json(wrapped)
    assert result.project_type == "new_website"


def test_parse_extraction_json_accepts_extra_text_around_json():
    payload = json.dumps(_valid_payload())
    wrapped = f"Sure, here is the result:\n{payload}\nLet me know if you need more."
    result = parse_extraction_json(wrapped)
    assert result.requirements == "I need a new website"


def test_parse_extraction_json_logs_repair_success_for_markdown(caplog):
    payload = json.dumps(_valid_payload())
    wrapped = f"```json\n{payload}\n```"
    caplog.set_level(logging.INFO, logger="apps.qualification")
    parse_extraction_json(wrapped, message_sid="SMtest000000000000000000000001")
    records = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "apps.qualification"
        and '"event":"llm_extraction_parse_repaired"' in record.message.replace(" ", "")
    ]
    assert len(records) == 1
    assert records[0]["parse_repair_attempted"] is True
    assert records[0]["parse_repair_success"] is True
    assert records[0]["llm_parse_failed"] is False
    assert "raw_response_prefix" in records[0]
    assert "raw_response_length" in records[0]


def test_parse_extraction_json_logs_failure_for_totally_invalid_json(caplog):
    caplog.set_level(logging.INFO, logger="apps.qualification")
    with pytest.raises(ExtractionParseError, match="Invalid JSON"):
        parse_extraction_json("{not valid", message_sid="SMtest000000000000000000000002")
    records = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "apps.qualification"
        and '"event":"llm_extraction_parse_failed"' in record.message.replace(" ", "")
    ]
    assert len(records) == 1
    assert records[0]["llm_parse_failed"] is True
    assert records[0]["parse_repair_success"] is False


def test_handle_qualification_turn_returns_safe_fallback_on_parse_failure():
    _english_session()
    with patch(
        "apps.qualification.qualification_turn.extract_qualification_from_openrouter",
        side_effect=ExtractionParseError("Invalid JSON in extraction response"),
    ):
        response = handle_qualification_turn(
            whatsapp_number=VALID_WHATSAPP_NUMBER,
            message=OPENROUTER_FALLBACK_MESSAGE,
        )
    expected_reply = get_customer_message(language="en", key="llm_parse_fallback")
    assert response["reply_text"] == expected_reply
    assert response["llm_parse_failed"] is True
    assert response["complete"] is False
    assert response["qualification_status"] == "in_progress"


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
def test_invalid_llm_json_returns_http_200_not_502(client: Client):
    _english_session()
    with patch(OPENROUTER_PATCH, return_value="{not valid json"):
        response = client.post(
            ENDPOINT_PATH,
            data=json.dumps(
                {
                    "message": OPENROUTER_FALLBACK_MESSAGE,
                    "whatsapp_number": VALID_WHATSAPP_NUMBER,
                    "input_channel": "whatsapp_text",
                },
            ),
            content_type="application/json",
            **internal_api_auth_headers(),
        )
    assert response.status_code == 200
    body = response.json()
    assert body["llm_parse_failed"] is True
    assert body["complete"] is False
    assert body["whatsapp_text"] == ""
    assert "team will guide you properly in the meeting" in body["reply_text"]


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
def test_markdown_wrapped_llm_json_returns_http_200(client: Client):
    _english_session()
    provider_text = f"```json\n{json.dumps(_referral_payload('Facebook'))}\n```"
    with patch(OPENROUTER_PATCH, return_value=provider_text):
        response = client.post(
            ENDPOINT_PATH,
            data=json.dumps(
                {
                    "message": OPENROUTER_FALLBACK_MESSAGE,
                    "whatsapp_number": VALID_WHATSAPP_NUMBER,
                    "input_channel": "whatsapp_text",
                },
            ),
            content_type="application/json",
            **internal_api_auth_headers(),
        )
    assert response.status_code == 200
    body = response.json()
    assert body.get("llm_parse_failed") is not True
    assert body["accepted_fields"]["referral_source"] == "Facebook"


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
def test_extra_text_around_llm_json_returns_http_200(client: Client):
    _english_session()
    provider_text = (
        "Here is the structured extraction:\n"
        f"{json.dumps(_referral_payload('Instagram'))}\n"
        "End of response."
    )
    with patch(OPENROUTER_PATCH, return_value=provider_text):
        response = client.post(
            ENDPOINT_PATH,
            data=json.dumps(
                {
                    "message": OPENROUTER_FALLBACK_MESSAGE,
                    "whatsapp_number": VALID_WHATSAPP_NUMBER,
                    "input_channel": "whatsapp_text",
                },
            ),
            content_type="application/json",
            **internal_api_auth_headers(),
        )
    assert response.status_code == 200
    body = response.json()
    assert body.get("llm_parse_failed") is not True
    assert body["accepted_fields"]["referral_source"] == "Instagram"


def test_extraction_service_returns_filter_result_for_repaired_json():
    payload = json.dumps(
        _referral_payload("Google"),
    )
    wrapped = f"```json\n{payload}\n```"
    result = ExtractionService().extract_from_provider_text(
        wrapped,
        customer_message=OPENROUTER_FALLBACK_MESSAGE,
        known_whatsapp_number=VALID_WHATSAPP_NUMBER,
    )
    assert result.accepted_fields["referral_source"] == "Google"
