"""Tests for numbered business_type question (replaces project_type option_template)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import Client, override_settings

from apps.qualification.conversation_state import clear_conversations, save_accepted_fields
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.domain.numbered_qualification import format_numbered_question
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.tests.internal_api_test_helpers import API_SECRET, internal_api_auth_headers

pytestmark = pytest.mark.django_db

ENDPOINT_PATH = "/api/internal/qualification/extract/"
WHATSAPP_NUMBER = "+923001238888"
BOOKING_LINK = "https://booking.example.com/test-schedule"
BUSINESS_TYPE_QUESTION = format_numbered_question(field="business_type", language="en")


def _seed_ready_for_business_type(number: str = WHATSAPP_NUMBER) -> None:
    save_accepted_fields(
        number,
        {
            "customer_type": "existing_customer"},
    )


@pytest.fixture
def client() -> Client:
    clear_conversations()
    return Client()


@pytest.fixture(autouse=True)
def _reset_state():
    clear_conversations()
    clear_message_sid_cache()
    yield
    clear_conversations()
    clear_message_sid_cache()


def _post(
    client: Client,
    *,
    message: str,
    button_payload: str | None = None,
    input_channel: str = "whatsapp_text",
    number: str = WHATSAPP_NUMBER,
) -> dict:
    payload = {
        "message": message,
        "whatsapp_number": number,
        "input_channel": input_channel}
    if button_payload is not None:
        payload["button_payload"] = button_payload
    response = client.post(
        ENDPOINT_PATH,
        data=payload,
        content_type="application/json",
        **internal_api_auth_headers(),
    )
    assert response.status_code == 200, response.content
    return response.json()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_waiting_for_business_type_returns_plain_numbered_text(mock_extract, client):
    _seed_ready_for_business_type()

    body = _post(client, message="hmm")

    assert body["next_field"] == "business_type"
    assert body.get("conversation_state") == "WAITING_FOR_BUSINESS_TYPE"
    assert body.get("option_template") is None
    assert body["reply_text"] == BUSINESS_TYPE_QUESTION
    assert "1. Local service business" in body["reply_text"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@pytest.mark.parametrize(
    ("button_payload", "message"),
    [
        ("new_website", "ignored label"),
        ("website_upgrade", "ignored label"),
        ("both", "ignored label"),
    ],
)
def test_legacy_project_type_button_payload_is_ignored(mock_extract, client, button_payload, message):
    _seed_ready_for_business_type()

    body = _post(
        client,
        message=message,
        button_payload=button_payload,
    )

    assert "business_type" not in body["accepted_fields"]
    assert body["next_field"] == "business_type"
    assert body.get("option_template") is None
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@pytest.mark.parametrize(
    ("message", "expected_value"),
    [
        ("1", "biz_local_service"),
        ("2", "biz_coaching"),
        ("3", "biz_ecommerce"),
        ("4", "biz_other"),
    ],
)
def test_numeric_business_type_capture(mock_extract, client, message, expected_value):
    _seed_ready_for_business_type()

    body = _post(client, message=message)

    assert body["accepted_fields"]["business_type"] == expected_value
    assert body["accepted_fields"]["business_type_number"] == int(message)
    assert body["next_field"] == "website_status"
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_valid_business_type_does_not_repeat_question(mock_extract, client):
    _seed_ready_for_business_type()

    body = _post(client, message="1")

    assert body["next_field"] == "website_status"
    assert "What best describes your business?" not in body["reply_text"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_business_type_stage_does_not_send_booking_link(mock_extract, client):
    _seed_ready_for_business_type()

    body = _post(client, message="1")

    assert body["qualification_status"] == "in_progress"
    assert body["send_booking_link"] is False
    assert body["booking_link_sent"] is False
    assert BOOKING_LINK not in body["reply_text"]


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
def test_voice_business_type_uses_spoken_numbered_options():
    from apps.qualification.channels import finalize_turn_response
    from apps.qualification.conversation_flow import try_handle_qualification_step_turn

    number = "+923001238887"
    clear_conversations()
    save_accepted_fields(number, {"customer_type": "existing_customer"})

    turn = try_handle_qualification_step_turn(
        whatsapp_number=number,
        message="maybe",
        language="en",
        for_voice=True,
    )
    assert turn is not None
    body = finalize_turn_response(
        turn,
        input_channel="whatsapp_voice_note",
        conversation_language="en",
        whatsapp_number=number,
    )

    assert body["next_field"] == "business_type"
    assert body.get("option_template") is None
    assert "What best describes your business?" in body["spoken_text"]
    assert body["should_send_audio"] is True
    assert body["should_send_text"] is False
    assert body["whatsapp_text"] == ""


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_booking_link_remains_idempotent_after_completion(mock_extract, client):
    from apps.qualification.domain.numbered_qualification import (
        NUMBERED_QUALIFICATION_FIELDS,
        apply_numbered_selection,
        normalize_numbered_qualification_answer,
    )

    fields = {"customer_type": "existing_customer"}
    for field in NUMBERED_QUALIFICATION_FIELDS:
        selection = normalize_numbered_qualification_answer(field, "1", language="en")
        assert selection is not None
        fields = apply_numbered_selection(fields, field, selection)
    save_accepted_fields(WHATSAPP_NUMBER, fields)

    first = _post(client, message="thanks")
    assert first["qualification_status"] == "completed"
    assert first["booking_link_sent"] is True

    second = _post(client, message="thanks again")
    assert second["qualification_status"] == "completed"
    assert BOOKING_LINK not in second["reply_text"]
    assert get_customer_message(language="en", key="post_booking_thanks") in second[
        "reply_text"
    ] or "booking link above" in second["reply_text"]
