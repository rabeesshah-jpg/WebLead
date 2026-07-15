"""Tests for Arabic customer messages and conversation_language propagation."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from apps.qualification.conversation_flow import build_turn_response
from apps.qualification.conversation_state import clear_conversations, save_accepted_fields
from apps.qualification.domain.language_selection import LANGUAGE_ARABIC, LANGUAGE_ENGLISH
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.models import (
    QualificationFieldFilterResult,
    RejectedQualificationField,
    WhatsAppConversationSession,
)
from apps.qualification.prompts import ARABIC_CONVERSATION_INSTRUCTIONS, build_extraction_system_prompt
from apps.qualification.tests.internal_api_test_helpers import API_SECRET, internal_api_auth_headers

pytestmark = [pytest.mark.language_gate, pytest.mark.django_db]

ENDPOINT_PATH = "/api/internal/qualification/extract/"
VALID_WHATSAPP_NUMBER = "+923001234567"
MESSAGE_SID = "SM0cc5a1d9e22bf9850ca24261ee23ce90"
NEW_CUSTOMER_REFERRAL_EN = get_customer_message(
    language=LANGUAGE_ENGLISH, key="referral_source_new_customer_intro"
)
NEW_CUSTOMER_REFERRAL_AR = get_customer_message(
    language=LANGUAGE_ARABIC, key="referral_source_new_customer_intro"
)

LANGUAGE_PICKER_SETTINGS = {
    "TWILIO_LANGUAGE_PICKER_CONTENT_SID": "HXtestcontentsidfortest0000000000",
    "TWILIO_WHATSAPP_FROM_NUMBER": "whatsapp:+15557654321",
    "N8N_QUALIFICATION_API_SECRET": API_SECRET,
    "BOOKING_LINK": "https://booking.example.com/test-schedule",
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


def _post_extract(client: Client, payload: dict) -> object:
    return client.post(
        ENDPOINT_PATH,
        data=json.dumps(payload),
        content_type="application/json",
        **internal_api_auth_headers(secret=API_SECRET),
    )


def _text_payload(*, message: str, button_payload: str | None = None) -> dict:
    payload = {
        "message": message,
        "whatsapp_number": VALID_WHATSAPP_NUMBER,
        "input_channel": "whatsapp_text",
        "message_sid": MESSAGE_SID,
        "media_url": None,
        "media_content_type": None,
    }
    if button_payload is not None:
        payload["button_payload"] = button_payload
    return payload


def _arabic_session() -> WhatsAppConversationSession:
    return WhatsAppConversationSession.objects.create(
        whatsapp_number=VALID_WHATSAPP_NUMBER,
        language=LANGUAGE_ARABIC,
        language_selected_at=timezone.now(),
    )


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_lang_ar_starts_with_arabic_first_question(mock_extract, mock_send_picker, client):
    response = _post_extract(
        client,
        _text_payload(message="العربية", button_payload="lang_ar"),
    )

    body = response.json()
    assert response.status_code == 200
    assert body["reply_text"] == NEW_CUSTOMER_REFERRAL_AR
    assert body["next_field"] == "referral_source"
    assert body["accepted_fields"]["customer_type"] == "new_customer"
    assert body["conversation_language"] == LANGUAGE_ARABIC
    mock_extract.assert_not_called()
    mock_send_picker.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_lang_en_starts_with_existing_english_first_question(mock_extract, mock_send_picker, client):
    response = _post_extract(
        client,
        _text_payload(message="English", button_payload="lang_en"),
    )

    body = response.json()
    assert response.status_code == 200
    assert body["reply_text"] == NEW_CUSTOMER_REFERRAL_EN
    assert body["next_field"] == "referral_source"
    assert body["accepted_fields"]["customer_type"] == "new_customer"
    assert body["conversation_language"] == LANGUAGE_ENGLISH
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter", return_value=QualificationFieldFilterResult(
    accepted_fields={"project_type": "new_website"},
    rejected_fields=(),
    human_handoff_requested=False,
))
def test_arabic_qualification_turn_includes_conversation_language(mock_extract, mock_send_picker, client):
    _arabic_session()
    save_accepted_fields(
        VALID_WHATSAPP_NUMBER,
        {
            "customer_type": "new_customer",
            "referral_source": "google",
        },
    )

    response = _post_extract(client, _text_payload(message="أحتاج موقعًا جديدًا"))

    body = response.json()
    assert response.status_code == 200
    assert body["conversation_language"] == LANGUAGE_ARABIC
    assert get_customer_message(language=LANGUAGE_ARABIC, key="requirements") in body["reply_text"]
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter", return_value=QualificationFieldFilterResult(
    accepted_fields={"project_type": "new_website"},
    rejected_fields=(),
    human_handoff_requested=False,
))
def test_english_qualification_turn_includes_conversation_language(mock_extract, mock_send_picker, client):
    WhatsAppConversationSession.objects.create(
        whatsapp_number=VALID_WHATSAPP_NUMBER,
        language=LANGUAGE_ENGLISH,
        language_selected_at=timezone.now(),
    )
    save_accepted_fields(
        VALID_WHATSAPP_NUMBER,
        {
            "customer_type": "existing_customer",
        },
    )

    response = _post_extract(client, _text_payload(message="I need a new website"))

    body = response.json()
    assert response.status_code == 200
    assert body["conversation_language"] == LANGUAGE_ENGLISH
    assert get_customer_message(language=LANGUAGE_ENGLISH, key="requirements") in body["reply_text"]
    mock_extract.assert_not_called()


def test_openrouter_system_prompt_includes_arabic_instructions_for_arabic_sessions():
    prompt = build_extraction_system_prompt(conversation_language=LANGUAGE_ARABIC)
    assert ARABIC_CONVERSATION_INSTRUCTIONS in prompt
    assert "Respond to the customer only in Arabic" in prompt


def test_openrouter_system_prompt_unchanged_for_english_sessions():
    english_prompt = build_extraction_system_prompt(conversation_language=LANGUAGE_ENGLISH)
    assert "Respond to the customer only in Arabic" not in english_prompt


def test_build_turn_response_keeps_structured_keys_in_english_for_arabic():
    response = build_turn_response(
        whatsapp_number=VALID_WHATSAPP_NUMBER,
        filter_result=QualificationFieldFilterResult(
            accepted_fields={"project_type": "new_website"},
            rejected_fields=(),
            human_handoff_requested=False,
        ),
        language=LANGUAGE_ARABIC,
    )
    assert response["accepted_fields"]["project_type"] == "new_website"
    assert response["next_field"] == "customer_type"
    assert response["conversation_language"] == LANGUAGE_ARABIC


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_arabic_old_phone_confirmation_session_completes_in_arabic(mock_extract, mock_send_picker, client):
    # Backward compat: an old session left mid phone-confirmation is now complete.
    _arabic_session()
    save_accepted_fields(
        VALID_WHATSAPP_NUMBER,
        {
            "customer_type": "new_customer",
            "project_type": "new_website",
            "requirements": "موقع مطعم",
            "referral_source": "إنستغرام",
            "whatsapp_confirmed": False,
        },
    )

    response = _post_extract(client, _text_payload(message="مرحبا"))

    body = response.json()
    assert body["conversation_language"] == LANGUAGE_ARABIC
    assert body["qualification_status"] == "completed"
    assert body["reply_text"] != get_customer_message(language=LANGUAGE_ARABIC, key="invalid_phone")
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_english_old_phone_confirmation_session_completes_in_english(mock_extract, mock_send_picker, client):
    WhatsAppConversationSession.objects.create(
        whatsapp_number=VALID_WHATSAPP_NUMBER,
        language=LANGUAGE_ENGLISH,
        language_selected_at=timezone.now(),
    )
    save_accepted_fields(
        VALID_WHATSAPP_NUMBER,
        {
            "customer_type": "new_customer",
            "project_type": "new_website",
            "requirements": "restaurant website",
            "referral_source": "Instagram",
            "whatsapp_confirmed": False,
        },
    )

    response = _post_extract(client, _text_payload(message="hello"))

    body = response.json()
    assert body["conversation_language"] == LANGUAGE_ENGLISH
    assert body["qualification_status"] == "completed"
    assert body["reply_text"] != get_customer_message(language=LANGUAGE_ENGLISH, key="invalid_phone")
    mock_extract.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter", return_value=QualificationFieldFilterResult(
    accepted_fields={},
    rejected_fields=(
        RejectedQualificationField(field_name="requirements", reason="confidence below threshold"),
    ),
    human_handoff_requested=False,
))
def test_arabic_generic_retry_response_is_arabic(mock_extract, mock_send_picker, client):
    _arabic_session()
    save_accepted_fields(
        VALID_WHATSAPP_NUMBER,
        {
            "customer_type": "new_customer",
            "referral_source": "google",
            "project_type": "new_website",
        },
    )

    response = _post_extract(client, _text_payload(message="غير واضح"))

    body = response.json()
    assert body["conversation_language"] == LANGUAGE_ARABIC
    assert body["reply_text"] == get_customer_message(language=LANGUAGE_ARABIC, key="generic_retry")


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter", return_value=QualificationFieldFilterResult(
    accepted_fields={"requirements": "مساعدة عاجلة"},
    human_handoff_requested=True,
    rejected_fields=(),
))
def test_arabic_human_handoff_response_is_arabic(mock_extract, mock_send_picker, client):
    _arabic_session()
    save_accepted_fields(
        VALID_WHATSAPP_NUMBER,
        {
            "customer_type": "new_customer",
            "referral_source": "google",
            "project_type": "new_website",
        },
    )

    response = _post_extract(client, _text_payload(message="أريد التحدث مع شخص"))

    body = response.json()
    assert body["qualification_status"] == "human_handoff"
    assert body["conversation_language"] == LANGUAGE_ARABIC
    assert body["reply_text"] == get_customer_message(language=LANGUAGE_ARABIC, key="human_handoff")


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@patch("apps.qualification.services.transcription_service.VoiceNoteTranscriptionService.transcribe")
def test_language_selection_skips_deepgram_and_openrouter(
    mock_transcribe,
    mock_extract,
    mock_send_picker,
    client,
):
    for button_payload, message in (("lang_en", "English"), ("lang_ar", "العربية")):
        clear_conversations()
        clear_message_sid_cache()
        WhatsAppConversationSession.objects.all().delete()
        mock_extract.reset_mock()
        mock_transcribe.reset_mock()

        response = _post_extract(
            client,
            _text_payload(message=message, button_payload=button_payload),
        )

        assert response.status_code == 200
        mock_extract.assert_not_called()
        mock_transcribe.assert_not_called()


@override_settings(**LANGUAGE_PICKER_SETTINGS)
@patch("apps.qualification.services.language_gate_service.send_language_picker")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_arabic_completion_response_is_arabic(mock_extract, mock_send_picker, client):
    _arabic_session()
    save_accepted_fields(
        VALID_WHATSAPP_NUMBER,
        {
            "customer_type": "new_customer",
            "project_type": "new_website",
            "requirements": "موقع مطعم",
            "referral_source": "إنستغرام",
        },
    )

    completion = _post_extract(client, _text_payload(message="Yes"))
    body = completion.json()
    assert body["qualification_status"] == "completed"
    assert body["conversation_language"] == LANGUAGE_ARABIC
    assert body["reply_text"] == get_customer_message(
        language=LANGUAGE_ARABIC,
        key="completion_with_booking_link",
        booking_link=LANGUAGE_PICKER_SETTINGS["BOOKING_LINK"],
    )
    mock_extract.assert_not_called()
