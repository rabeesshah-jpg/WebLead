"""Tests for explicit qualification restart (not idle-based)."""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from apps.qualification.conversation_state import (
    clear_conversations,
    get_accepted_fields,
    save_accepted_fields,
)
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.models import WhatsAppConversationSession
from apps.qualification.tests.internal_api_test_helpers import API_SECRET, internal_api_auth_headers

pytestmark = pytest.mark.django_db

ENDPOINT_PATH = "/api/internal/qualification/extract/"
WHATSAPP_NUMBER = "+923001234567"
BOOKING_LINK = "https://booking.example.com/test-schedule"
MENU_SETTINGS = {
    "TWILIO_LANGUAGE_PICKER_CONTENT_SID": "HXtestcontentsidfortest0000000000",
    "TWILIO_WHATSAPP_FROM_NUMBER": "whatsapp:+15557654321",
    "TWILIO_WHATSAPP_MENU_CONTENT_SID": "HXtestmainmenucontentsid00000000",
    "LEAD_QUALIFICATION_ENABLED": True,
}


def _post_text(client: Client, message: str, *, message_sid: str) -> object:
    return client.post(
        ENDPOINT_PATH,
        data=json.dumps(
            {
                "whatsapp_number": WHATSAPP_NUMBER,
                "input_channel": "whatsapp_text",
                "message": message,
                "message_sid": message_sid,
            }
        ),
        content_type="application/json",
        **internal_api_auth_headers(),
    )


@pytest.fixture
def client() -> Client:
    clear_conversations()
    clear_message_sid_cache()
    return Client()


@pytest.fixture(autouse=True)
def _english_session():
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()
    WhatsAppConversationSession.objects.create(
        whatsapp_number=WHATSAPP_NUMBER,
        language="en",
        language_selected_at=timezone.now(),
        onboarding_intro_sent=True,
        last_message_at=timezone.now() - timedelta(hours=2),
    )
    yield
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK, **MENU_SETTINGS)
@pytest.mark.whatsapp_menu
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_explicit_restart_clears_qualification_state(mock_extract, client):
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {"project_type": "new_website", "requirements": "restaurant"},
    )

    response = _post_text(client, "start over", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce90")
    body = response.json()

    assert response.status_code == 200
    assert get_accepted_fields(WHATSAPP_NUMBER) == {}
    assert body["next_field"] == "project_type"
    assert body["reply_text"] == get_customer_message(language="en", key="restart_intro")
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK, **MENU_SETTINGS)
@pytest.mark.whatsapp_menu
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@pytest.mark.parametrize(
    "restart_message,message_sid",
    [
        ("restart", "SM0cc5a1d9e22bf9850ca24261ee23cea0"),
        ("reset", "SM0cc5a1d9e22bf9850ca24261ee23cea1"),
        ("begin again", "SM0cc5a1d9e22bf9850ca24261ee23cea2"),
        ("new inquiry", "SM0cc5a1d9e22bf9850ca24261ee23cea3"),
    ],
)
def test_explicit_restart_phrases_clear_state(mock_extract, client, restart_message, message_sid):
    save_accepted_fields(WHATSAPP_NUMBER, {"project_type": "new_website"})

    response = _post_text(client, restart_message, message_sid=message_sid)

    assert response.status_code == 200
    assert get_accepted_fields(WHATSAPP_NUMBER) == {}
    mock_extract.assert_not_called()
