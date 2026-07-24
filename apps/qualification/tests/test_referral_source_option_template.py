"""Tests for referral_source Twilio list picker option_template and capture."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from apps.qualification.channels import finalize_turn_response
from apps.qualification.conversation_flow import try_handle_qualification_step_turn
from apps.qualification.conversation_state import clear_conversations, save_accepted_fields
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.models import WhatsAppConversationSession
from apps.qualification.tests.internal_api_test_helpers import API_SECRET, internal_api_auth_headers

pytestmark = pytest.mark.django_db

ENDPOINT_PATH = "/api/internal/qualification/extract/"
WHATSAPP_NUMBER = "+923001237777"
BOOKING_LINK = "https://booking.example.com/test-schedule"
REFERRAL_FALLBACK = get_customer_message(language="en", key="referral_source")
REFERRAL_VOICE = get_customer_message(language="en", key="referral_source_voice")


def _seed_new_customer(number: str = WHATSAPP_NUMBER) -> None:
    save_accepted_fields(number, {"customer_type": "new_customer"})


def _seed_existing_customer(number: str = WHATSAPP_NUMBER) -> None:
    now = timezone.now()
    WhatsAppConversationSession.objects.get_or_create(
        whatsapp_number=number,
        defaults={
            "language": "en",
            "language_selected_at": now,
            "booking_link_sent_at": now,
            "qualified_at": now},
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
def test_new_customer_asks_referral_with_option_template(mock_extract, client):
    body = _post(client, message="new customer")

    assert body["accepted_fields"]["customer_type"] == "new_customer"
    assert body["next_field"] == "referral_source"
    assert body.get("conversation_state") == "WAITING_FOR_REFERRAL_SOURCE"
    assert body["option_template"] == "referral_source"
    assert REFERRAL_FALLBACK in body["reply_text"]
    assert "1. Google" in body["reply_text"]
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
def test_existing_customer_detection_starts_connecting_without_referral(
    mock_send, mock_sleep, mock_extract, client
):
    """Qualified/existing numbers get sync connecting + Noura (not referral)."""
    number = WHATSAPP_NUMBER
    now = timezone.now()
    WhatsAppConversationSession.objects.create(
        whatsapp_number=number,
        language="en",
        language_selected_at=now,
        qualified_at=now,
        booking_link_sent_at=now,
    )

    body = _post(client, message="hello")

    assert body["accepted_fields"]["customer_type"] == "existing_customer"
    assert body["next_field"] == "business_type"
    assert "referral_source" not in body["accepted_fields"]
    assert body.get("option_template") == "business_type"
    assert body["reply_text"] == ""
    assert body["conversation_state"] == "WAITING_FOR_BUSINESS_TYPE"
    assert body["should_send_qualification_question"] is True
    mock_sleep.assert_called_once_with(5)
    assert mock_send.call_count == 2
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@pytest.mark.parametrize(
    ("button_payload", "expected"),
    [
        ("google", "google"),
        ("instagram", "instagram"),
        ("facebook", "facebook"),
        ("friend_referral", "friend_referral"),
        ("other", "other"),
    ],
)
def test_referral_button_payload_captures_and_moves_to_business_type(
    mock_extract, client, button_payload, expected
):
    _seed_new_customer()

    body = _post(client, message="ignored label", button_payload=button_payload)

    assert body["accepted_fields"]["referral_source"] == expected
    assert body["next_field"] == "business_type"
    assert body.get("option_template") is None
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("1", "google"),
        ("2", "instagram"),
        ("3", "facebook"),
        ("4", "friend_referral"),
        ("5", "other"),
        ("google", "google"),
        ("insta", "instagram"),
        ("fb", "facebook"),
        ("friend", "friend_referral"),
    ],
)
def test_referral_numeric_and_text_fallback(mock_extract, client, message, expected):
    _seed_new_customer()

    body = _post(client, message=message)

    assert body["accepted_fields"]["referral_source"] == expected
    assert body["next_field"] == "business_type"
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
def test_voice_referral_uses_spoken_text_without_option_template():
    number = "+923001237778"
    clear_conversations()
    _seed_new_customer(number)

    turn = try_handle_qualification_step_turn(
        whatsapp_number=number,
        message="",
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

    assert body["next_field"] == "referral_source"
    assert body.get("option_template") is None
    assert body["spoken_text"] == REFERRAL_VOICE
    assert body["should_send_audio"] is True
    assert body["should_send_text"] is False


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("جوجل", "google"),
        ("إنستغرام", "instagram"),
        ("فيسبوك", "facebook"),
        ("صديق", "friend_referral"),
        ("إحالة", "friend_referral"),
        ("أخرى", "other"),
    ],
)
def test_arabic_referral_label_captures_and_moves_to_business_type(message, expected):
    number = "+923001237779"
    clear_conversations()
    _seed_new_customer(number)

    response = try_handle_qualification_step_turn(
        whatsapp_number=number,
        message=message,
        language="ar",
    )

    assert response is not None
    assert response["accepted_fields"]["referral_source"] == expected
    assert response["next_field"] == "business_type"
    assert response["conversation_language"] == "ar"


@pytest.mark.parametrize(
    ("message", "expected_customer_type", "expected_next_field"),
    [
        ("عميل جديد", "new_customer", "referral_source"),
        ("جديد", "new_customer", "referral_source"),
        ("عميل حالي", "existing_customer", "business_type"),
        ("عميل موجود", "existing_customer", "business_type"),
    ],
)
def test_arabic_customer_type_capture_routes_correctly(
    message, expected_customer_type, expected_next_field
):
    number = "+923001237780"
    clear_conversations()

    response = try_handle_qualification_step_turn(
        whatsapp_number=number,
        message=message,
        language="ar",
    )

    assert response is not None
    assert response["accepted_fields"]["customer_type"] == expected_customer_type
    assert response["next_field"] == expected_next_field
    assert response["conversation_language"] == "ar"
