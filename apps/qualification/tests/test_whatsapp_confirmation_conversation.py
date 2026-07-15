"""Regression tests for rich inbound message handling during qualification."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import Client, override_settings

from apps.qualification.conversation_state import clear_conversations, save_accepted_fields
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.models import QualificationFieldFilterResult, RejectedQualificationField
from apps.qualification.tests.internal_api_test_helpers import API_SECRET, internal_api_auth_headers

pytestmark = pytest.mark.django_db

ENDPOINT_PATH = "/api/internal/qualification/extract/"
WHATSAPP_NUMBER = "+923001234567"
BOOKING_LINK = "https://booking.example.com/test-schedule"
COMPLETION_REPLY_TEXT = get_customer_message(
    language="en",
    key="completion_with_booking_link",
    booking_link=BOOKING_LINK,
)


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


def _seed_completed_qualification(mock_extract, client) -> None:
    """Seed the three required fields so qualification is already complete."""
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "project_type": "new_website",
            "requirements": "I need a new website for my restaurant",
            "referral_source": "Facebook",
        },
    )
    mock_extract.reset_mock()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_multiple_services_are_saved_with_next_question(mock_extract, client):
    response = _post(client, "I need a website, SEO, and AI chatbot")

    body = response.json()
    assert response.status_code == 200
    assert body["accepted_fields"]["services_required"] == ["website", "seo", "ai_chatbot"]
    assert body["accepted_fields"]["project_type"] == "new_website"
    assert body["accepted_fields"]["requirements"] == "I need a website, SEO, and AI chatbot"
    assert body["next_field"] == "referral_source"
    assert body["qualification_status"] == "in_progress"
    assert "How did you hear about us?" in body["reply_text"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_question_after_qualification_complete_returns_booking_link(mock_extract, client):
    _seed_completed_qualification(mock_extract, client)

    response = _post(client, "What services do you provide?")

    body = response.json()
    assert response.status_code == 200
    assert body["qualification_status"] == "completed"
    assert body["next_field"] is None
    assert BOOKING_LINK in body["reply_text"]
    assert "best number to reach you" not in body["reply_text"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_unsupported_question_after_qualification_complete_returns_booking_link(mock_extract, client):
    _seed_completed_qualification(mock_extract, client)

    response = _post(client, "Can you guarantee 1 million sales?")

    body = response.json()
    assert response.status_code == 200
    assert body["qualification_status"] == "completed"
    assert body["next_field"] is None
    assert "best number to reach you" not in body["reply_text"]
    assert "Please reply Yes or No" not in body["reply_text"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_requirement_after_qualification_complete_does_not_ask_confirmation(mock_extract, client):
    _seed_completed_qualification(mock_extract, client)

    response = _post(client, "I need a new website and automation")

    body = response.json()
    assert response.status_code == 200
    assert body["qualification_status"] == "completed"
    assert body["next_field"] is None
    assert "Please reply Yes or No" not in body["reply_text"]
    assert "best number to reach you" not in body["reply_text"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_referral_source_completes_and_returns_booking_link(mock_extract, client):
    mock_extract.return_value = _filter_result(
        accepted_fields={"referral_source": "Facebook"},
    )
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "project_type": "new_website",
            "requirements": "I need a new website for my restaurant",
        },
    )

    response = _post(client, "Facebook")

    body = response.json()
    assert response.status_code == 200
    assert body["accepted_fields"]["referral_source"] == "Facebook"
    assert body["qualification_status"] == "completed"
    assert body["next_field"] is None
    assert body["reply_text"] == COMPLETION_REPLY_TEXT
    assert "best number to reach you" not in body["reply_text"]


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_new_and_upgrade_project_type_is_saved_with_next_question(mock_extract, client):
    response = _post(
        client,
        "I have a website to upgrade and also want a new website",
    )

    body = response.json()
    assert response.status_code == 200
    assert body["accepted_fields"]["project_type"] == "new_and_upgrade"
    assert (
        "I have a website to upgrade and also want a new website"
        in body["accepted_fields"]["requirements"]
    )
    assert body["next_field"] == "referral_source"
    assert body["qualification_status"] == "in_progress"
    mock_extract.assert_not_called()
