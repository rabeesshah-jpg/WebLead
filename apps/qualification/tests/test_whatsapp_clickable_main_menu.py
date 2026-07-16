"""Tests for Twilio list-picker WhatsApp main menu routing."""

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
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.models import QualificationFieldFilterResult, WhatsAppConversationSession
from apps.qualification.tests.internal_api_test_helpers import (
    API_SECRET,
    internal_api_auth_headers,
)

pytestmark = [pytest.mark.django_db, pytest.mark.whatsapp_menu]

ENDPOINT_PATH = "/api/internal/qualification/extract/"
VALID_WHATSAPP_NUMBER = "+923001234567"
MENU_CONTENT_SID = "HXtestmainmenucontentsid00000000"

# Valid Twilio MessageSid values (SM + 32 alphanumeric chars).
SID_MENU_SHOW = "SM0cc5a1d9e22bf9850ca24261ee23ceb6"
SID_MENU_CONTINUE = "SM0cc5a1d9e22bf9850ca24261ee23ceb7"
SID_MENU_RESTART = "SM0cc5a1d9e22bf9850ca24261ee23ceb8"
SID_MENU_LANGUAGE = "SM0cc5a1d9e22bf9850ca24261ee23ceb9"
SID_MENU_HUMAN = "SM0cc5a1d9e22bf9850ca24261ee23ceba"
SID_UNKNOWN_MENU = "SM0cc5a1d9e22bf9850ca24261ee23cec0"
SID_UNKNOWN_PAYLOAD = "SM0cc5a1d9e22bf9850ca24261ee23cec1"
SID_IDEMPOTENT_RESTART = "SM0cc5a1d9e22bf9850ca24261ee23cec2"
SID_FEATURE_FLAG_OFF = "SM0cc5a1d9e22bf9850ca24261ee23cec3"

MAIN_MENU_SETTINGS = {
    "TWILIO_LANGUAGE_PICKER_CONTENT_SID": "HXtestcontentsidfortest0000000000",
    "TWILIO_WHATSAPP_FROM_NUMBER": "whatsapp:+15557654321",
    "TWILIO_WHATSAPP_MENU_CONTENT_SID": MENU_CONTENT_SID,
    "TWILIO_MENU_CONTENT_SID": "",
    "LEAD_QUALIFICATION_ENABLED": True,
    "SESSION_IDLE_RESET_SECONDS": 7200,
    "N8N_QUALIFICATION_API_SECRET": API_SECRET,
}

IN_PROGRESS_FIELDS = {
    "customer_type": "new_customer",
    "project_type": "new_website",
    "requirements": "A restaurant website with online ordering",
    "referral_source": "Google",
    "whatsapp_confirmed": True,
    "preferred_phone": VALID_WHATSAPP_NUMBER,
}

PARTIAL_FIELDS = {
    "customer_type": "new_customer",
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
    message: str | None = "Hello",
    message_sid: str,
    button_payload: str | None = None,
    button_text: str | None = None,
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
    if button_text is not None:
        payload["button_text"] = button_text
    return payload


def _seed_session() -> WhatsAppConversationSession:
    return WhatsAppConversationSession.objects.create(
        whatsapp_number=VALID_WHATSAPP_NUMBER,
        language="en",
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


@override_settings(**MAIN_MENU_SETTINGS)
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
def test_menu_command_sends_twilio_content_sid_instead_of_plain_text(mock_send_menu: MagicMock, client):
    mock_send_menu.return_value = "SMmainmenusent0000000000000000"
    _seed_session()
    save_accepted_fields(VALID_WHATSAPP_NUMBER, IN_PROGRESS_FIELDS)

    response = _post_extract(client, _text_payload(message="M", message_sid=SID_MENU_SHOW))
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "awaiting_menu_selection"
    mock_send_menu.assert_called_once()
    assert "reply_text" not in body


@pytest.mark.parametrize(
    ("button_payload", "message_sid", "assertions"),
    [
        (
            "continue",
            SID_MENU_CONTINUE,
            lambda body, session: (
                body["accepted_fields"] == PARTIAL_FIELDS
                and body["next_field"] == "referral_source"
            ),
        ),
        (
            "restart",
            SID_MENU_RESTART,
            lambda body, session: (
                get_accepted_fields(VALID_WHATSAPP_NUMBER) == {}
                and body.get("status") == "awaiting_language_selection"
                and session.language is None
            ),
        ),
        (
            "language",
            SID_MENU_LANGUAGE,
            lambda body, session: body.get("status") == "awaiting_language_selection",
        ),
        (
            "human",
            SID_MENU_HUMAN,
            lambda body, session: (
                body["human_handoff_requested"] is True
                and session.human_handoff_requested_at is not None
            ),
        ),
        (
            "menu_continue",
            "SM0cc5a1d9e22bf9850ca24261ee23cec4",
            lambda body, session: body["next_field"] == "referral_source",
        ),
    ],
)
@override_settings(**MAIN_MENU_SETTINGS)
@patch("apps.qualification.services.whatsapp_menu_service.send_language_picker")
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
def test_each_button_payload_routes_correctly(
    mock_send_menu: MagicMock,
    mock_send_picker: MagicMock,
    client,
    button_payload: str,
    message_sid: str,
    assertions,
):
    mock_send_menu.return_value = "SMmainmenusent0000000000000000"
    mock_send_picker.return_value = "SMlanguagepickersent000000000000"
    _seed_session()
    save_accepted_fields(VALID_WHATSAPP_NUMBER, PARTIAL_FIELDS)

    response = _post_extract(
        client,
        _text_payload(
            message="Selected option",
            message_sid=message_sid,
            button_payload=button_payload,
            button_text="Visible label",
        ),
    )
    body = response.json()
    session = WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER)
    session.refresh_from_db()

    assert response.status_code == 200
    assert assertions(body, session)


@override_settings(**MAIN_MENU_SETTINGS)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
def test_unknown_payload_resends_menu(
    mock_send_menu: MagicMock,
    mock_extract: MagicMock,
    client,
):
    mock_send_menu.return_value = "SMmainmenusent0000000000000000"
    _seed_session()
    save_accepted_fields(VALID_WHATSAPP_NUMBER, PARTIAL_FIELDS)

    _post_extract(client, _text_payload(message="M", message_sid=SID_UNKNOWN_MENU))
    response = _post_extract(
        client,
        _text_payload(
            message="Mystery",
            message_sid=SID_UNKNOWN_PAYLOAD,
            button_payload="menu_unknown_option",
            button_text="Mystery",
        ),
    )
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "awaiting_menu_selection"
    assert mock_send_menu.call_count == 2
    mock_extract.assert_not_called()


@override_settings(**MAIN_MENU_SETTINGS)
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
def test_repeated_message_sid_is_idempotent_for_menu_restart(mock_send_menu: MagicMock, client):
    mock_send_menu.return_value = "SMmainmenusent0000000000000000"
    _seed_session()
    save_accepted_fields(VALID_WHATSAPP_NUMBER, IN_PROGRESS_FIELDS)
    message_sid = SID_IDEMPOTENT_RESTART
    payload = _text_payload(
        message="Restart",
        message_sid=message_sid,
        button_payload="menu_restart",
        button_text="Restart",
    )

    first = _post_extract(client, payload)
    second = _post_extract(client, payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert get_accepted_fields(VALID_WHATSAPP_NUMBER) == {}


@override_settings(
    **{
        **MAIN_MENU_SETTINGS,
        "LEAD_QUALIFICATION_ENABLED": False,
    }
)
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_feature_flag_disabled_skips_menu_and_uses_normal_flow(
    mock_extract: MagicMock,
    mock_send_menu: MagicMock,
    client,
):
    mock_extract.return_value = QualificationFieldFilterResult(
        accepted_fields={"project_type": "new_website"},
        rejected_fields=(),
        human_handoff_requested=False,
    )
    _seed_session()

    response = _post_extract(
        client,
        _text_payload(message="M", message_sid=SID_FEATURE_FLAG_OFF),
    )
    body = response.json()

    assert response.status_code == 200
    mock_send_menu.assert_not_called()
    assert body["accepted_fields"]["project_type"] == "new_website"
    mock_extract.assert_called_once()
