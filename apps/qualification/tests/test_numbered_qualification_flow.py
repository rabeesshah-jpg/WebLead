"""Tests for the numbered multi-choice qualification state machine."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import Client, override_settings

from apps.qualification.conversation_state import (
    clear_conversations,
    get_accepted_fields,
    save_accepted_fields,
)
from apps.qualification.domain.numbered_qualification import (
    QUALIFICATION_OPTIONS,
    QUALIFICATION_STEPS,
    format_numbered_question,
    normalize_numbered_qualification_answer,
)
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.tests.internal_api_test_helpers import (
    API_SECRET,
    internal_api_auth_headers,
)

pytestmark = pytest.mark.django_db

ENDPOINT_PATH = "/api/internal/qualification/extract/"
WHATSAPP_NUMBER = "+923001231111"
BOOKING_LINK = "https://booking.example.com/test-schedule"
MESSAGE_SID = "SM0cc5a1d9e22bf9850ca24261ee23cef9"


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
    message: str,
    *,
    number: str = WHATSAPP_NUMBER,
    message_sid: str | None = None,
) -> dict:
    payload: dict[str, object] = {
        "message": message,
        "whatsapp_number": number,
        "input_channel": "whatsapp_text",
    }
    if message_sid is not None:
        payload["message_sid"] = message_sid
    response = client.post(
        ENDPOINT_PATH,
        data=payload,
        content_type="application/json",
        **internal_api_auth_headers(),
    )
    assert response.status_code == 200, response.content
    return response.json()


def _seed_ready_for_business_type() -> None:
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {"customer_type": "new_customer", "referral_source": "google"},
    )


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_first_qualification_step_is_business_type(mock_extract, client):
    save_accepted_fields(WHATSAPP_NUMBER, {"customer_type": "new_customer"})

    body = _post(client, "1")

    assert body["next_field"] == "business_type"
    assert body["qualification_step"] == "business_type"
    assert body["should_send_qualification_question"] is True
    assert body["qualification_complete"] is False
    assert body["language"] == "en"
    assert body["conversation_language"] == "en"
    assert QUALIFICATION_STEPS[0] == "business_type"
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_english_api_response_aliases(mock_extract, client):
    _seed_ready_for_business_type()

    body = _post(client, "hmm")

    assert body["should_send_qualification_question"] is True
    assert body["qualification_step"] == "business_type"
    assert body["language"] == "en"
    assert body["qualification_complete"] is False
    assert "What best describes your business?" in body["reply_text"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_arabic_api_response_aliases(mock_extract, client):
    from apps.qualification.channels import finalize_turn_response
    from apps.qualification.conversation_flow import try_handle_qualification_step_turn

    # Root conftest forces English on the extract endpoint unless marked
    # ``language_gate``. Exercise Arabic through the shared turn finalize path.
    _seed_ready_for_business_type()
    turn = try_handle_qualification_step_turn(
        whatsapp_number=WHATSAPP_NUMBER,
        message="hmm",
        language="ar",
    )
    assert turn is not None
    body = finalize_turn_response(
        turn,
        input_channel="whatsapp_text",
        conversation_language="ar",
        whatsapp_number=WHATSAPP_NUMBER,
    )

    assert body["should_send_qualification_question"] is True
    assert body["qualification_step"] == "business_type"
    assert body["language"] == "ar"
    assert body["conversation_language"] == "ar"
    assert body["qualification_complete"] is False
    assert "ما الذي يصف عملك بشكل أفضل؟" in body["reply_text"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_valid_answer_stores_option_id_and_localized_text(mock_extract, client):
    _seed_ready_for_business_type()

    body = _post(client, "1")

    assert body["accepted_fields"]["business_type"] == "biz_local_service"
    assert body["accepted_fields"]["business_type_option_id"] == "biz_local_service"
    assert body["accepted_fields"]["business_type_number"] == 1
    assert (
        body["accepted_fields"]["business_type_answer"]
        == "Local service business (clinic, salon, restaurant)"
    )
    assert body["next_field"] == "website_status"
    assert body["qualification_step"] == "website_status"
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@pytest.mark.parametrize("message", ["new website", "upgrade", "both", "5", "0", "hmm"])
def test_invalid_option_rejection(mock_extract, client, message):
    _seed_ready_for_business_type()

    body = _post(client, message)

    assert body["next_field"] == "business_type"
    assert "business_type" not in body["accepted_fields"]
    assert body["reply_text"] == format_numbered_question(
        field="business_type",
        language="en",
    )
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_cross_step_option_id_is_rejected(mock_extract, client):
    _seed_ready_for_business_type()

    body = _post(client, "ads_lt_2k")

    assert body["next_field"] == "business_type"
    assert "business_type" not in body["accepted_fields"]
    assert get_accepted_fields(WHATSAPP_NUMBER).get("business_type") is None
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_same_step_option_id_is_accepted(mock_extract, client):
    _seed_ready_for_business_type()

    body = _post(client, "biz_ecommerce")

    assert body["accepted_fields"]["business_type"] == "biz_ecommerce"
    assert body["accepted_fields"]["business_type_option_id"] == "biz_ecommerce"
    assert body["accepted_fields"]["business_type_number"] == 3
    assert body["next_field"] == "website_status"
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_full_flow_completes_and_continues_to_booking(mock_extract, client):
    _seed_ready_for_business_type()

    answers = ("1", "2", "1", "2", "1")
    body = {}
    for index, answer in enumerate(answers):
        body = _post(client, answer)
        if index < len(answers) - 1:
            assert body["next_field"] == QUALIFICATION_STEPS[index + 1]
            assert body["qualification_step"] == QUALIFICATION_STEPS[index + 1]
            assert body["qualification_status"] == "in_progress"
            assert body["qualification_complete"] is False
            assert BOOKING_LINK not in body["reply_text"]

    assert body["next_field"] is None
    assert body["qualification_step"] is None
    assert body["qualification_status"] == "completed"
    assert body["qualification_complete"] is True
    assert body["should_send_qualification_question"] is False
    assert BOOKING_LINK in body["reply_text"]
    assert body["accepted_fields"]["business_type"] == "biz_local_service"
    assert body["accepted_fields"]["website_status"] == "site_basic"
    assert body["accepted_fields"]["paid_ads"] == "ads_none"
    assert body["accepted_fields"]["main_goal"] == "goal_website_marketing"
    assert body["accepted_fields"]["launch_timeline"] == "timeline_30d"
    assert body["accepted_fields"]["launch_timeline_option_id"] == "timeline_30d"
    assert "Within 30 days" in body["accepted_fields"]["requirements"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_duplicate_message_sid_does_not_double_advance(mock_extract, client):
    _seed_ready_for_business_type()
    headers = internal_api_auth_headers()
    payload = {
        "message": "1",
        "whatsapp_number": WHATSAPP_NUMBER,
        "input_channel": "whatsapp_text",
        "message_sid": MESSAGE_SID,
    }

    first = client.post(
        ENDPOINT_PATH,
        data=payload,
        content_type="application/json",
        **headers,
    )
    second = client.post(
        ENDPOINT_PATH,
        data=payload,
        content_type="application/json",
        **headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["accepted_fields"]["business_type"] == "biz_local_service"
    assert second.json()["accepted_fields"]["business_type"] == "biz_local_service"
    assert first.json()["next_field"] == "website_status"
    assert second.json()["next_field"] == "website_status"
    assert get_accepted_fields(WHATSAPP_NUMBER)["business_type"] == "biz_local_service"
    mock_extract.assert_not_called()


def test_qualification_option_ids_are_stable_and_language_independent():
    assert QUALIFICATION_OPTIONS["business_type"] == frozenset(
        {
            "biz_local_service",
            "biz_coaching",
            "biz_ecommerce",
            "biz_other",
        }
    )
    assert QUALIFICATION_OPTIONS["paid_ads"] == frozenset(
        {
            "ads_none",
            "ads_boost",
            "ads_lt_2k",
            "ads_2k_10k",
            "ads_gt_10k",
        }
    )
    assert QUALIFICATION_OPTIONS["main_goal"] == frozenset(
        {
            "goal_website_only",
            "goal_website_marketing",
            "goal_more_customers",
        }
    )
    en = normalize_numbered_qualification_answer(
        "main_goal", "2", language="en"
    )
    ar = normalize_numbered_qualification_answer(
        "main_goal", "2", language="ar"
    )
    assert en is not None and ar is not None
    assert en["value"] == ar["value"] == "goal_website_marketing"
    assert en["answer"] != ar["answer"]


def test_normalize_rejects_out_of_range_and_cross_step_ids():
    assert normalize_numbered_qualification_answer("paid_ads", "3")["value"] == "ads_lt_2k"
    assert normalize_numbered_qualification_answer("paid_ads", "6") is None
    assert normalize_numbered_qualification_answer("business_type", "ads_lt_2k") is None
    assert normalize_numbered_qualification_answer("main_goal", "4") is None


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_business_type_list_picker_button_payload_is_accepted(mock_extract, client):
    from apps.qualification.conversation_flow import try_handle_qualification_step_turn

    _seed_ready_for_business_type()
    turn = try_handle_qualification_step_turn(
        whatsapp_number=WHATSAPP_NUMBER,
        message="Local service",
        language="en",
        button_payload="biz_local_service",
    )
    assert turn is not None
    assert turn["accepted_fields"]["business_type"] == "biz_local_service"
    assert turn["next_field"] == "website_status"
    mock_extract.assert_not_called()
