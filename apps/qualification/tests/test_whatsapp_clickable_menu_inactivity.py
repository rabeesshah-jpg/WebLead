"""Tests for WhatsApp clickable menu and inactivity-triggered menu display."""

from __future__ import annotations

import json
from datetime import timedelta
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
MEDIA_URL = "https://api.twilio.com/2010-04-01/Accounts/ACtest/Media/MEtestvoice001"
MENU_CONTENT_SID = "HXtestmenucontentsid000000000000"

MENU_SETTINGS = {
    "TWILIO_LANGUAGE_PICKER_CONTENT_SID": "HXtestcontentsidfortest0000000000",
    "TWILIO_WHATSAPP_FROM_NUMBER": "whatsapp:+15557654321",
    "TWILIO_WHATSAPP_MENU_CONTENT_SID": MENU_CONTENT_SID,
    "LEAD_QUALIFICATION_ENABLED": True,
    "WHATSAPP_MENU_INACTIVITY_SECONDS": 600,
    "WHATSAPP_MENU_PENDING_SECONDS": 600,
    "N8N_QUALIFICATION_API_SECRET": API_SECRET,
}

IN_PROGRESS_FIELDS = {
    "project_type": "new_website",
    "requirements": "A restaurant website with online ordering",
    "referral_source": "Google",
    "whatsapp_confirmed": True,
    "preferred_phone": VALID_WHATSAPP_NUMBER,
}

PARTIAL_FIELDS = {
    "project_type": "new_website",
    "requirements": "A restaurant website with online ordering",
}


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
        "media_content_type": None,
    }
    if button_payload is not None:
        payload["button_payload"] = button_payload
    return payload


def _voice_payload(*, message_sid: str) -> dict:
    return {
        "whatsapp_number": VALID_WHATSAPP_NUMBER,
        "input_channel": "whatsapp_voice_note",
        "message_sid": message_sid,
        "media_url": MEDIA_URL,
        "media_content_type": "audio/ogg",
    }


def _seed_session(
    *,
    language: str = LANGUAGE_ENGLISH,
    last_message_at=None,
) -> WhatsAppConversationSession:
    return WhatsAppConversationSession.objects.create(
        whatsapp_number=VALID_WHATSAPP_NUMBER,
        language=language,
        language_selected_at=timezone.now(),
        last_message_at=last_message_at,
    )


def _inactive_last_message_at():
    return timezone.now() - timedelta(seconds=601)


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
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_active_user_within_inactivity_window_continues_normal_flow(mock_extract, client):
    _seed_session(last_message_at=timezone.now())
    save_accepted_fields(VALID_WHATSAPP_NUMBER, PARTIAL_FIELDS)
    mock_extract.return_value = QualificationFieldFilterResult(
        accepted_fields={"requirements": "Need online ordering"},
        rejected_fields=(),
        human_handoff_requested=False,
    )

    response = _post_extract(
        client,
        _text_payload(
            message="We also need a reservation form",
            message_sid="SM0cc5a1d9e22bf9850ca24261ee23cea6",
        ),
    )
    body = response.json()

    assert response.status_code == 200
    assert body.get("status") != "awaiting_menu_selection"
    mock_extract.assert_called_once()


@override_settings(**MENU_SETTINGS)
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
def test_inactive_user_after_threshold_gets_interactive_menu(mock_send_menu: MagicMock, client):
    mock_send_menu.return_value = "SMclickablemenusent000000000000"
    _seed_session(last_message_at=_inactive_last_message_at())
    save_accepted_fields(VALID_WHATSAPP_NUMBER, IN_PROGRESS_FIELDS)

    response = _post_extract(
        client,
        _text_payload(
            message="Hello again",
            message_sid="SM0cc5a1d9e22bf9850ca24261ee23cea7",
        ),
    )
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "awaiting_menu_selection"
    assert "reply_text" not in body
    mock_send_menu.assert_called_once()
    session = WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER)
    assert session.last_menu_sent is True


@override_settings(**MENU_SETTINGS)
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
def test_menu_button_payload_menu_restart_clears_state(mock_send_menu: MagicMock, client):
    mock_send_menu.return_value = "SMclickablemenusent000000000000"
    _seed_session()
    save_accepted_fields(VALID_WHATSAPP_NUMBER, IN_PROGRESS_FIELDS)

    _post_extract(client, _text_payload(message="menu", message_sid="SM0cc5a1d9e22bf9850ca24261ee23cea8"))
    response = _post_extract(
        client,
        _text_payload(
            message="Restart qualification",
            message_sid="SM0cc5a1d9e22bf9850ca24261ee23cea9",
            button_payload="menu_restart",
        ),
    )
    body = response.json()

    assert response.status_code == 200
    assert get_accepted_fields(VALID_WHATSAPP_NUMBER) == {}
    assert body["next_field"] == "project_type"
    assert body["reply_text"] == get_customer_message(language=LANGUAGE_ENGLISH, key="restart_intro")


@override_settings(**MENU_SETTINGS)
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
def test_menu_button_payload_menu_continue_resumes(mock_send_menu: MagicMock, client):
    mock_send_menu.return_value = "SMclickablemenusent000000000000"
    _seed_session()
    save_accepted_fields(VALID_WHATSAPP_NUMBER, PARTIAL_FIELDS)

    _post_extract(client, _text_payload(message="/menu", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ceaa"))
    response = _post_extract(
        client,
        _text_payload(
            message="Continue current conversation",
            message_sid="SM0cc5a1d9e22bf9850ca24261ee23ceab",
            button_payload="menu_continue",
        ),
    )
    body = response.json()

    assert response.status_code == 200
    assert body["accepted_fields"] == PARTIAL_FIELDS
    assert body["qualification_status"] == "in_progress"
    assert body["next_field"] == "referral_source"


@override_settings(**MENU_SETTINGS)
@patch("apps.qualification.services.whatsapp_menu_service.send_language_picker")
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
def test_menu_button_payload_menu_language_triggers_picker(
    mock_send_menu: MagicMock,
    mock_send_picker: MagicMock,
    client,
):
    mock_send_menu.return_value = "SMclickablemenusent000000000000"
    mock_send_picker.return_value = "SMlanguagepickersent000000000000"
    _seed_session()
    save_accepted_fields(VALID_WHATSAPP_NUMBER, IN_PROGRESS_FIELDS)

    _post_extract(client, _text_payload(message="menu", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ceac"))
    response = _post_extract(
        client,
        _text_payload(
            message="Change language",
            message_sid="SM0cc5a1d9e22bf9850ca24261ee23cead",
            button_payload="menu_language",
        ),
    )
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "awaiting_language_selection"
    mock_send_picker.assert_called_once()


@override_settings(**MENU_SETTINGS)
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
def test_menu_button_payload_menu_human_requests_handoff(mock_send_menu: MagicMock, client):
    mock_send_menu.return_value = "SMclickablemenusent000000000000"
    _seed_session()
    save_accepted_fields(VALID_WHATSAPP_NUMBER, IN_PROGRESS_FIELDS)

    _post_extract(client, _text_payload(message="menu", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ceae"))
    response = _post_extract(
        client,
        _text_payload(
            message="Talk to human",
            message_sid="SM0cc5a1d9e22bf9850ca24261ee23ceaf",
            button_payload="menu_human",
        ),
    )
    body = response.json()

    assert response.status_code == 200
    assert body["human_handoff_requested"] is True
    assert body["qualification_status"] == "human_handoff"
    assert body["accepted_fields"] == IN_PROGRESS_FIELDS


@override_settings(**MENU_SETTINGS)
def test_direct_restart_restarts_immediately(client):
    _seed_session()
    save_accepted_fields(VALID_WHATSAPP_NUMBER, IN_PROGRESS_FIELDS)

    response = _post_extract(
        client,
        _text_payload(message="/restart", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ceb2"),
    )
    body = response.json()

    assert response.status_code == 200
    assert get_accepted_fields(VALID_WHATSAPP_NUMBER) == {}
    assert body["next_field"] == "project_type"


@override_settings(**MENU_SETTINGS)
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.core.legacy_compat.transcribe_audio", return_value="I am back now")
def test_voice_transcript_after_inactivity_triggers_menu(
    mock_transcribe: MagicMock,
    mock_download: MagicMock,
    mock_send_menu: MagicMock,
    client,
):
    mock_send_menu.return_value = "SMclickablemenusent000000000000"
    _seed_session(last_message_at=_inactive_last_message_at())
    save_accepted_fields(VALID_WHATSAPP_NUMBER, IN_PROGRESS_FIELDS)

    response = _post_extract(client, _voice_payload(message_sid="SM0cc5a1d9e22bf9850ca24261ee23ceb3"))
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "awaiting_menu_selection"
    mock_send_menu.assert_called_once()


@override_settings(**MENU_SETTINGS)
def test_language_is_preserved_after_restart(client):
    _seed_session(language=LANGUAGE_ARABIC)
    save_accepted_fields(VALID_WHATSAPP_NUMBER, IN_PROGRESS_FIELDS)

    response = _post_extract(
        client,
        _text_payload(message="restart", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ceb4"),
    )
    body = response.json()

    assert body["conversation_language"] == LANGUAGE_ARABIC
    assert WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER).language == LANGUAGE_ARABIC


@override_settings(**MENU_SETTINGS)
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
def test_clickable_menu_template_sent_when_configured(mock_send_menu: MagicMock, client):
    mock_send_menu.return_value = "SMclickablemenusent000000000000"
    _seed_session(last_message_at=_inactive_last_message_at())
    save_accepted_fields(VALID_WHATSAPP_NUMBER, IN_PROGRESS_FIELDS)

    response = _post_extract(
        client,
        _text_payload(message="Hello again", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ceb5"),
    )
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "awaiting_menu_selection"
    mock_send_menu.assert_called_once()
    assert "reply_text" not in body
