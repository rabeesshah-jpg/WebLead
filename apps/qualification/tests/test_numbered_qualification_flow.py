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
        "input_channel": "whatsapp_text"}
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


def _seed_ready_for_website_status() -> None:
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "customer_type": "new_customer",
            "referral_source": "facebook",
            "business_type": "biz_local_service",
            "business_type_option_id": "biz_local_service",
            "business_type_number": 1,
            "business_type_answer": "Local service business (clinic, salon, restaurant)"},
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
        "message_sid": MESSAGE_SID}

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
            "biz_other"}
    )
    assert QUALIFICATION_OPTIONS["paid_ads"] == frozenset(
        {
            "ads_none",
            "ads_boost",
            "ads_lt_2k",
            "ads_2k_10k",
            "ads_gt_10k"}
    )
    assert QUALIFICATION_OPTIONS["main_goal"] == frozenset(
        {
            "goal_website_only",
            "goal_website_marketing",
            "goal_more_customers"}
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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", "biz_local_service"),
        ("2", "biz_coaching"),
        ("3", "biz_ecommerce"),
        ("4", "biz_other"),
        ("local_service", "biz_local_service"),
        ("coaching", "biz_coaching"),
        ("ecommerce", "biz_ecommerce"),
        ("other", "biz_other"),
        ("biz_local_service", "biz_local_service"),
        ("LOCAL_SERVICE", "biz_local_service"),
    ],
)
def test_normalize_accepts_numeric_canonical_and_twilio_list_picker_ids(raw, expected):
    selection = normalize_numbered_qualification_answer("business_type", raw, language="en")
    assert selection is not None
    assert selection["value"] == expected


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


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@pytest.mark.parametrize(
    ("message", "button_payload", "expected"),
    [
        ("local_service", None, "biz_local_service"),
        ("coaching", None, "biz_coaching"),
        ("ecommerce", None, "biz_ecommerce"),
        ("other", None, "biz_other"),
        ("Local service business", "local_service", "biz_local_service"),
        ("ignored label", "coaching", "biz_coaching"),
    ],
)
def test_business_type_twilio_list_picker_values_advance_state(
    mock_extract,
    client,
    message,
    button_payload,
    expected,
):
    from apps.qualification.conversation_flow import try_handle_qualification_step_turn

    _seed_ready_for_business_type()
    turn = try_handle_qualification_step_turn(
        whatsapp_number=WHATSAPP_NUMBER,
        message=message,
        language="en",
        button_payload=button_payload,
    )
    assert turn is not None
    assert turn["accepted_fields"]["business_type"] == expected
    assert turn["accepted_fields"]["business_type_option_id"] == expected
    assert turn["next_field"] == "website_status"
    assert get_accepted_fields(WHATSAPP_NUMBER)["business_type"] == expected
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_local_service_body_saves_business_type_via_extract_api(mock_extract, client):
    """Reproduce production bug: Twilio Body=local_service, no ButtonPayload."""
    _seed_ready_for_business_type()

    body = _post(client, "local_service")

    assert body["accepted_fields"]["business_type"] == "biz_local_service"
    assert body["conversation_state"] == "WAITING_FOR_WEBSITE_STATUS"
    assert body["next_field"] == "website_status"
    assert get_accepted_fields(WHATSAPP_NUMBER)["business_type"] == "biz_local_service"
    mock_extract.assert_not_called()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", "site_none"),
        ("2", "site_basic"),
        ("3", "site_old_professional"),
        ("4", "site_modern"),
        ("no_website", "site_none"),
        ("basic_website", "site_basic"),
        ("old_professional", "site_old_professional"),
        ("modern_site", "site_modern"),
        ("site_old_professional", "site_old_professional"),
        ("No website yet", "site_none"),
        ("Yes, a basic / DIY website", "site_basic"),
        ("Old professional site", "site_old_professional"),
        ("Professional website but more than 3 years old", "site_old_professional"),
        ("Yes, a professional site but 3+ years old", "site_old_professional"),
        ("Yes, a modern site we're mostly happy with", "site_modern"),
    ],
)
def test_normalize_accepts_website_status_twilio_ids_and_labels(raw, expected):
    selection = normalize_numbered_qualification_answer(
        "website_status", raw, language="en"
    )
    assert selection is not None
    assert selection["value"] == expected


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@pytest.mark.parametrize(
    ("message", "button_payload", "expected"),
    [
        ("no_website", None, "site_none"),
        ("basic_website", None, "site_basic"),
        ("old_professional", None, "site_old_professional"),
        ("modern_site", None, "site_modern"),
        ("No website yet", None, "site_none"),
        ("Old professional site", None, "site_old_professional"),
        ("Professional website but more than 3 years old", None, "site_old_professional"),
        ("Yes, a basic / DIY website", "basic_website", "site_basic"),
        ("ignored label", "old_professional", "site_old_professional"),
    ],
)
def test_website_status_twilio_list_picker_values_advance_state(
    mock_extract,
    client,
    message,
    button_payload,
    expected,
):
    from apps.qualification.conversation_flow import try_handle_qualification_step_turn

    _seed_ready_for_website_status()
    turn = try_handle_qualification_step_turn(
        whatsapp_number=WHATSAPP_NUMBER,
        message=message,
        language="en",
        button_payload=button_payload,
    )
    assert turn is not None
    assert turn["accepted_fields"]["website_status"] == expected
    assert turn["accepted_fields"]["website_status_option_id"] == expected
    assert turn["next_field"] == "paid_ads"
    assert get_accepted_fields(WHATSAPP_NUMBER)["website_status"] == expected
    # Prior steps remain intact; website question must not repeat.
    assert turn["accepted_fields"]["business_type"] == "biz_local_service"
    assert turn["rejected_fields"] == {}
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_old_professional_body_saves_website_status_via_extract_api(mock_extract, client):
    """Reproduce production bug: Twilio Body=old_professional, no ButtonPayload."""
    _seed_ready_for_website_status()

    body = _post(client, "old_professional")

    assert body["accepted_fields"]["website_status"] == "site_old_professional"
    assert body["conversation_state"] == "WAITING_FOR_PAID_ADS"
    assert body["next_field"] == "paid_ads"
    assert "Do you currently have a website?" not in body["reply_text"]
    assert get_accepted_fields(WHATSAPP_NUMBER)["website_status"] == "site_old_professional"
    mock_extract.assert_not_called()


@pytest.mark.parametrize(
    ("field", "raw", "expected"),
    [
        ("paid_ads", "ads_under_2k", "ads_lt_2k"),
        ("paid_ads", "no_ads", "ads_none"),
        ("paid_ads", "ads_boost", "ads_boost"),
        ("paid_ads", "ads_2k_10k", "ads_2k_10k"),
        ("paid_ads", "ads_mid", "ads_2k_10k"),
        ("paid_ads", "ads_over_10k", "ads_gt_10k"),
        ("paid_ads", "ads_high", "ads_gt_10k"),
        ("main_goal", "website_only", "goal_website_only"),
        ("main_goal", "website_marketing", "goal_website_marketing"),
        ("main_goal", "more_customers", "goal_more_customers"),
        ("launch_timeline", "within_30_days", "timeline_30d"),
        ("launch_timeline", "1_3_months", "timeline_1_3m"),
        ("launch_timeline", "3_6_months", "timeline_3_6m"),
        ("launch_timeline", "exploring", "timeline_exploring"),
        ("website_status", "site_old", "site_old_professional"),
    ],
)
def test_central_twilio_aliases_resolve_for_all_numbered_steps(field, raw, expected):
    selection = normalize_numbered_qualification_answer(field, raw, language="en")
    assert selection is not None
    assert selection["value"] == expected


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_ads_under_2k_saves_paid_ads_and_advances(mock_extract, client):
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "customer_type": "new_customer",
            "referral_source": "facebook",
            "business_type": "biz_local_service",
            "website_status": "site_old_professional"},
    )

    body = _post(client, "ads_under_2k")

    assert body["accepted_fields"]["paid_ads"] == "ads_lt_2k"
    assert body["conversation_state"] == "WAITING_FOR_MAIN_GOAL"
    assert body["next_field"] == "main_goal"
    assert "Do you currently run paid ads?" not in body["reply_text"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_alias_already_saved_skips_step_without_repeating_question(mock_extract, client):
    """If an alias was stored raw, canonicalize + skip to the next unanswered step."""
    from apps.qualification.conversation_flow import try_handle_qualification_step_turn

    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "customer_type": "new_customer",
            "referral_source": "facebook",
            "business_type": "biz_local_service",
            # Raw Twilio alias (pre-fix storage) must still count as answered.
            "website_status": "old_professional"},
    )

    turn = try_handle_qualification_step_turn(
        whatsapp_number=WHATSAPP_NUMBER,
        message="ads_under_2k",
        language="en",
    )
    assert turn is not None
    assert turn["accepted_fields"]["website_status"] == "site_old_professional"
    assert turn["accepted_fields"]["paid_ads"] == "ads_lt_2k"
    assert turn["next_field"] == "main_goal"
    assert "Do you currently have a website?" not in (turn.get("reply_text") or "")
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_full_twilio_list_picker_journey_never_repeats_a_question(mock_extract, client):
    """End-to-end new-customer journey using production Twilio list-picker IDs."""
    question_for_field = {
        "business_type": "What best describes your business?",
        "website_status": "Do you currently have a website?",
        "paid_ads": "Do you currently run paid ads?",
        "main_goal": "What are you mainly looking for from us right now?",
        "launch_timeline": "How soon would you like to launch"}
    journey = [
        ("1", "customer_type", "new_customer", "WAITING_FOR_REFERRAL_SOURCE", "referral_source"),
        ("instagram", "referral_source", "instagram", "WAITING_FOR_BUSINESS_TYPE", "business_type"),
        (
            "local_service",
            "business_type",
            "biz_local_service",
            "WAITING_FOR_WEBSITE_STATUS",
            "website_status",
        ),
        (
            "old_professional",
            "website_status",
            "site_old_professional",
            "WAITING_FOR_PAID_ADS",
            "paid_ads",
        ),
        ("ads_under_2k", "paid_ads", "ads_lt_2k", "WAITING_FOR_MAIN_GOAL", "main_goal"),
        (
            "website_marketing",
            "main_goal",
            "goal_website_marketing",
            "WAITING_FOR_LAUNCH_TIMELINE",
            "launch_timeline",
        ),
        ("within_30_days", "launch_timeline", "timeline_30d", "BOOKING_LINK_SENT", None),
    ]
    body: dict = {}

    for message, field, expected_value, expected_state, expected_next in journey:
        body = _post(client, message)
        assert body["accepted_fields"][field] == expected_value, field
        assert body["conversation_state"] == expected_state, field
        assert body["next_field"] == expected_next, field
        reply = body.get("reply_text") or ""
        prompt = question_for_field.get(field)
        if prompt:
            assert prompt not in reply, (field, reply)

    assert body["qualification_status"] == "completed"
    assert BOOKING_LINK in body["reply_text"]
    fields = get_accepted_fields(WHATSAPP_NUMBER)
    assert fields["customer_type"] == "new_customer"
    assert fields["referral_source"] == "instagram"
    assert fields["business_type"] == "biz_local_service"
    assert fields["website_status"] == "site_old_professional"
    assert fields["paid_ads"] == "ads_lt_2k"
    assert fields["main_goal"] == "goal_website_marketing"
    assert fields["launch_timeline"] == "timeline_30d"
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@patch("apps.qualification.conversation_flow.log_qualification_event")
def test_stale_website_option_ignored_while_waiting_for_main_goal(
    mock_log_event,
    mock_extract,
    client,
):
    """Late Twilio website_status payload must not re-ask main_goal."""
    from apps.qualification.conversation_flow import try_handle_qualification_step_turn

    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "customer_type": "new_customer",
            "referral_source": "facebook",
            "business_type": "biz_local_service",
            "website_status": "site_old_professional",
            "paid_ads": "ads_lt_2k"},
    )

    turn = try_handle_qualification_step_turn(
        whatsapp_number=WHATSAPP_NUMBER,
        message="professional_site",
        language="en",
    )
    assert turn is not None
    assert turn["next_field"] == "main_goal"
    assert turn.get("stale_option_ignored") is True
    assert turn["should_send_qualification_question"] is False
    assert turn["should_send_text"] is False
    assert turn["reply_text"] == ""
    assert turn["accepted_fields"]["paid_ads"] == "ads_lt_2k"
    assert "main_goal" not in turn["accepted_fields"]

    body = _post(client, "professional_site")
    assert body["next_field"] == "main_goal"
    assert body["conversation_state"] == "WAITING_FOR_MAIN_GOAL"
    assert body["should_send_qualification_question"] is False
    assert body["should_send_text"] is False
    assert body["reply_text"] == ""
    assert "What are you mainly looking for from us right now?" not in (body.get("reply_text") or "")

    stale_calls = [
        call
        for call in mock_log_event.call_args_list
        if call.args and call.args[0] == "stale_option_ignored"
    ]
    assert len(stale_calls) >= 1
    assert stale_calls[0].kwargs["matched_previous_step"] == "website_status"
    assert stale_calls[0].kwargs["incoming_option"] == "professional_site"
    assert stale_calls[0].kwargs["current_state"] == "WAITING_FOR_MAIN_GOAL"
    assert "goal_website_only" in stale_calls[0].kwargs["expected_options"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_journey_with_late_stale_picker_does_not_duplicate_questions(mock_extract, client):
    """Full journey including a late prior-step list-picker tap stays on track."""
    steps = [
        "1",
        "instagram",
        "local_service",
        "old_professional",
        "ads_under_2k",
    ]
    for message in steps:
        body = _post(client, message)

    assert body["next_field"] == "main_goal"
    assert body["accepted_fields"]["paid_ads"] == "ads_lt_2k"

    stale = _post(client, "professional_site")
    assert stale["next_field"] == "main_goal"
    assert stale["should_send_qualification_question"] is False
    assert stale["reply_text"] == ""
    assert stale["accepted_fields"]["website_status"] == "site_old_professional"
    assert "main_goal" not in stale["accepted_fields"]

    continued = _post(client, "goal_marketing")
    assert continued["accepted_fields"]["main_goal"] == "goal_website_marketing"
    assert continued["next_field"] == "launch_timeline"
    assert "What are you mainly looking for from us right now?" not in continued["reply_text"]

    done = _post(client, "within_30_days")
    assert done["qualification_status"] == "completed"
    assert done["accepted_fields"]["launch_timeline"] == "timeline_30d"
    mock_extract.assert_not_called()


def test_professional_site_alias_maps_to_website_status():
    selection = normalize_numbered_qualification_answer(
        "website_status", "professional_site", language="en"
    )
    assert selection is not None
    assert selection["value"] == "site_old_professional"
