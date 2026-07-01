"""Tests for local preferred-phone validation without OpenRouter."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from django.test import Client, override_settings

from apps.qualification.conversation_state import clear_conversations, get_accepted_fields, save_accepted_fields
from apps.qualification.domain.language_selection import LANGUAGE_ARABIC, LANGUAGE_ENGLISH
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.message_idempotency import clear_message_sid_cache, get_cached_turn_response
from apps.qualification.models import QualificationFieldFilterResult, WhatsAppConversationSession
from apps.qualification.tests.internal_api_test_helpers import API_SECRET, internal_api_auth_headers

pytestmark = pytest.mark.django_db

ENDPOINT_PATH = "/api/internal/qualification/extract/"
WHATSAPP_NUMBER = "+923001234567"
PREFERRED_PHONE = "+923246271156"
MESSAGE_SID = "SM0cc5a1d9e22bf9850ca24261ee23ce90"
PHONE_MESSAGE_SID = "SM0cc5a1d9e22bf9850ca24261ee23ce91"
BOOKING_LINK = "https://booking.example.com/test-schedule"
COMPLETION_REPLY_TEXT = "Thank you. I will send you a booking link now."

BASE_FIELDS = {
    "project_type": "new_website",
    "requirements": "I need a new website for my restaurant",
    "referral_source": "Facebook",
    "whatsapp_confirmed": False,
}


@pytest.fixture
def client() -> Client:
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()
    return Client()


@pytest.fixture(autouse=True)
def _reset_state():
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()
    yield
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()


def _post(
    client: Client,
    message: str,
    *,
    message_sid: str = MESSAGE_SID,
    whatsapp_number: str = WHATSAPP_NUMBER,
) -> object:
    return client.post(
        ENDPOINT_PATH,
        data={
            "message": message,
            "whatsapp_number": whatsapp_number,
            "input_channel": "whatsapp_text",
            "message_sid": message_sid,
            "media_url": None,
            "media_content_type": None,
        },
        content_type="application/json",
        **internal_api_auth_headers(secret=API_SECRET),
    )


def _seed_preferred_phone_step() -> None:
    save_accepted_fields(WHATSAPP_NUMBER, dict(BASE_FIELDS))


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_valid_preferred_phone_is_accepted_without_openrouter(mock_extract, client):
    _seed_preferred_phone_step()

    response = _post(client, PREFERRED_PHONE, message_sid=PHONE_MESSAGE_SID)

    assert response.status_code == 200
    body = response.json()
    assert body["accepted_fields"]["preferred_phone"] == PREFERRED_PHONE
    assert body["preferred_phone"] == PREFERRED_PHONE
    assert body["qualification_status"] == "completed"
    assert body["next_field"] is None
    assert body["reply_text"] == COMPLETION_REPLY_TEXT
    assert body["send_booking_link"] is True
    assert get_accepted_fields(WHATSAPP_NUMBER)["project_type"] == "new_website"
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_preferred_phone_with_spaces_is_accepted(mock_extract, client):
    _seed_preferred_phone_step()

    response = _post(client, "+92 324 627 1156", message_sid=PHONE_MESSAGE_SID)

    assert response.status_code == 200
    assert response.json()["accepted_fields"]["preferred_phone"] == PREFERRED_PHONE
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_preferred_phone_with_hyphens_is_accepted(mock_extract, client):
    _seed_preferred_phone_step()

    response = _post(client, "+92-324-627-1156", message_sid=PHONE_MESSAGE_SID)

    assert response.status_code == 200
    assert response.json()["accepted_fields"]["preferred_phone"] == PREFERRED_PHONE
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@pytest.mark.language_gate
def test_arabic_session_uses_arabic_completion_message(mock_extract, mock_send_picker, client):
    from django.utils import timezone

    WhatsAppConversationSession.objects.create(
        whatsapp_number=WHATSAPP_NUMBER,
        language=LANGUAGE_ARABIC,
        language_selected_at=timezone.now(),
    )
    _seed_preferred_phone_step()

    response = _post(client, PREFERRED_PHONE, message_sid=PHONE_MESSAGE_SID)

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_language"] == LANGUAGE_ARABIC
    assert body["reply_text"] == get_customer_message(language=LANGUAGE_ARABIC, key="completion")
    assert body["qualification_status"] == "completed"
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@pytest.mark.parametrize("message", ["abc", "123", "+12"])
def test_invalid_preferred_phone_returns_localized_invalid_message(mock_extract, client, message):
    _seed_preferred_phone_step()

    response = _post(client, message, message_sid=PHONE_MESSAGE_SID)

    assert response.status_code == 200
    body = response.json()
    assert body["next_field"] == "preferred_phone"
    assert body["preferred_phone"] is None
    assert body["qualification_status"] == "in_progress"
    assert body["reply_text"] == get_customer_message(language=LANGUAGE_ENGLISH, key="invalid_phone")
    assert "preferred_phone" not in body["accepted_fields"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter", return_value=QualificationFieldFilterResult(
    accepted_fields={"referral_source": "Instagram"},
    rejected_fields=(),
    human_handoff_requested=False,
))
def test_phone_like_message_does_not_apply_when_not_on_preferred_phone_step(mock_extract, client):
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "project_type": "new_website",
            "requirements": "restaurant website",
        },
    )

    response = _post(client, PREFERRED_PHONE, message_sid=PHONE_MESSAGE_SID)

    assert response.status_code == 200
    assert response.json()["next_field"] == "whatsapp_confirmed"
    assert "preferred_phone" not in response.json()["accepted_fields"]
    mock_extract.assert_called_once()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_existing_preferred_phone_is_not_overwritten(mock_extract, client):
    existing_phone = "+923009999999"
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            **BASE_FIELDS,
            "preferred_phone": existing_phone,
        },
    )

    response = _post(client, PREFERRED_PHONE, message_sid=PHONE_MESSAGE_SID)

    assert response.status_code == 200
    body = response.json()
    assert body["qualification_status"] == "completed"
    assert body["accepted_fields"]["preferred_phone"] == existing_phone
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_duplicate_message_sid_for_preferred_phone_is_idempotent(mock_extract, client):
    _seed_preferred_phone_step()
    payload = {
        "message": PREFERRED_PHONE,
        "whatsapp_number": WHATSAPP_NUMBER,
        "input_channel": "whatsapp_text",
        "message_sid": PHONE_MESSAGE_SID,
        "media_url": None,
        "media_content_type": None,
    }

    first = client.post(
        ENDPOINT_PATH,
        data=json.dumps(payload),
        content_type="application/json",
        **internal_api_auth_headers(secret=API_SECRET),
    )
    second = client.post(
        ENDPOINT_PATH,
        data=json.dumps(payload),
        content_type="application/json",
        **internal_api_auth_headers(secret=API_SECRET),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    assert get_accepted_fields(WHATSAPP_NUMBER)["preferred_phone"] == PREFERRED_PHONE
    assert get_cached_turn_response(PHONE_MESSAGE_SID) is not None
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_no_to_whatsapp_then_valid_phone_completes_without_openrouter(mock_extract, client):
    mock_extract.side_effect = [
        QualificationFieldFilterResult(
            accepted_fields={
                "project_type": "new_website",
                "requirements": "I need a new website for my restaurant",
            },
            rejected_fields=(),
            human_handoff_requested=False,
        ),
        QualificationFieldFilterResult(
            accepted_fields={"referral_source": "Facebook"},
            rejected_fields=(),
            human_handoff_requested=False,
        ),
    ]

    _post(client, "I need a new website for my restaurant.", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce90")
    _post(client, "Facebook", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce92")
    _post(client, "No", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce93")
    mock_extract.reset_mock()

    response = _post(client, PREFERRED_PHONE, message_sid=PHONE_MESSAGE_SID)

    assert response.status_code == 200
    body = response.json()
    assert body["accepted_fields"]["whatsapp_confirmed"] is False
    assert body["accepted_fields"]["preferred_phone"] == PREFERRED_PHONE
    assert body["qualification_status"] == "completed"
    mock_extract.assert_not_called()
