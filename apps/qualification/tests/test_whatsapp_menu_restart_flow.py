"""Tests for WhatsApp menu and restart conversation flow."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from apps.qualification.conversation_state import (
    clear_conversations,
    get_accepted_fields,
    save_accepted_fields,
)
from apps.qualification.domain.language_selection import LANGUAGE_ARABIC, LANGUAGE_ENGLISH
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.models import QualificationFieldFilterResult, WhatsAppConversationSession
from apps.qualification.tests.internal_api_test_helpers import (
    API_SECRET,
    MOCK_VOICE_AUDIO_DOWNLOAD,
    internal_api_auth_headers,
)

pytestmark = [pytest.mark.django_db, pytest.mark.whatsapp_menu]

ENDPOINT_PATH = "/api/internal/qualification/extract/"
VALID_WHATSAPP_NUMBER = "+923001234567"
MEDIA_URL = "https://waha.example.com/api/files/true_923246271149@c.us_VOICE001.ogg"
MENU_MESSAGE_SID = "SM0cc5a1d9e22bf9850ca24261ee23ce90"
RESTART_MESSAGE_SID = "SM0cc5a1d9e22bf9850ca24261ee23ce91"
VOICE_RESTART_MESSAGE_SID = "SM0cc5a1d9e22bf9850ca24261ee23ce93"
NORMAL_QUAL_MESSAGE_SID = "SM0cc5a1d9e22bf9850ca24261ee23ce94"

MENU_SETTINGS = {
    
    
    
    "LEAD_QUALIFICATION_ENABLED": True,
    "SESSION_IDLE_RESET_SECONDS": 7200,
    "N8N_QUALIFICATION_API_SECRET": API_SECRET}

IN_PROGRESS_FIELDS = {
    "customer_type": "new_customer",
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


def _text_payload(
    *,
    message: str,
    message_sid: str,
    button_payload: str | None = None,
) -> dict:
    payload = {
        "message": message,
        "whatsapp_number": VALID_WHATSAPP_NUMBER,
        "input_channel": "whatsapp_text",
        "message_sid": message_sid,
        "media_url": None,
        "media_content_type": None}
    if button_payload is not None:
        payload["button_payload"] = button_payload
    return payload


def _voice_payload(*, message_sid: str) -> dict:
    return {
        "whatsapp_number": VALID_WHATSAPP_NUMBER,
        "input_channel": "whatsapp_voice_note",
        "message_sid": message_sid,
        "media_url": MEDIA_URL,
        "media_content_type": "audio/ogg"}


def _seed_session(*, language: str = LANGUAGE_ENGLISH) -> WhatsAppConversationSession:
    return WhatsAppConversationSession.objects.create(
        whatsapp_number=VALID_WHATSAPP_NUMBER,
        language=language,
        language_selected_at=timezone.now(),
    )


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


@override_settings(**MENU_SETTINGS)
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
def test_menu_command_sends_interactive_menu(mock_send_menu: MagicMock, client):
    mock_send_menu.return_value = "SMmainmenusent0000000000000000"
    _seed_session()
    save_accepted_fields(VALID_WHATSAPP_NUMBER, IN_PROGRESS_FIELDS)

    response = _post_extract(client, _text_payload(message="M", message_sid=MENU_MESSAGE_SID))
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "awaiting_menu_selection"
    assert "reply_text" not in body
    mock_send_menu.assert_called_once()
    session = WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER)
    assert session.last_menu_sent is True


@override_settings(**MENU_SETTINGS)
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
@pytest.mark.parametrize("message", ["M", " M ", "\nM\n"])
def test_exact_uppercase_m_opens_menu(mock_send_menu: MagicMock, client, message: str):
    mock_send_menu.return_value = "SMmainmenusent0000000000000001"
    _seed_session()
    save_accepted_fields(VALID_WHATSAPP_NUMBER, IN_PROGRESS_FIELDS)

    response = _post_extract(
        client,
        _text_payload(message=message, message_sid=MENU_MESSAGE_SID),
    )
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "awaiting_menu_selection"
    assert get_accepted_fields(VALID_WHATSAPP_NUMBER) == IN_PROGRESS_FIELDS
    mock_send_menu.assert_called_once()


@override_settings(**MENU_SETTINGS)
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@pytest.mark.parametrize(
    "message",
    ["m", "menu", "/menu", "i need your menu", "M please", "I want M"],
)
def test_non_exact_uppercase_m_does_not_open_menu(
    mock_extract: MagicMock,
    mock_send_menu: MagicMock,
    client,
    message: str,
):
    mock_extract.return_value = QualificationFieldFilterResult(
        accepted_fields={},
        rejected_fields=(),
        human_handoff_requested=False,
    )
    _seed_session()
    save_accepted_fields(
        VALID_WHATSAPP_NUMBER,
        {
            "project_type": "new_website",
            "requirements": "website",
            "referral_source": "Google"},
    )

    response = _post_extract(
        client,
        _text_payload(
            message=message,
            message_sid=NORMAL_QUAL_MESSAGE_SID,
        ),
    )

    assert response.status_code == 200
    mock_send_menu.assert_not_called()
    body = response.json()
    assert body.get("status") != "awaiting_menu_selection"
    assert "reply_text" in body


@override_settings(**MENU_SETTINGS)
def test_restart_command_clears_state(client):
    _seed_session(language=LANGUAGE_ARABIC)
    save_accepted_fields(VALID_WHATSAPP_NUMBER, IN_PROGRESS_FIELDS)

    response = _post_extract(client, _text_payload(message="/restart", message_sid=RESTART_MESSAGE_SID))
    body = response.json()

    assert response.status_code == 200
    assert get_accepted_fields(VALID_WHATSAPP_NUMBER) == {}
    assert body["status"] == "awaiting_language_selection"
    assert body["message"] == "Language selector sent."
    session = WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER)
    assert session.language is None


@override_settings(**MENU_SETTINGS)
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
def test_list_picker_restart_clears_state(mock_send_menu: MagicMock, client):
    mock_send_menu.return_value = "SMmainmenusent0000000000000000"
    _seed_session()
    save_accepted_fields(VALID_WHATSAPP_NUMBER, IN_PROGRESS_FIELDS)

    _post_extract(client, _text_payload(message="M", message_sid="SM0cc5a1d9e22bf9850ca24261ee23cea0"))
    response = _post_extract(
        client,
        _text_payload(
            message="Restart qualification",
            message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce92",
            button_payload="restart",
        ),
    )
    body = response.json()

    assert response.status_code == 200
    assert get_accepted_fields(VALID_WHATSAPP_NUMBER) == {}
    assert body["status"] == "awaiting_language_selection"
    assert WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER).language is None


@override_settings(**MENU_SETTINGS)
def test_language_is_cleared_after_restart(client):
    _seed_session(language=LANGUAGE_ARABIC)
    save_accepted_fields(VALID_WHATSAPP_NUMBER, IN_PROGRESS_FIELDS)

    response = _post_extract(client, _text_payload(message="restart", message_sid="SM0cc5a1d9e22bf9850ca24261ee23cea1"))
    body = response.json()

    assert body["status"] == "awaiting_language_selection"
    assert WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER).language is None


@override_settings(**MENU_SETTINGS)
@patch("apps.qualification.services.whatsapp_menu_service.send_language_picker")
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
def test_list_picker_language_triggers_picker(
    mock_send_menu: MagicMock,
    mock_send_picker: MagicMock,
    client,
):
    mock_send_menu.return_value = "SMmainmenusent0000000000000000"
    mock_send_picker.return_value = "SMlanguagepickersent000000000000"
    _seed_session()
    save_accepted_fields(VALID_WHATSAPP_NUMBER, IN_PROGRESS_FIELDS)

    _post_extract(client, _text_payload(message="M", message_sid="SM0cc5a1d9e22bf9850ca24261ee23cea2"))
    response = _post_extract(
        client,
        _text_payload(
            message="Change language",
            message_sid="SM0cc5a1d9e22bf9850ca24261ee23cea3",
            button_payload="language",
        ),
    )
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "awaiting_language_selection"
    mock_send_picker.assert_called_once()
    session = WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER)
    assert session.language_picker_pending_until is not None
    assert session.menu_pending is False
    assert session.menu_pending_until is None


@override_settings(**MENU_SETTINGS)
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
def test_list_picker_human_triggers_handoff(mock_send_menu: MagicMock, client):
    mock_send_menu.return_value = "SMmainmenusent0000000000000000"
    _seed_session()
    save_accepted_fields(VALID_WHATSAPP_NUMBER, IN_PROGRESS_FIELDS)

    _post_extract(client, _text_payload(message="M", message_sid="SM0cc5a1d9e22bf9850ca24261ee23cea4"))
    response = _post_extract(
        client,
        _text_payload(
            message="Talk to human",
            message_sid="SM0cc5a1d9e22bf9850ca24261ee23cea5",
            button_payload="human",
        ),
    )
    body = response.json()

    assert response.status_code == 200
    assert body["human_handoff_requested"] is True
    assert body["qualification_status"] == "human_handoff"
    assert body["reply_text"] == get_customer_message(language=LANGUAGE_ENGLISH, key="human_handoff")
    assert body["accepted_fields"] == IN_PROGRESS_FIELDS


@override_settings(**MENU_SETTINGS)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.core.legacy_compat.transcribe_audio", return_value="restart")
def test_voice_note_transcript_restart_triggers_restart(
    mock_transcribe: MagicMock,
    mock_download: MagicMock,
    client,
):
    _seed_session()
    save_accepted_fields(VALID_WHATSAPP_NUMBER, IN_PROGRESS_FIELDS)

    response = _post_extract(client, _voice_payload(message_sid=VOICE_RESTART_MESSAGE_SID))
    body = response.json()

    assert response.status_code == 200
    assert body["transcript"] == "restart"
    assert get_accepted_fields(VALID_WHATSAPP_NUMBER) == {}
    assert body["status"] == "awaiting_language_selection"
    assert WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER).language is None


@override_settings(**MENU_SETTINGS)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_existing_normal_qualification_still_works(mock_extract, client):
    _seed_session()
    save_accepted_fields(
        VALID_WHATSAPP_NUMBER,
        {"customer_type": "new_customer", "referral_source": "google"},
    )
    mock_extract.return_value = QualificationFieldFilterResult(
        accepted_fields={"project_type": "new_website"},
        rejected_fields=(),
        human_handoff_requested=False,
    )

    response = _post_extract(
        client,
        _text_payload(
            message="I need a new website for my bakery",
            message_sid=NORMAL_QUAL_MESSAGE_SID,
        ),
    )
    body = response.json()

    assert response.status_code == 200
    assert body.get("status") != "awaiting_language_selection"
    assert body["accepted_fields"]["customer_type"] == "new_customer"
    assert body["accepted_fields"]["project_type"] == "new_website"
    assert body["next_field"] == "requirements"
    assert body["qualification_status"] == "in_progress"
    mock_extract.assert_not_called()
