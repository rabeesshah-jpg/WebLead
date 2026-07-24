"""Tests for post-completion booking link follow-up behavior."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import Client, override_settings

from apps.qualification.conversation_state import clear_conversations, save_accepted_fields
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.models import WhatsAppConversationSession
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


def _post(client: Client, message: str, *, message_sid: str) -> object:
    return client.post(
        ENDPOINT_PATH,
        data={
            "message": message,
            "whatsapp_number": WHATSAPP_NUMBER,
            "input_channel": "whatsapp_text",
            "message_sid": message_sid},
        content_type="application/json",
        **internal_api_auth_headers(),
    )


def _complete_qualification(client: Client) -> dict:
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "project_type": "new_website",
            "requirements": "I need a new website for my restaurant",
            "referral_source": "Facebook"},
    )
    response = _post(client, "Yes", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce80")
    body = response.json()
    assert response.status_code == 200
    assert body["qualification_status"] == "completed"
    assert BOOKING_LINK in body["reply_text"]
    assert body["booking_link_sent"] is True
    assert body.get("conversation_state") == "BOOKING_LINK_SENT"
    return body


@pytest.fixture
def client() -> Client:
    clear_conversations()
    clear_message_sid_cache()
    return Client()


@pytest.fixture(autouse=True)
def _reset_state():
    clear_conversations()
    clear_message_sid_cache()
    yield
    clear_conversations()
    clear_message_sid_cache()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_booking_link_is_sent_once_after_qualification(mock_extract, client):
    body = _complete_qualification(client)
    assert body["reply_text"] == COMPLETION_REPLY_TEXT
    assert body["send_booking_link"] is True
    session = WhatsAppConversationSession.objects.get(whatsapp_number=WHATSAPP_NUMBER)
    assert session.booking_link_sent_at is not None
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_second_message_after_booking_link_does_not_include_raw_url(mock_extract, client):
    _complete_qualification(client)

    response = _post(client, "Ok", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce81")
    body = response.json()

    assert response.status_code == 200
    assert body["qualification_status"] == "completed"
    assert BOOKING_LINK not in body["reply_text"]
    assert body["booking_link_sent"] is True
    assert body["send_booking_link"] is False
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_how_are_you_after_booking_link_does_not_resend_url(mock_extract, client):
    _complete_qualification(client)

    response = _post(client, "How are you", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce82")
    body = response.json()

    assert BOOKING_LINK not in body["reply_text"]
    assert "doing well" in body["reply_text"]
    assert "booking link above" in body["reply_text"]
    assert body["send_booking_link"] is False
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_hi_bro_after_booking_link_does_not_resend_url(mock_extract, client):
    _complete_qualification(client)

    response = _post(client, "Hi bro", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce83")
    body = response.json()

    assert BOOKING_LINK not in body["reply_text"]
    assert body["reply_text"].startswith("Hi.")
    assert "booking link above" in body["reply_text"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_send_link_again_after_booking_link_does_not_resend_url(mock_extract, client):
    _complete_qualification(client)

    response = _post(
        client,
        "Send link again",
        message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce84",
    )
    body = response.json()

    assert BOOKING_LINK not in body["reply_text"]
    assert "already shared above" in body["reply_text"]
    assert body["send_booking_link"] is False
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_exit_chat_after_booking_link_does_not_resend_url(mock_extract, client):
    _complete_qualification(client)

    response = _post(client, "Exit chat", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce85")
    body = response.json()

    assert BOOKING_LINK not in body["reply_text"]
    assert "message us again anytime" in body["reply_text"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@pytest.mark.whatsapp_menu
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_restart_resets_booking_link_sent_for_new_session(mock_extract, client):
    _complete_qualification(client)
    session = WhatsAppConversationSession.objects.get(whatsapp_number=WHATSAPP_NUMBER)
    assert session.booking_link_sent_at is not None

    response = _post(client, "restart", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce86")
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "awaiting_language_selection"
    session.refresh_from_db()
    assert session.booking_link_sent_at is None
    assert session.language is None
    mock_extract.assert_not_called()
