"""Tests for stateful WhatsApp qualification conversation flow."""

from __future__ import annotations

from unittest.mock import ANY, patch

import pytest
from django.test import Client, override_settings

from apps.qualification.conversation_flow import (
    classify_whatsapp_confirmation_reply,
    normalize_confirmation_message,
)
from apps.qualification.conversation_state import clear_conversations
from apps.qualification.tests.internal_api_test_helpers import API_SECRET, internal_api_auth_headers
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.models import QualificationFieldFilterResult, RejectedQualificationField

ENDPOINT_PATH = "/api/internal/qualification/extract/"
WHATSAPP_NUMBER = "+923001234567"
BOOKING_LINK = "https://booking.example.com/test-schedule"
COMPLETION_REPLY_TEXT = "Thank you. I will send you a booking link now."


def _filter_result(
    *,
    accepted_fields: dict[str, object],
    human_handoff_requested: bool = False,
    rejected_fields: tuple[RejectedQualificationField, ...] = (),
) -> QualificationFieldFilterResult:
    return QualificationFieldFilterResult(
        accepted_fields=accepted_fields,
        rejected_fields=rejected_fields,
        human_handoff_requested=human_handoff_requested,
    )


def _post(client: Client, message: str) -> object:
    return client.post(
        ENDPOINT_PATH,
        data={
            "message": message,
            "whatsapp_number": WHATSAPP_NUMBER,
            "input_channel": "whatsapp_text",
        },
        content_type="application/json",
        **internal_api_auth_headers(),
    )


@pytest.fixture
def client() -> Client:
    clear_conversations()
    return Client()


@pytest.fixture(autouse=True)
def _reset_conversation_state():
    clear_conversations()
    clear_message_sid_cache()
    yield
    clear_conversations()
    clear_message_sid_cache()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_first_message_with_website_requirement_asks_for_referral_source(mock_extract, client):
    mock_extract.return_value = _filter_result(
        accepted_fields={
            "project_type": "new_website",
            "requirements": "I need a new website for my restaurant",
        },
        rejected_fields=(
            RejectedQualificationField(field_name="referral_source", reason="null value"),
            RejectedQualificationField(field_name="whatsapp_confirmed", reason="null value"),
            RejectedQualificationField(field_name="preferred_phone", reason="null value"),
        ),
    )

    response = _post(client, "I need a new website for my restaurant.")

    assert response.status_code == 200
    body = response.json()
    assert body["accepted_fields"] == {
        "project_type": "new_website",
        "requirements": "I need a new website for my restaurant",
    }
    assert body["next_field"] == "referral_source"
    assert body["reply_text"] == "Thank you. How did you hear about us?"
    assert body["qualification_status"] == "in_progress"
    mock_extract.assert_called_once_with(
        customer_message="I need a new website for my restaurant.",
        known_whatsapp_number=WHATSAPP_NUMBER,
        phone_confirmation_question_asked=False,
        message_sid=None,
        collected_fields={},
        conversation_history=[],
        conversation_language="en",
    )


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_referral_source_response_asks_for_whatsapp_confirmation(mock_extract, client):
    mock_extract.side_effect = [
        _filter_result(
            accepted_fields={
                "project_type": "new_website",
                "requirements": "I need a new website for my restaurant",
            },
        ),
        _filter_result(
            accepted_fields={"referral_source": "Facebook"},
            rejected_fields=(
                RejectedQualificationField(field_name="whatsapp_confirmed", reason="null value"),
                RejectedQualificationField(field_name="preferred_phone", reason="null value"),
            ),
        ),
    ]

    first = _post(client, "I need a new website for my restaurant.")
    second = _post(client, "Facebook")

    assert first.status_code == 200
    assert second.status_code == 200
    body = second.json()
    assert body["accepted_fields"]["referral_source"] == "Facebook"
    assert body["next_field"] == "whatsapp_confirmed"
    assert body["reply_text"] == "Thank you. Is this WhatsApp number the best number to reach you?"
    assert body["qualification_status"] == "in_progress"
    mock_extract.assert_any_call(
        customer_message="Facebook",
        known_whatsapp_number=WHATSAPP_NUMBER,
        phone_confirmation_question_asked=False,
        message_sid=None,
        collected_fields={
            "project_type": "new_website",
            "requirements": "I need a new website for my restaurant",
        },
        conversation_history=ANY,
        conversation_language="en",
    )


def _reach_whatsapp_confirmation_prompt(mock_extract, client) -> None:
    mock_extract.side_effect = [
        _filter_result(
            accepted_fields={
                "project_type": "new_website",
                "requirements": "I need a new website for my restaurant",
            },
        ),
        _filter_result(accepted_fields={"referral_source": "Facebook"}),
    ]
    _post(client, "I need a new website for my restaurant.")
    _post(client, "Facebook")
    mock_extract.reset_mock()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_customer_confirms_whatsapp_number_completes_qualification(mock_extract, client):
    _reach_whatsapp_confirmation_prompt(mock_extract, client)

    response = _post(client, "Yes")

    body = response.json()
    assert body["accepted_fields"]["whatsapp_confirmed"] is True
    assert body["accepted_fields"]["preferred_phone"] == WHATSAPP_NUMBER
    assert body["preferred_phone"] == WHATSAPP_NUMBER
    assert body["qualification_status"] == "completed"
    assert body["next_field"] is None
    assert body["reply_text"] == COMPLETION_REPLY_TEXT
    assert body["send_booking_link"] is True
    assert body["booking_link"] == BOOKING_LINK
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@pytest.mark.parametrize("message", ["Yes", "Yes it's best", "yep"])
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_whatsapp_confirmation_yes_variants_complete_without_openrouter(
    mock_extract,
    client,
    message,
):
    _reach_whatsapp_confirmation_prompt(mock_extract, client)

    response = _post(client, message)

    body = response.json()
    assert body["qualification_status"] == "completed"
    assert body["accepted_fields"]["whatsapp_confirmed"] is True
    assert body["accepted_fields"]["preferred_phone"] == WHATSAPP_NUMBER
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@pytest.mark.parametrize("message", ["No", "No, use another number"])
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_whatsapp_confirmation_no_variants_ask_for_preferred_phone(
    mock_extract,
    client,
    message,
):
    _reach_whatsapp_confirmation_prompt(mock_extract, client)

    response = _post(client, message)

    body = response.json()
    assert body["qualification_status"] == "in_progress"
    assert body["accepted_fields"]["whatsapp_confirmed"] is False
    assert body["next_field"] == "preferred_phone"
    assert body["reply_text"] == "Please share the best phone number to reach you."
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_whatsapp_confirmation_unclear_reply_reprompts_without_openrouter(mock_extract, client):
    _reach_whatsapp_confirmation_prompt(mock_extract, client)

    response = _post(client, "maybe")

    body = response.json()
    assert body["qualification_status"] == "in_progress"
    assert body["next_field"] == "whatsapp_confirmed"
    assert "Please reply Yes" in body["reply_text"]
    assert body["accepted_fields"]["project_type"] == "new_website"
    assert body["accepted_fields"]["referral_source"] == "Facebook"
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_completed_state_retry_remains_completed_without_openrouter(mock_extract, client):
    _reach_whatsapp_confirmation_prompt(mock_extract, client)
    _post(client, "Yes")
    mock_extract.reset_mock()

    response = _post(client, "Yes it's best")

    body = response.json()
    assert body["qualification_status"] == "completed"
    assert body["next_field"] is None
    assert body["reply_text"] == COMPLETION_REPLY_TEXT
    assert body["send_booking_link"] is True
    assert body["booking_link"] == BOOKING_LINK
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_customer_declines_and_gives_alternate_phone_completes_qualification(mock_extract, client):
    alternate_phone = "+923009999999"
    mock_extract.side_effect = [
        _filter_result(
            accepted_fields={
                "project_type": "new_website",
                "requirements": "I need a new website for my restaurant",
            },
        ),
        _filter_result(accepted_fields={"referral_source": "Facebook"}),
        _filter_result(accepted_fields={"preferred_phone": alternate_phone}),
    ]

    _post(client, "I need a new website for my restaurant.")
    _post(client, "Facebook")
    _post(client, "No")
    response = _post(client, f"Please contact me on {alternate_phone}")

    body = response.json()
    assert body["accepted_fields"]["whatsapp_confirmed"] is False
    assert body["accepted_fields"]["preferred_phone"] == alternate_phone
    assert body["preferred_phone"] == alternate_phone
    assert body["qualification_status"] == "completed"
    assert body["reply_text"] == COMPLETION_REPLY_TEXT
    assert body["send_booking_link"] is True
    assert body["booking_link"] == BOOKING_LINK
    assert mock_extract.call_count == 3
    mock_extract.assert_any_call(
        customer_message=f"Please contact me on {alternate_phone}",
        known_whatsapp_number=WHATSAPP_NUMBER,
        phone_confirmation_question_asked=True,
        message_sid=None,
        collected_fields=ANY,
        conversation_history=ANY,
        conversation_language="en",
    )


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_repeated_message_does_not_reset_saved_answers(mock_extract, client):
    mock_extract.side_effect = [
        _filter_result(
            accepted_fields={
                "project_type": "new_website",
                "requirements": "I need a new website for my restaurant",
            },
        ),
        _filter_result(
            accepted_fields={
                "project_type": "website_upgrade",
                "requirements": "Different requirement",
            },
        ),
    ]

    first = _post(client, "I need a new website for my restaurant.")
    second = _post(client, "I need a new website for my restaurant.")

    assert first.status_code == 200
    assert second.status_code == 200
    body = second.json()
    assert body["accepted_fields"]["project_type"] == "new_website"
    assert body["accepted_fields"]["requirements"] == "I need a new website for my restaurant"


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_human_handoff_request_bypasses_normal_questions(mock_extract, client):
    mock_extract.return_value = _filter_result(
        accepted_fields={"requirements": "I need help urgently"},
        human_handoff_requested=True,
    )

    response = _post(client, "Please connect me to a person")

    body = response.json()
    assert body["human_handoff_requested"] is True
    assert body["qualification_status"] == "human_handoff"
    assert body["next_field"] is None
    assert "team member" in body["reply_text"]


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Yes", "yes"),
        ("Yes it's best", "yes"),
        ("yep", "yes"),
        ("No", "no"),
        ("No, use another number", "no"),
        ("maybe", "unclear"),
    ],
)
def test_classify_whatsapp_confirmation_reply(message, expected):
    assert classify_whatsapp_confirmation_reply(message) == expected


def test_normalize_confirmation_message_strips_punctuation_and_extra_spaces():
    assert normalize_confirmation_message("  Yes, it's best!  ") == "yes it's best"
