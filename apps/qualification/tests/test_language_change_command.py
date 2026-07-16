"""Tests for explicit /language slash-command handling."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from apps.qualification.conversation_state import clear_conversations, get_accepted_fields, save_accepted_fields
from apps.qualification.domain.language_selection import LANGUAGE_ARABIC, LANGUAGE_ENGLISH
from apps.qualification.domain.messages import (
    get_customer_message,
    get_language_changed_confirmation_message,
)
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.models import QualificationFieldFilterResult, WhatsAppConversationSession
from apps.qualification.tests.internal_api_test_helpers import API_SECRET, internal_api_auth_headers

pytestmark = [pytest.mark.language_gate, pytest.mark.django_db]

ENDPOINT_PATH = "/api/internal/qualification/extract/"
VALID_WHATSAPP_NUMBER = "+923001234567"
MESSAGE_SID = "SM0cc5a1d9e22bf9850ca24261ee23ce90"
CHANGE_MESSAGE_SID = "SM0cc5a1d9e22bf9850ca24261ee23ce91"
SELECT_MESSAGE_SID = "SM0cc5a1d9e22bf9850ca24261ee23ce92"

LANGUAGE_PICKER_SETTINGS = {
    "TWILIO_LANGUAGE_PICKER_CONTENT_SID": "HXtestcontentsidfortest0000000000",
    "TWILIO_WHATSAPP_FROM_NUMBER": "whatsapp:+15557654321",
    "N8N_QUALIFICATION_API_SECRET": API_SECRET,
}

IN_PROGRESS_FIELDS = {
    "customer_type": "new_customer",
}


def _expect_language_change_reply(*, language: str, next_field: str) -> str:
    return (
        f"{get_language_changed_confirmation_message(language=language)}\n\n"
        f"{get_customer_message(language=language, key=next_field)}"
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
    message_sid: str = MESSAGE_SID,
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


def _english_session_with_progress() -> WhatsAppConversationSession:
    save_accepted_fields(VALID_WHATSAPP_NUMBER, dict(IN_PROGRESS_FIELDS))
    return WhatsAppConversationSession.objects.create(
        whatsapp_number=VALID_WHATSAPP_NUMBER,
        language=LANGUAGE_ENGLISH,
        language_selected_at=timezone.now(),
    )


def _arabic_session_with_progress() -> WhatsAppConversationSession:
    save_accepted_fields(VALID_WHATSAPP_NUMBER, dict(IN_PROGRESS_FIELDS))
    return WhatsAppConversationSession.objects.create(
        whatsapp_number=VALID_WHATSAPP_NUMBER,
        language=LANGUAGE_ARABIC,
        language_selected_at=timezone.now(),
    )


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker", return_value="SMpicker000000000000000000000001")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_slash_language_resends_picker_without_changing_language_or_data(
    mock_extract,
    mock_send_picker,
    client,
):
    session = _english_session_with_progress()
    previous_selected_at = session.language_selected_at

    response = _post_extract(client, _text_payload(message="/language", message_sid=CHANGE_MESSAGE_SID))

    assert response.status_code == 200
    assert response.json() == {
        "status": "awaiting_language_selection",
        "message": "Language selector sent.",
        "language_command_action": "picker_sent",
    }
    mock_send_picker.assert_called_once_with(to_number=f"whatsapp:{VALID_WHATSAPP_NUMBER}")
    mock_extract.assert_not_called()
    session.refresh_from_db()
    assert session.language == LANGUAGE_ENGLISH
    assert session.language_selected_at == previous_selected_at
    assert session.language_picker_pending_until is not None
    assert get_accepted_fields(VALID_WHATSAPP_NUMBER) == IN_PROGRESS_FIELDS


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker", return_value="SMpicker000000000000000000000001")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_slash_language_from_arabic_conversation_preserves_data(
    mock_extract,
    mock_send_picker,
    client,
):
    _arabic_session_with_progress()

    response = _post_extract(client, _text_payload(message="/language", message_sid=CHANGE_MESSAGE_SID))

    assert response.status_code == 200
    assert response.json()["status"] == "awaiting_language_selection"
    session = WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER)
    assert session.language == LANGUAGE_ARABIC
    assert get_accepted_fields(VALID_WHATSAPP_NUMBER) == IN_PROGRESS_FIELDS
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_arabic_conversation_slash_language_set_en(
    mock_extract,
    mock_send_picker,
    client,
):
    session = _arabic_session_with_progress()
    previous_selected_at = session.language_selected_at

    response = _post_extract(
        client,
        _text_payload(message="/language set en", message_sid=CHANGE_MESSAGE_SID),
    )

    assert response.status_code == 200
    body = response.json()
    session.refresh_from_db()
    assert session.language == LANGUAGE_ENGLISH
    assert session.language_selected_at >= previous_selected_at
    assert session.language_picker_pending_until is None
    assert session.awaiting_language_reselection is False
    assert get_accepted_fields(VALID_WHATSAPP_NUMBER) == IN_PROGRESS_FIELDS
    assert body["next_field"] == "referral_source"
    assert body["reply_text"] == _expect_language_change_reply(
        language=LANGUAGE_ENGLISH,
        next_field="referral_source",
    )
    assert body["conversation_language"] == LANGUAGE_ENGLISH
    assert body["language_command_action"] == "language_changed"
    mock_send_picker.assert_not_called()
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_english_conversation_slash_language_set_arabic(
    mock_extract,
    mock_send_picker,
    client,
):
    _english_session_with_progress()

    response = _post_extract(
        client,
        _text_payload(message="/language set العربية", message_sid=CHANGE_MESSAGE_SID),
    )

    assert response.status_code == 200
    body = response.json()
    assert WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER).language == LANGUAGE_ARABIC
    assert body["next_field"] == "referral_source"
    assert body["reply_text"] == _expect_language_change_reply(
        language=LANGUAGE_ARABIC,
        next_field="referral_source",
    )
    assert body["language_command_action"] == "language_changed"
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_button_after_slash_language_updates_language_and_preserves_progress(
    mock_extract,
    mock_send_picker,
    client,
):
    _english_session_with_progress()

    _post_extract(client, _text_payload(message="/language", message_sid=CHANGE_MESSAGE_SID))
    response = _post_extract(
        client,
        _text_payload(
            message="العربية",
            message_sid=SELECT_MESSAGE_SID,
            button_payload="lang_ar",
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_language"] == LANGUAGE_ARABIC
    assert body["next_field"] == "referral_source"
    assert body["reply_text"] == _expect_language_change_reply(
        language=LANGUAGE_ARABIC,
        next_field="referral_source",
    )
    assert get_accepted_fields(VALID_WHATSAPP_NUMBER) == IN_PROGRESS_FIELDS
    mock_send_picker.assert_called_once()
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_lang_ar_button_from_english_returns_arabic_confirmation(mock_extract, mock_send_picker, client):
    _english_session_with_progress()

    response = _post_extract(
        client,
        _text_payload(
            message="العربية",
            message_sid=SELECT_MESSAGE_SID,
            button_payload="lang_ar",
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_language"] == LANGUAGE_ARABIC
    assert body["reply_text"] == _expect_language_change_reply(
        language=LANGUAGE_ARABIC,
        next_field="referral_source",
    )
    assert get_accepted_fields(VALID_WHATSAPP_NUMBER) == IN_PROGRESS_FIELDS
    mock_send_picker.assert_not_called()
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_lang_en_button_from_arabic_returns_english_confirmation(mock_extract, mock_send_picker, client):
    _arabic_session_with_progress()

    response = _post_extract(
        client,
        _text_payload(
            message="English",
            message_sid=SELECT_MESSAGE_SID,
            button_payload="lang_en",
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_language"] == LANGUAGE_ENGLISH
    assert body["reply_text"] == _expect_language_change_reply(
        language=LANGUAGE_ENGLISH,
        next_field="referral_source",
    )
    assert get_accepted_fields(VALID_WHATSAPP_NUMBER) == IN_PROGRESS_FIELDS
    mock_send_picker.assert_not_called()
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker", return_value="SMpicker000000000000000000000001")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_next_message_after_language_change_continues_qualification(
    mock_extract,
    mock_send_picker,
    client,
):
    _english_session_with_progress()

    _post_extract(client, _text_payload(message="/language", message_sid=CHANGE_MESSAGE_SID))
    _post_extract(
        client,
        _text_payload(
            message="العربية",
            message_sid=SELECT_MESSAGE_SID,
            button_payload="lang_ar",
        ),
    )

    response = _post_extract(
        client,
        _text_payload(message="سمعت عنكم على فيسبوك", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce93"),
    )

    assert response.status_code == 200
    mock_extract.assert_not_called()
    fields = get_accepted_fields(VALID_WHATSAPP_NUMBER)
    assert fields["customer_type"] == "new_customer"
    assert fields["referral_source"] == "facebook"
    assert response.json()["next_field"] == "business_type"


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter", return_value=QualificationFieldFilterResult(
    accepted_fields={"referral_source": "Facebook"},
    rejected_fields=(),
    human_handoff_requested=False,
))
def test_normal_message_mentioning_english_does_not_change_language(
    mock_extract,
    mock_send_picker,
    client,
):
    _english_session_with_progress()

    response = _post_extract(
        client,
        _text_payload(message="I need an English website.", message_sid=CHANGE_MESSAGE_SID),
    )

    assert response.status_code == 200
    mock_extract.assert_not_called()
    assert WhatsAppConversationSession.objects.get(whatsapp_number=VALID_WHATSAPP_NUMBER).language == LANGUAGE_ENGLISH


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_typed_english_switches_arabic_conversation_to_english(
    mock_extract,
    mock_send_picker,
    client,
):
    _arabic_session_with_progress()

    response = _post_extract(
        client,
        _text_payload(message="English", message_sid=CHANGE_MESSAGE_SID),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_language"] == LANGUAGE_ENGLISH
    assert body["next_field"] == "referral_source"
    assert body["reply_text"] == _expect_language_change_reply(
        language=LANGUAGE_ENGLISH,
        next_field="referral_source",
    )
    assert (
        WhatsAppConversationSession.objects.get(
            whatsapp_number=VALID_WHATSAPP_NUMBER
        ).language
        == LANGUAGE_ENGLISH
    )
    assert get_accepted_fields(VALID_WHATSAPP_NUMBER) == IN_PROGRESS_FIELDS
    mock_send_picker.assert_not_called()
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_typed_arabic_switches_english_conversation_to_arabic(
    mock_extract,
    mock_send_picker,
    client,
):
    _english_session_with_progress()

    response = _post_extract(
        client,
        _text_payload(message="العربية", message_sid=CHANGE_MESSAGE_SID),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_language"] == LANGUAGE_ARABIC
    assert body["next_field"] == "referral_source"
    assert body["reply_text"] == _expect_language_change_reply(
        language=LANGUAGE_ARABIC,
        next_field="referral_source",
    )
    assert (
        WhatsAppConversationSession.objects.get(
            whatsapp_number=VALID_WHATSAPP_NUMBER
        ).language
        == LANGUAGE_ARABIC
    )
    assert get_accepted_fields(VALID_WHATSAPP_NUMBER) == IN_PROGRESS_FIELDS
    mock_send_picker.assert_not_called()
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_typed_switch_to_english_returns_english_referral_option_template(
    mock_extract,
    mock_send_picker,
    client,
):
    _arabic_session_with_progress()

    response = _post_extract(
        client,
        _text_payload(message="en", message_sid=CHANGE_MESSAGE_SID),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_language"] == LANGUAGE_ENGLISH
    assert body["option_template"] == "referral_source"
    assert get_customer_message(
        language=LANGUAGE_ENGLISH, key="referral_source"
    ) in body["reply_text"]
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_typed_switch_to_arabic_returns_arabic_referral_option_template(
    mock_extract,
    mock_send_picker,
    client,
):
    _english_session_with_progress()

    response = _post_extract(
        client,
        _text_payload(message="ar", message_sid=CHANGE_MESSAGE_SID),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_language"] == LANGUAGE_ARABIC
    assert body["option_template"] == "referral_source"
    assert get_customer_message(
        language=LANGUAGE_ARABIC, key="referral_source"
    ) in body["reply_text"]
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker", return_value="SMpicker000000000000000000000001")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_duplicate_message_sid_does_not_resend_picker(mock_extract, mock_send_picker, client):
    _english_session_with_progress()
    payload = _text_payload(message="/language", message_sid=CHANGE_MESSAGE_SID)

    first = _post_extract(client, payload)
    second = _post_extract(client, payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    mock_send_picker.assert_called_once()
    mock_extract.assert_not_called()
