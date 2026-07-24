"""Regression tests for rich inbound classification and question handling."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from django.test import Client, override_settings

from apps.qualification.conversation_state import clear_conversations, save_accepted_fields
from apps.qualification.domain.inbound_message_classification import classify_inbound_message
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.domain.tts_safety import spoken_text_contains_url
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.tests.internal_api_test_helpers import API_SECRET, internal_api_auth_headers

pytestmark = pytest.mark.django_db

ENDPOINT_PATH = "/api/internal/qualification/extract/"
WHATSAPP_NUMBER = "+923001234567"
BOOKING_LINK = "https://booking.example.com/test-schedule"
CALL_SID = "CAabcdefghijklmnopqrstuvwxyz012345"


def _post_text(client: Client, message: str) -> object:
    return client.post(
        ENDPOINT_PATH,
        data={
            "message": message,
            "whatsapp_number": WHATSAPP_NUMBER,
            "input_channel": "whatsapp_text"},
        content_type="application/json",
        **internal_api_auth_headers(),
    )


def _post_voice(client: Client, message: str) -> object:
    return client.post(
        ENDPOINT_PATH,
        data=json.dumps(
            {
                "whatsapp_number": WHATSAPP_NUMBER,
                "input_channel": "whatsapp_voice_note",
                "message": message,
                "message_sid": "SM0cc5a1d9e22bf9850ca24261ee23cef1",
                "media_url": (
                    "https://waha.example.com/api/files/true_923246271149@c.us_VOICE001.ogg"
                ),
                "media_content_type": "audio/ogg",
                "call_sid": CALL_SID,
                "utterance_id": "utt-unsupported-1",
                "is_final": True}
        ),
        content_type="application/json",
        **internal_api_auth_headers(),
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


def _reach_whatsapp_confirmation(client: Client) -> None:
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "project_type": "new_website",
            "requirements": "I need a new website for my restaurant",
            "referral_source": "Facebook"},
    )


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_services_question_answers_and_continues_current_question(mock_extract, client):
    response = _post_text(client, "What services do you provide?")

    body = response.json()
    assert response.status_code == 200
    assert "website design" in body["reply_text"]
    assert "SEO" in body["reply_text"]
    assert "new website" in body["reply_text"]
    assert "upgrade" in body["reply_text"]
    assert body["next_field"] == "business_type"
    assert body["classification"] == ["user_question"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_location_question_answers_and_continues_current_question(mock_extract, client):
    response = _post_text(client, "Where are you located?")

    body = response.json()
    assert response.status_code == 200
    assert "work remotely" in body["reply_text"]
    assert "new website" in body["reply_text"]
    assert "upgrade" in body["reply_text"]
    assert body["next_field"] == "business_type"
    assert "user_question" in body["classification"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_unsupported_question_defers_to_meeting_and_continues(mock_extract, client):
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "project_type": "new_website",
            "requirements": "website"},
    )

    response = _post_text(client, "Can you guarantee 1 million sales?")

    body = response.json()
    assert response.status_code == 200
    assert "website specialist" in body["reply_text"]
    assert "How did you hear about Good Websites?" in body["reply_text"]
    assert body["next_field"] == "referral_source"
    assert "unsupported_or_unclear_question" in body["classification"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_multiple_services_saved_without_overwriting_previous(mock_extract, client):
    first = _post_text(client, "I need a website")
    first_body = first.json()
    assert first_body["accepted_fields"]["services_required"] == ["website"]

    second = _post_text(client, "Also need SEO and AI chatbot")
    second_body = second.json()
    assert second_body["accepted_fields"]["services_required"] == [
        "website",
        "seo",
        "ai_chatbot",
    ]
    assert second_body["saved_services"] == ["seo", "ai_chatbot"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_new_and_upgrade_requirement_saved_with_next_question(mock_extract, client):
    response = _post_text(
        client,
        "I want to upgrade my website and also need a new website",
    )

    body = response.json()
    assert response.status_code == 200
    assert body["accepted_fields"]["project_type"] == "new_and_upgrade"
    assert (
        "I want to upgrade my website and also need a new website"
        in body["accepted_fields"]["requirements"]
    )
    assert body["next_field"] == "referral_source"
    assert "service_request" in body["classification"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_combined_requirement_and_location_question(mock_extract, client):
    response = _post_text(
        client,
        "I need a website and automation, also where are you located?",
    )

    body = response.json()
    assert response.status_code == 200
    assert body["accepted_fields"]["services_required"] == ["website", "automation"]
    assert "work remotely" in body["reply_text"]
    assert "I've noted that" in body["reply_text"]
    assert "How did you hear about Good Websites?" in body["reply_text"]
    assert "service_request" in body["classification"]
    assert "user_question" in body["classification"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_question_after_qualification_complete_returns_booking_link(mock_extract, client):
    _reach_whatsapp_confirmation(client)

    response = _post_text(client, "What services do you provide?")

    body = response.json()
    assert response.status_code == 200
    assert body["qualification_status"] == "completed"
    assert body["next_field"] is None
    assert "best number to reach you" not in body["reply_text"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_requirement_after_qualification_complete_does_not_reask(mock_extract, client):
    _reach_whatsapp_confirmation(client)

    response = _post_text(client, "I need automation and SEO")

    body = response.json()
    assert response.status_code == 200
    assert body["qualification_status"] == "completed"
    assert body["next_field"] is None
    assert "Please reply Yes or No" not in body["reply_text"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_completed_session_returns_booking_without_reasking(mock_extract, client):
    _reach_whatsapp_confirmation(client)

    response = _post_text(client, "Yup")

    body = response.json()
    assert response.status_code == 200
    assert body["accepted_fields"]["whatsapp_confirmed"] is True
    assert body["accepted_fields"]["preferred_phone"] == WHATSAPP_NUMBER
    assert body["qualification_status"] == "completed"
    assert body["next_field"] is None
    assert "best number to reach you" not in body["reply_text"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_voice_unsupported_question_has_spoken_fallback_without_url(mock_extract, client):
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "project_type": "new_website",
            "requirements": "website"},
    )

    response = _post_voice(client, "Can you guarantee 1 million sales?")

    body = response.json()
    assert response.status_code == 200
    assert "website specialist" in body["spoken_text"]
    assert spoken_text_contains_url(body["spoken_text"]) is False
    assert body["next_field"] == "referral_source"
    mock_extract.assert_not_called()


def test_classify_combined_service_and_location_message():
    classification = classify_inbound_message(
        "I need a website and automation, also where are you located?"
    )
    assert "website" in classification.service_tokens
    assert "automation" in classification.service_tokens
    assert classification.user_question_location is True
    assert classification.service_request is True
