"""Tests for the LiveKit voice-call completion internal API."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from django.test import Client, override_settings

pytestmark = pytest.mark.django_db

from apps.qualification.conversation_state import clear_conversations, get_accepted_fields
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.tests.internal_api_test_helpers import (
    ERROR_CONTRACT_400,
    ERROR_CONTRACT_403,
    ERROR_CONTRACT_502,
    ERROR_CONTRACT_503,
    assert_public_error_contract,
)
from apps.qualification.voice_event_auth import VOICE_EVENT_SECRET_HEADER_NAME

ENDPOINT_PATH = "/api/internal/qualification/voice-call-completed/"
VOICE_EVENT_SECRET = "test-weblead-voice-event-secret"
VOICE_EVENT_SECRET_META_KEY = "HTTP_" + VOICE_EVENT_SECRET_HEADER_NAME.upper().replace("-", "_")
VALID_WHATSAPP_NUMBER = "+923001234567"
BOOKING_LINK = "https://booking.example.com/test-schedule"

VALID_PAYLOAD = {
    "event": "voice_call.completed",
    "event_id": "evt-voice-001",
    "call_id": "call-voice-001",
    "customer_phone": VALID_WHATSAPP_NUMBER,
    "whatsapp_number": VALID_WHATSAPP_NUMBER,
    "project_type": "new_website",
    "requirements": "Restaurant website with online ordering",
    "referral_source": "Google",
    "whatsapp_confirmed": True,
    "preferred_phone": "+923246271156",
    "send_booking_link": True,
}


def voice_event_auth_headers(*, secret: str | None = VOICE_EVENT_SECRET) -> dict[str, str]:
    headers: dict[str, str] = {}
    if secret is not None:
        headers[VOICE_EVENT_SECRET_META_KEY] = secret
    return headers


def _post_voice_call_completed(
    client: Client,
    payload: object,
    *,
    secret: str | None = VOICE_EVENT_SECRET,
):
    headers: dict[str, str] = {
        "content_type": "application/json",
        **voice_event_auth_headers(secret=secret),
    }
    body = json.dumps(payload) if not isinstance(payload, (bytes, str)) else payload
    if isinstance(body, str):
        body = body.encode("utf-8")
    return client.post(ENDPOINT_PATH, data=body, **headers)


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


@override_settings(WEBLEAD_VOICE_EVENT_SECRET="")
def test_voice_call_completed_returns_503_when_secret_unconfigured(client):
    response = _post_voice_call_completed(client, VALID_PAYLOAD)
    assert_public_error_contract(response, status_code=503, body=ERROR_CONTRACT_503)


def test_voice_call_completed_rejects_invalid_secret(client):
    response = _post_voice_call_completed(client, VALID_PAYLOAD, secret="wrong-secret")
    assert_public_error_contract(response, status_code=403, body=ERROR_CONTRACT_403)


def test_voice_call_completed_rejects_invalid_whatsapp_number(client):
    payload = {**VALID_PAYLOAD, "whatsapp_number": "not-a-phone"}
    response = _post_voice_call_completed(client, payload)
    assert_public_error_contract(response, status_code=400, body=ERROR_CONTRACT_400)


def test_voice_call_completed_accepts_valid_event(
    mock_twilio_booking_link_send: MagicMock,
    client,
):
    response = _post_voice_call_completed(client, VALID_PAYLOAD)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["event_id"] == VALID_PAYLOAD["event_id"]
    assert body["call_id"] == VALID_PAYLOAD["call_id"]
    assert body["qualification_status"] == "completed"
    assert body["send_booking_link"] is True
    assert body["booking_link_sent"] is True
    assert body["booking_link"] == BOOKING_LINK
    assert body["accepted_fields"]["project_type"] == "new_website"
    assert body["accepted_fields"]["preferred_phone"] == "+923246271156"

    saved = get_accepted_fields(VALID_WHATSAPP_NUMBER)
    assert saved["project_type"] == "new_website"
    assert saved["requirements"] == VALID_PAYLOAD["requirements"]

    mock_twilio_booking_link_send.assert_called_once()
    sent_body = mock_twilio_booking_link_send.call_args.kwargs["body"]
    assert BOOKING_LINK in sent_body
    assert sent_body == (
        f"Please book a time here: {BOOKING_LINK}"
    )
    assert "Perfect, thank you" not in sent_body
    assert mock_twilio_booking_link_send.call_args.kwargs["input_channel"] == "voice_call_completed"
    assert body["spoken_text"] == (
        "Perfect, thank you. I'll send the booking link to your WhatsApp now."
    )
    assert BOOKING_LINK not in body["spoken_text"]
    assert body["whatsapp_text"] == sent_body
    assert body["actions"] == []


def test_voice_call_completed_duplicate_event_id_is_idempotent(
    mock_twilio_booking_link_send: MagicMock,
    client,
):
    first = _post_voice_call_completed(client, VALID_PAYLOAD)
    second = _post_voice_call_completed(
        client,
        {**VALID_PAYLOAD, "call_id": "call-voice-duplicate-replay"},
    )

    assert first.status_code == 200
    assert first.json()["status"] == "accepted"
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["event_id"] == VALID_PAYLOAD["event_id"]
    assert second.json()["call_id"] == VALID_PAYLOAD["call_id"]
    assert second.json()["booking_link_sent"] is True
    mock_twilio_booking_link_send.assert_called_once()


def test_voice_call_completed_send_booking_link_false_does_not_send(
    mock_twilio_booking_link_send: MagicMock,
    client,
):
    payload = {**VALID_PAYLOAD, "send_booking_link": False}

    response = _post_voice_call_completed(client, payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["send_booking_link"] is False
    assert body["booking_link_sent"] is False
    assert body["booking_link"] is None
    mock_twilio_booking_link_send.assert_not_called()

    saved = get_accepted_fields(VALID_WHATSAPP_NUMBER)
    assert saved["project_type"] == "new_website"


def test_voice_call_completed_booking_link_sent_exactly_once(
    mock_twilio_booking_link_send: MagicMock,
    client,
):
    for _ in range(3):
        response = _post_voice_call_completed(client, VALID_PAYLOAD)
        assert response.status_code == 200

    mock_twilio_booking_link_send.assert_called_once()
