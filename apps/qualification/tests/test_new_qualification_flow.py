"""Tests for the client-approved menu-driven qualification flow.

Flow order (language is handled by the Twilio picker gate before this flow):
    customer_type -> referral_source (new customers only) -> numbered questions
    -> booking link.

The language gate is bypassed and the conversation language is forced to English
for these tests by the root ``conftest`` autouse fixture (they are not marked
``language_gate``). Arabic and voice behaviour are exercised at the domain level.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from apps.qualification.conversation_flow import (
    next_missing_question,
    try_handle_qualification_step_turn,
)
from apps.qualification.conversation_state import (
    clear_conversations,
    get_accepted_fields,
    save_accepted_fields,
)
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.domain.numbered_qualification import (
    NUMBERED_QUALIFICATION_FIELDS,
    apply_numbered_selection,
    format_numbered_question,
    normalize_numbered_qualification_answer,
)
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.models import WhatsAppConversationSession
from apps.qualification.qualification_turn import run_qualification_turn
from apps.qualification.tests.internal_api_test_helpers import (
    API_SECRET,
    internal_api_auth_headers,
)

pytestmark = pytest.mark.django_db

ENDPOINT_PATH = "/api/internal/qualification/extract/"
WHATSAPP_NUMBER = "+923001239999"
BOOKING_LINK = "https://booking.example.com/test-schedule"
COMPLETION_REPLY_TEXT = get_customer_message(
    language="en",
    key="completion_with_booking_link",
    booking_link=BOOKING_LINK,
)


def _completed_numbered_fields() -> dict:
    fields: dict = {
        "customer_type": "new_customer",
        "referral_source": "google",
    }
    answers = ("1", "1", "1", "1", "1")
    for field, answer in zip(NUMBERED_QUALIFICATION_FIELDS, answers, strict=True):
        selection = normalize_numbered_qualification_answer(field, answer, language="en")
        assert selection is not None
        fields = apply_numbered_selection(fields, field, selection)
    return fields


@pytest.fixture
def client() -> Client:
    clear_conversations()
    return Client()


@pytest.fixture(autouse=True)
def _reset_conversation_state():
    clear_conversations()
    clear_message_sid_cache()
    yield
    clear_conversations()
    clear_message_sid_cache()


def _make_qualified_session(number: str, *, language: str = "en") -> WhatsAppConversationSession:
    now = timezone.now()
    session, _ = WhatsAppConversationSession.objects.get_or_create(
        whatsapp_number=number,
        defaults={
            "language": language,
            "language_selected_at": now,
            "booking_link_sent_at": now,
            "qualified_at": now,
        },
    )
    return session


def _post(client: Client, message: str, *, number: str = WHATSAPP_NUMBER) -> dict:
    response = client.post(
        ENDPOINT_PATH,
        data={
            "message": message,
            "whatsapp_number": number,
            "input_channel": "whatsapp_text",
        },
        content_type="application/json",
        **internal_api_auth_headers(),
    )
    assert response.status_code == 200, response.content
    return response.json()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_new_session_auto_assigns_new_customer_and_asks_referral(mock_extract, client):
    body = _post(client, "start")

    assert body["accepted_fields"]["customer_type"] == "new_customer"
    assert body["next_field"] == "referral_source"
    assert "new customer or an existing customer" not in body["reply_text"]
    assert "How did you hear about us?" in body["reply_text"]
    assert body["qualification_status"] == "in_progress"
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_new_customer_moves_to_referral_source(mock_extract, client):
    body = _post(client, "new customer")

    assert body["accepted_fields"]["customer_type"] == "new_customer"
    assert body["next_field"] == "referral_source"
    assert "How did you hear about us?" in body["reply_text"]
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
def test_detected_existing_customer_starts_connecting_flow(
    mock_send, mock_sleep, mock_extract, client
):
    _make_qualified_session(WHATSAPP_NUMBER)

    body = _post(client, "existing customer")

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
def test_customer_type_question_is_never_asked(mock_extract, client):
    body = _post(client, "2")

    assert body["next_field"] != "customer_type"
    assert "new customer or an existing customer" not in body["reply_text"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_referral_answer_moves_to_business_type(mock_extract, client):
    save_accepted_fields(WHATSAPP_NUMBER, {"customer_type": "new_customer"})

    body = _post(client, "google")

    assert body["accepted_fields"]["referral_source"] == "google"
    assert body["next_field"] == "business_type"
    assert body["qualification_step"] == "business_type"
    assert body["should_send_qualification_question"] is True
    assert body["qualification_complete"] is False
    assert body["language"] == "en"
    assert "What best describes your business?" in body["reply_text"]
    assert "project_type" not in body["accepted_fields"]
    assert "Are you wanting to build a new website" not in body["reply_text"]
    assert body.get("option_template") is None
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@pytest.mark.parametrize("message", ["facebook", "Facebook", "FACEBOOK", "fb"])
def test_facebook_referral_text_moves_to_business_type(mock_extract, client, message):
    save_accepted_fields(WHATSAPP_NUMBER, {"customer_type": "new_customer"})

    body = _post(client, message)

    assert body["accepted_fields"]["referral_source"] == "facebook"
    assert body["next_field"] == "business_type"
    assert body["qualification_step"] == "business_type"
    assert body["should_send_qualification_question"] is True
    assert body["qualification_complete"] is False
    assert "project_type" not in (body.get("reply_text") or "").lower()
    assert body.get("option_template") is None
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_facebook_referral_button_payload_moves_to_business_type(mock_extract, client):
    save_accepted_fields(WHATSAPP_NUMBER, {"customer_type": "new_customer"})

    response = client.post(
        ENDPOINT_PATH,
        data={
            "message": "Facebook",
            "button_payload": "facebook",
            "whatsapp_number": WHATSAPP_NUMBER,
            "input_channel": "whatsapp_text",
        },
        content_type="application/json",
        **internal_api_auth_headers(),
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["accepted_fields"]["referral_source"] == "facebook"
    assert body["next_field"] == "business_type"
    assert body["qualification_step"] == "business_type"
    assert body["conversation_state"] == "WAITING_FOR_BUSINESS_TYPE"
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_invalid_referral_source_reasks_without_500(mock_extract, client):
    save_accepted_fields(WHATSAPP_NUMBER, {"customer_type": "new_customer"})

    # Avoid substrings that match legitimate referral keywords (e.g. "referral").
    body = _post(client, "not-a-known-channel-xyz")

    assert body["next_field"] == "referral_source"
    assert body["accepted_fields"].get("referral_source") is None
    assert "How did you hear about us?" in body["reply_text"]
    assert body["qualification_status"] == "in_progress"
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_numbered_referral_answer_is_normalized(mock_extract, client):
    save_accepted_fields(WHATSAPP_NUMBER, {"customer_type": "new_customer"})

    body = _post(client, "3")

    assert body["accepted_fields"]["referral_source"] == "facebook"
    assert body["next_field"] == "business_type"
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_business_type_answer_moves_to_website_status(mock_extract, client):
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {"customer_type": "new_customer", "referral_source": "google"},
    )

    body = _post(client, "1")

    assert body["accepted_fields"]["business_type"] == "biz_local_service"
    assert body["accepted_fields"]["business_type_number"] == 1
    assert body["next_field"] == "website_status"
    assert "Do you currently have a website?" in body["reply_text"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_keyword_project_type_no_longer_advances(mock_extract, client):
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {"customer_type": "existing_customer"},
    )

    body = _post(client, "both")

    assert "business_type" not in body["accepted_fields"]
    assert body["next_field"] == "business_type"
    assert body["reply_text"] == format_numbered_question(
        field="business_type",
        language="en",
    )
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_final_numbered_answer_sends_booking_link_and_fills_contact(mock_extract, client):
    fields = _completed_numbered_fields()
    fields.pop("launch_timeline")
    fields.pop("launch_timeline_number", None)
    fields.pop("launch_timeline_answer", None)
    save_accepted_fields(WHATSAPP_NUMBER, fields)

    body = _post(client, "1")

    assert body["next_field"] is None
    assert body["qualification_status"] == "completed"
    assert BOOKING_LINK in body["reply_text"]
    assert body["reply_text"] == COMPLETION_REPLY_TEXT
    assert body["booking_link"] == BOOKING_LINK
    assert body["accepted_fields"]["whatsapp_confirmed"] is True
    assert body["accepted_fields"]["preferred_phone"] == WHATSAPP_NUMBER
    assert body.get("conversation_state") == "BOOKING_LINK_SENT"


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_full_new_customer_flow_end_to_end(mock_extract, client):
    first = _post(client, "new")
    assert first["next_field"] == "referral_source"

    second = _post(client, "friend")
    assert second["accepted_fields"]["referral_source"] == "friend_referral"
    assert second["next_field"] == "business_type"

    body = second
    for expected_next, answer in zip(
        NUMBERED_QUALIFICATION_FIELDS[1:] + (None,),
        ("1", "2", "3", "2", "4"),
        strict=True,
    ):
        body = _post(client, answer)
        assert body["next_field"] == expected_next

    assert body["qualification_status"] == "completed"
    assert BOOKING_LINK in body["reply_text"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_phone_confirmation_is_never_asked(mock_extract, client):
    for message in ("new", "google", "1", "1", "1", "1", "1"):
        body = _post(client, message)
        assert "best contact number" not in body["reply_text"]
        assert "best number to reach you" not in body["reply_text"]
        assert body.get("next_field") != "whatsapp_confirmed"
        assert body.get("next_field") != "preferred_phone"


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_booking_link_is_sent_only_once(mock_extract, client):
    save_accepted_fields(WHATSAPP_NUMBER, _completed_numbered_fields())

    first = _post(client, "an online store")
    assert first["qualification_status"] == "completed"
    assert BOOKING_LINK in first["reply_text"]
    assert first["booking_link_sent"] is True

    second = _post(client, "thanks")
    assert second["qualification_status"] == "completed"
    assert BOOKING_LINK not in second["reply_text"]
    assert "booking link above" in second["reply_text"]
    assert second["send_booking_link"] is False


def test_onboarding_intro_has_no_menu_or_help_instructions():
    for language in ("en", "ar"):
        intro = get_customer_message(language=language, key="onboarding_intro")
        assert "Send M" not in intro
        assert "menu" not in intro.lower()
        assert "voice note" not in intro.lower()
        assert "أرسل M" not in intro
        assert "القائمة" not in intro


# --- Domain-level flow (shared handler used by both text and voice) -----------


def test_voice_transcript_follows_the_same_flow():
    number = "+923004440001"
    clear_conversations()
    with patch(
        "apps.qualification.qualification_turn.get_conversation_language",
        return_value="en",
    ):
        response = run_qualification_turn(
            whatsapp_number=number,
            message="new customer",
            for_voice=True,
        )

    assert response["accepted_fields"]["customer_type"] == "new_customer"
    assert response["next_field"] == "referral_source"
    assert get_accepted_fields(number)["customer_type"] == "new_customer"


def test_next_missing_question_returns_customer_type_first():
    number = "+923004440002"
    clear_conversations()
    question = next_missing_question(whatsapp_number=number, language="en")
    assert question is not None
    assert "new customer or an existing customer" in question


def test_arabic_customer_type_question_is_arabic():
    number = "+923004440003"
    clear_conversations()
    response = try_handle_qualification_step_turn(
        whatsapp_number=number,
        message="مرحبا",
        language="ar",
    )
    assert response is not None
    # Unrecognized answer re-asks the current question in Arabic.
    assert response["next_field"] == "customer_type"
    assert "عميل جديد" in response["reply_text"]
    assert response["conversation_language"] == "ar"


def test_arabic_referral_capture_moves_to_business_type_in_arabic():
    number = "+923004440005"
    clear_conversations()
    save_accepted_fields(number, {"customer_type": "new_customer"})
    response = try_handle_qualification_step_turn(
        whatsapp_number=number,
        message="فيسبوك",
        language="ar",
    )
    assert response is not None
    assert response["accepted_fields"]["referral_source"] == "facebook"
    assert response["next_field"] == "business_type"
    assert "ما الذي يصف عملك بشكل أفضل؟" in response["reply_text"]
    assert response["conversation_language"] == "ar"


def test_arabic_new_customer_capture_moves_to_referral_in_arabic():
    number = "+923004440004"
    clear_conversations()
    response = try_handle_qualification_step_turn(
        whatsapp_number=number,
        message="1",
        language="ar",
    )
    assert response is not None
    assert response["accepted_fields"]["customer_type"] == "new_customer"
    assert response["next_field"] == "referral_source"
    assert "كيف سمعت عنا؟" in response["reply_text"]


def test_arabic_business_type_numeric_capture_stores_arabic_answer():
    number = "+923004440006"
    clear_conversations()
    save_accepted_fields(number, {"customer_type": "existing_customer"})

    response = try_handle_qualification_step_turn(
        whatsapp_number=number,
        message="1",
        language="ar",
    )

    assert response is not None
    assert response["accepted_fields"]["business_type"] == "biz_local_service"
    assert response["accepted_fields"]["business_type_number"] == 1
    assert "عمل خدمات محلي" in response["accepted_fields"]["business_type_answer"]
    assert response["next_field"] == "website_status"
    assert response["conversation_language"] == "ar"
    assert "هل لديك موقع إلكتروني حاليًا؟" in response["reply_text"]


def test_arabic_business_type_selection_does_not_send_option_template():
    from apps.qualification.channels import finalize_turn_response

    number = "+923004440006"
    clear_conversations()
    save_accepted_fields(number, {"customer_type": "existing_customer"})

    turn = try_handle_qualification_step_turn(
        whatsapp_number=number,
        message="2",
        language="ar",
    )
    assert turn is not None
    body = finalize_turn_response(
        turn,
        input_channel="whatsapp_text",
        conversation_language="ar",
        whatsapp_number=number,
    )

    assert body["accepted_fields"]["business_type"] == "biz_coaching"
    assert body["next_field"] == "website_status"
    assert body.get("option_template") is None
