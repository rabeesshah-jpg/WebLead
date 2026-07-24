"""Integration tests for main-menu language action parity with /language."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from apps.qualification.conversation_state import clear_conversations, save_accepted_fields
from apps.qualification.message_idempotency import clear_message_sid_cache, get_cached_turn_response
from apps.qualification.models import WhatsAppConversationSession
from apps.qualification.tests.internal_api_test_helpers import (
    API_SECRET,
    internal_api_auth_headers,
)

pytestmark = [pytest.mark.django_db, pytest.mark.whatsapp_menu]

ENDPOINT_PATH = "/api/internal/qualification/extract/"
VALID_WHATSAPP_NUMBER = "+923001234567"
MENU_CONTENT_SID = "HXtestmainmenucontentsid00000000"
LANGUAGE_MESSAGE_SID = "SM0cc5a1d9e22bf9850ca24261ee23ceb1"
MENU_LANGUAGE_BODY_SID = "SM0cc5a1d9e22bf9850ca24261ee23ceb2"
MENU_LANGUAGE_BODY_ONLY_SID = "SM0cc5a1d9e22bf9850ca24261ee23ceb4"
MENU_LANGUAGE_DUPLICATE_SID = "SM0cc5a1d9e22bf9850ca24261ee23ceb5"

MENU_LANGUAGE_PAYLOAD_SID = "SM0cc5a1d9e22bf9850ca24261ee23ceb3"

SETTINGS = {
    
    
    "TWILIO_WHATSAPP_MENU_CONTENT_SID": MENU_CONTENT_SID,
    "LEAD_QUALIFICATION_ENABLED": True,
    "N8N_QUALIFICATION_API_SECRET": API_SECRET}

IN_PROGRESS_FIELDS = {
    "project_type": "new_website",
    "requirements": "A restaurant website with online ordering",
    "referral_source": "Google",
    "whatsapp_confirmed": True,
    "preferred_phone": VALID_WHATSAPP_NUMBER}


def _post_extract(client: Client, payload: dict) -> object:
    return client.post(
        ENDPOINT_PATH,
        data=json.dumps(payload),
        content_type="application/json",
        **internal_api_auth_headers(secret=API_SECRET),
    )


def _seed_session() -> WhatsAppConversationSession:
    return WhatsAppConversationSession.objects.create(
        whatsapp_number=VALID_WHATSAPP_NUMBER,
        language="en",
        language_selected_at=timezone.now(),
    )


@pytest.fixture(autouse=True)
def _reset_state():
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()
    yield
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()


@override_settings(**SETTINGS)
@patch("apps.qualification.services.whatsapp_menu_service.send_language_picker")
@patch("apps.qualification.services.language_gate_service.send_language_picker")
def test_language_command_and_menu_language_action_match(
    mock_gate_send_picker: MagicMock,
    mock_menu_send_picker: MagicMock,
):
    mock_gate_send_picker.return_value = "SMlanguagepickersent000000000000"
    mock_menu_send_picker.return_value = "SMlanguagepickersent000000000000"
    client = Client()
    _seed_session()
    save_accepted_fields(VALID_WHATSAPP_NUMBER, IN_PROGRESS_FIELDS)

    slash_response = _post_extract(
        client,
        {
            "message": "/language",
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_text",
            "message_sid": LANGUAGE_MESSAGE_SID,
            "media_url": None,
            "media_content_type": None},
    )
    slash_body = slash_response.json()

    menu_response = _post_extract(
        client,
        {
            "message": "Change language\nEnglish / Arabic",
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_text",
            "message_sid": MENU_LANGUAGE_BODY_SID,
            "media_url": None,
            "media_content_type": None},
    )
    menu_body = menu_response.json()

    payload_response = _post_extract(
        client,
        {
            "message": "Change language",
            "button_payload": "language",
            "button_text": "Change language\nEnglish / Arabic",
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_text",
            "message_sid": MENU_LANGUAGE_PAYLOAD_SID,
            "media_url": None,
            "media_content_type": None},
    )
    payload_body = payload_response.json()

    assert slash_response.status_code == 200
    assert menu_response.status_code == 200
    assert payload_response.status_code == 200
    assert slash_body["status"] == "awaiting_language_selection"
    assert menu_body["status"] == "awaiting_language_selection"
    assert payload_body["status"] == "awaiting_language_selection"
    assert slash_body["language_command_action"] == "picker_sent"
    assert menu_body["language_command_action"] == "picker_sent"
    assert payload_body["language_command_action"] == "picker_sent"
    assert mock_gate_send_picker.call_count == 1
    assert mock_menu_send_picker.call_count == 2


@override_settings(**SETTINGS)
@patch("apps.qualification.services.whatsapp_menu_service.send_language_picker")
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
def test_body_only_language_token_triggers_language_flow(
    mock_send_menu: MagicMock,
    mock_send_picker: MagicMock,
):
    mock_send_menu.return_value = "SMmainmenusent0000000000000000"
    mock_send_picker.return_value = "SMlanguagepickersent000000000000"
    client = Client()
    _seed_session()
    save_accepted_fields(VALID_WHATSAPP_NUMBER, IN_PROGRESS_FIELDS)

    _post_extract(
        client,
        {
            "message": "M",
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_text",
            "message_sid": "SM0menu000000000000000000000001",
            "media_url": None,
            "media_content_type": None},
    )

    response = _post_extract(
        client,
        {
            "message": "language",
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_text",
            "message_sid": MENU_LANGUAGE_BODY_ONLY_SID,
            "media_url": None,
            "media_content_type": None},
    )
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "awaiting_language_selection"
    assert body["language_command_action"] == "picker_sent"
    mock_send_picker.assert_called_once()
    session = WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER)
    assert session.language_picker_pending_until is not None
    assert session.menu_pending is False


@override_settings(**SETTINGS)
@patch("apps.qualification.services.whatsapp_menu_service.send_language_picker")
def test_unrelated_body_does_not_trigger_language_flow(mock_send_picker: MagicMock):
    mock_send_picker.return_value = "SMlanguagepickersent000000000000"
    client = Client()
    _seed_session()

    response = _post_extract(
        client,
        {
            "message": "I need a new website for my bakery",
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_text",
            "message_sid": "SM0cc5a1d9e22bf9850ca24261ee23ceb6",
            "media_url": None,
            "media_content_type": None},
    )
    body = response.json()

    assert response.status_code == 200
    assert body.get("status") != "awaiting_language_selection"
    mock_send_picker.assert_not_called()


@override_settings(**SETTINGS)
@patch("apps.qualification.services.whatsapp_menu_service.send_language_picker")
@patch("apps.qualification.services.language_gate_service.send_language_picker")
def test_duplicate_message_sid_for_menu_language_does_not_resend_picker(
    mock_gate_send_picker: MagicMock,
    mock_menu_send_picker: MagicMock,
):
    mock_gate_send_picker.return_value = "SMlanguagepickersent000000000000"
    mock_menu_send_picker.return_value = "SMlanguagepickersent000000000000"
    client = Client()
    _seed_session()
    save_accepted_fields(VALID_WHATSAPP_NUMBER, IN_PROGRESS_FIELDS)

    payload = {
        "message": "language",
        "whatsapp_number": VALID_WHATSAPP_NUMBER,
        "input_channel": "whatsapp_text",
        "message_sid": MENU_LANGUAGE_DUPLICATE_SID,
        "media_url": None,
        "media_content_type": None}

    first = _post_extract(client, payload)
    second = _post_extract(client, payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    mock_menu_send_picker.assert_called_once()
    assert get_cached_turn_response(MENU_LANGUAGE_DUPLICATE_SID) is not None
