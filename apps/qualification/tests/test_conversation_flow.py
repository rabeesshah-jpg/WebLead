"""Tests for stateful WhatsApp qualification conversation flow.

The client-approved order is:
    customer_type -> referral_source (new customers only) -> numbered questions
    -> booking link.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import Client, override_settings

from apps.qualification.conversation_flow import (
    classify_whatsapp_confirmation_reply,
    normalize_confirmation_message,
)
from django.utils import timezone

from apps.qualification.domain.messages import get_customer_message
from apps.qualification.conversation_state import clear_conversations, save_accepted_fields
from apps.qualification.tests.internal_api_test_helpers import API_SECRET, internal_api_auth_headers
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.models import (
    QualificationFieldFilterResult,
    RejectedQualificationField,
    WhatsAppConversationSession,
)

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


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_first_turn_auto_assigns_new_customer_and_asks_referral(mock_extract, client):
    response = _post(client, "hmm")

    assert response.status_code == 200
    body = response.json()
    assert body["accepted_fields"]["customer_type"] == "new_customer"
    assert body["next_field"] == "referral_source"
    assert "new customer or an existing customer" not in body["reply_text"]
    assert "How did you hear about us?" in body["reply_text"]
    assert body["qualification_status"] == "in_progress"
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_new_customer_answer_moves_to_referral_source(mock_extract, client):
    response = _post(client, "new customer")

    body = response.json()
    assert body["accepted_fields"]["customer_type"] == "new_customer"
    assert body["next_field"] == "referral_source"
    assert "How did you hear about us?" in body["reply_text"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@patch(
    "apps.qualification.services.existing_customer_live_agent_service.time.sleep",
)
@patch(
    "apps.qualification.services.existing_customer_live_agent_service.send_whatsapp_text_message",
    side_effect=["SMconnecting001", "SMnoura002"],
)
def test_detected_existing_customer_starts_connecting_flow(
    mock_send, mock_sleep, mock_extract, client
):
    now = timezone.now()
    WhatsAppConversationSession.objects.get_or_create(
        whatsapp_number=WHATSAPP_NUMBER,
        defaults={
            "language": "en",
            "language_selected_at": now,
            "booking_link_sent_at": now,
            "qualified_at": now,
        },
    )

    response = _post(client, "existing")

    body = response.json()
    assert body["accepted_fields"]["customer_type"] == "existing_customer"
    assert body["next_field"] == "business_type"
    assert "referral_source" not in body["accepted_fields"]
    assert body.get("option_template") == "business_type"
    assert body["reply_text"] == ""
    assert body["should_send_text"] is False
    assert body["should_send_qualification_question"] is True
    assert body["conversation_state"] == "WAITING_FOR_BUSINESS_TYPE"
    mock_sleep.assert_called_once_with(5)
    assert mock_send.call_count == 2
    mock_extract.assert_not_called()


def _seed_ready_for_final_numbered_question(number: str = WHATSAPP_NUMBER) -> None:
    """Seed everything up to the final numbered question (launch_timeline)."""
    from apps.qualification.domain.numbered_qualification import (
        NUMBERED_QUALIFICATION_FIELDS,
        apply_numbered_selection,
        normalize_numbered_qualification_answer,
    )

    fields: dict = {
        "customer_type": "new_customer",
        "referral_source": "facebook",
    }
    for field in NUMBERED_QUALIFICATION_FIELDS[:-1]:
        selection = normalize_numbered_qualification_answer(field, "1", language="en")
        assert selection is not None
        fields = apply_numbered_selection(fields, field, selection)
    save_accepted_fields(number, fields)


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_final_numbered_answer_sends_booking_link_and_fills_contact(mock_extract, client):
    _seed_ready_for_final_numbered_question()

    response = _post(client, "1")

    body = response.json()
    assert body["next_field"] is None
    assert body["qualification_status"] == "completed"
    assert body["reply_text"] == COMPLETION_REPLY_TEXT
    assert BOOKING_LINK in body["reply_text"]
    assert "best contact number" not in body["reply_text"]
    assert "best number to reach you" not in body["reply_text"]
    # Contact fields are filled internally from the inbound WhatsApp number.
    assert body["accepted_fields"]["whatsapp_confirmed"] is True
    assert body["accepted_fields"]["preferred_phone"] == WHATSAPP_NUMBER
    assert body["preferred_phone"] == WHATSAPP_NUMBER
    assert body["booking_link_sent"] is True
    assert body.get("conversation_state") == "BOOKING_LINK_SENT"


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_phone_confirmation_question_is_never_asked(mock_extract, client):
    for message in ("new", "google", "1", "1", "1", "1", "1"):
        body = _post(client, message).json()
        assert "best contact number" not in body["reply_text"]
        assert "best number to reach you" not in body["reply_text"]
        assert body.get("next_field") not in {"whatsapp_confirmed", "preferred_phone"}


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_completed_state_retry_remains_completed_without_openrouter(mock_extract, client):
    _seed_ready_for_final_numbered_question()
    _post(client, "1")
    mock_extract.reset_mock()

    response = _post(client, "thanks")

    body = response.json()
    assert body["qualification_status"] == "completed"
    assert body["next_field"] is None
    assert BOOKING_LINK not in body["reply_text"]
    assert "booking link above" in body["reply_text"]
    assert body["send_booking_link"] is False
    assert body["booking_link_sent"] is True
    assert body.get("conversation_state") == "BOOKING_LINK_SENT"
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_option_answers_do_not_call_openrouter(mock_extract, client):
    save_accepted_fields(WHATSAPP_NUMBER, {"customer_type": "new_customer"})

    response = _post(client, "4")

    body = response.json()
    assert body["accepted_fields"]["referral_source"] == "friend_referral"
    assert body["next_field"] == "business_type"
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_invalid_final_answer_reasks_without_openrouter(mock_extract, client):
    _seed_ready_for_final_numbered_question()

    response = _post(client, "please connect me to a person right now")

    body = response.json()
    assert body["next_field"] == "launch_timeline"
    assert "How soon would you like to launch" in body["reply_text"]
    mock_extract.assert_not_called()


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Yes", "yes"),
        ("Yes it's best", "yes"),
        ("yep", "yes"),
        ("yeah", "yes"),
        ("confirm", "yes"),
        ("confirmed", "yes"),
        ("haan", "yes"),
        ("han", "yes"),
        ("ji", "yes"),
        ("No", "no"),
        ("No, use another number", "no"),
        ("nahi", "no"),
        ("nahin", "no"),
        ("maybe", "unclear"),
        ("I need a new website", "unclear"),
    ],
)
def test_classify_whatsapp_confirmation_reply(message, expected):
    assert classify_whatsapp_confirmation_reply(message) == expected


def test_normalize_confirmation_message_strips_punctuation_and_extra_spaces():
    assert normalize_confirmation_message("  Yes, it's best!  ") == "yes it's best"
