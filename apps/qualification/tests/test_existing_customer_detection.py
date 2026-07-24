"""Tests for automatic existing-customer detection before the customer_type question.

These tests are not marked ``language_gate``; the root conftest bypasses the
language gate and forces English at the API layer. Arabic and voice behaviour are
exercised at the domain / channel level.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from apps.qualification.channels import finalize_turn_response
from apps.qualification.conversation_flow import try_handle_qualification_step_turn
from apps.qualification.conversation_state import (
    clear_conversations,
    get_accepted_fields,
    save_accepted_fields,
)
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.models import WhatsAppConversationSession
from apps.qualification.services.existing_customer_detection import (
    DETECTION_SOURCE_BOOKING_LINK,
    DETECTION_SOURCE_NONE,
    DETECTION_SOURCE_SESSION,
    detect_existing_customer,
    maybe_auto_detect_existing_customer,
)
from apps.qualification.tests.internal_api_test_helpers import (
    API_SECRET,
    internal_api_auth_headers,
)

pytestmark = pytest.mark.django_db

ENDPOINT_PATH = "/api/internal/qualification/extract/"
BOOKING_LINK = "https://booking.example.com/test-schedule"

EN_NOURA = get_customer_message(
    language="en", key="existing_customer_noura_followup"
)
AR_NOURA = get_customer_message(
    language="ar", key="existing_customer_noura_followup"
)
EN_CONNECTING = get_customer_message(language="en", key="existing_customer_connecting")
AR_CONNECTING = get_customer_message(language="ar", key="existing_customer_connecting")
EN_NEW_CUSTOMER_REFERRAL = get_customer_message(
    language="en", key="referral_source_new_customer_intro"
)
AR_NEW_CUSTOMER_REFERRAL = get_customer_message(
    language="ar", key="referral_source_new_customer_intro"
)
EN_NEW_CUSTOMER_REFERRAL_VOICE = get_customer_message(
    language="en", key="referral_source_new_customer_intro_voice"
)

SEND_PATH = (
    "apps.qualification.services.existing_customer_live_agent_service"
    ".send_whatsapp_text_message"
)
SLEEP_PATH = "apps.qualification.services.existing_customer_live_agent_service.time.sleep"


@pytest.fixture(autouse=True)
def _reset_state():
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()
    yield
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture
def mock_twilio_send():
    with patch(SEND_PATH, side_effect=["SMconnecting001", "SMnoura002"]) as mock_send:
        yield mock_send


@pytest.fixture
def mock_sleep():
    with patch(SLEEP_PATH) as mocked:
        yield mocked


def _make_qualified_session(number: str, *, language: str = "en") -> WhatsAppConversationSession:
    now = timezone.now()
    return WhatsAppConversationSession.objects.create(
        whatsapp_number=number,
        language=language,
        language_selected_at=now,
        booking_link_sent_at=now,
        qualified_at=now,
    )


def _post(
    client: Client,
    message: str,
    *,
    number: str,
    message_sid: str | None = None,
) -> dict:
    data: dict = {
        "message": message,
        "whatsapp_number": number,
        "input_channel": "whatsapp_text"}
    if message_sid is not None:
        data["message_sid"] = message_sid
    response = client.post(
        ENDPOINT_PATH,
        data=data,
        content_type="application/json",
        **internal_api_auth_headers(),
    )
    assert response.status_code == 200, response.content
    return response.json()


# --- detection unit tests ----------------------------------------------------


def test_detect_existing_customer_from_qualified_at():
    number = "+923001110001"
    _make_qualified_session(number)

    detection = detect_existing_customer(number)

    assert detection.detected is True
    assert detection.source == DETECTION_SOURCE_SESSION


def test_detect_existing_customer_from_booking_link_only():
    number = "+923001110002"
    now = timezone.now()
    WhatsAppConversationSession.objects.create(
        whatsapp_number=number,
        language="en",
        language_selected_at=now,
        booking_link_sent_at=now,
        qualified_at=None,
    )

    detection = detect_existing_customer(number)

    assert detection.detected is True
    assert detection.source == DETECTION_SOURCE_BOOKING_LINK


def test_detect_unknown_customer_returns_none_source():
    detection = detect_existing_customer("+923001110003")

    assert detection.detected is False
    assert detection.source == DETECTION_SOURCE_NONE


@pytest.mark.parametrize(
    "lookup_number",
    [
        "+923001110004",
        "whatsapp:+923001110004",
        "+92 300 111 0004",
        " whatsapp:+92 300 111 0004 ",
    ],
)
def test_detection_uses_normalized_whatsapp_numbers(lookup_number):
    _make_qualified_session("+923001110004")

    detection = detect_existing_customer(lookup_number)

    assert detection.detected is True
    assert detection.source == DETECTION_SOURCE_SESSION


# --- flow behaviour ----------------------------------------------------------


def test_known_existing_customer_sends_connecting_then_noura_after_sleep(
    mock_twilio_send, mock_sleep
):
    number = "+923001110010"
    _make_qualified_session(number)

    turn = maybe_auto_detect_existing_customer(
        whatsapp_number=number,
        language="en",
        input_channel="whatsapp_text",
    )

    assert turn is not None
    assert turn["accepted_fields"]["customer_type"] == "existing_customer"
    assert turn["accepted_fields"]["existing_customer_followup_sent"] is True
    assert "existing_customer_live_agent" not in turn["accepted_fields"]
    assert "referral_source" not in turn["accepted_fields"]
    assert turn["next_field"] == "business_type"
    assert turn["reply_text"] == ""
    assert turn["should_send_text"] is False
    assert turn["option_template"] == "business_type"
    assert turn["conversation_state"] == "WAITING_FOR_BUSINESS_TYPE"
    assert turn["qualification_step"] == "business_type"
    assert turn["qualification_complete"] is False
    assert turn["existing_customer_followup_scheduled"] is False
    assert turn["followup_delay_seconds"] == 5
    assert turn["should_send_qualification_question"] is True
    assert "What best describes your business?" not in turn["reply_text"]

    assert mock_twilio_send.call_count == 2
    assert mock_twilio_send.call_args_list[0] == call(
        to_number=number, body=EN_CONNECTING
    )
    assert mock_twilio_send.call_args_list[1] == call(to_number=number, body=EN_NOURA)
    mock_sleep.assert_called_once_with(5)
    # Sleep must happen after the connecting send succeeds.
    assert mock_twilio_send.call_args_list[0][1]["body"] == EN_CONNECTING

    session = WhatsAppConversationSession.objects.get(whatsapp_number=number)
    assert session.existing_customer_connecting_sent_at is not None
    assert session.existing_customer_noura_sent_at is not None
    assert session.existing_customer_followup_sent_at is not None
    assert get_accepted_fields(number)["customer_type"] == "existing_customer"


def test_unknown_customer_auto_assigned_new_and_asked_referral(mock_twilio_send, mock_sleep):
    number = "+923001110011"

    turn = maybe_auto_detect_existing_customer(
        whatsapp_number=number,
        language="en",
        input_channel="whatsapp_text",
    )

    assert turn is not None
    assert turn["accepted_fields"]["customer_type"] == "new_customer"
    assert turn["next_field"] == "referral_source"
    assert turn["reply_text"] == EN_NEW_CUSTOMER_REFERRAL
    assert get_accepted_fields(number)["customer_type"] == "new_customer"
    mock_twilio_send.assert_not_called()
    mock_sleep.assert_not_called()


def test_auto_detect_returns_none_when_customer_type_already_set(
    mock_twilio_send, mock_sleep
):
    number = "+923001110016"
    save_accepted_fields(number, {"customer_type": "new_customer"})

    assert (
        maybe_auto_detect_existing_customer(
            whatsapp_number=number,
            language="en",
            input_channel="whatsapp_text",
        )
        is None
    )
    mock_twilio_send.assert_not_called()
    mock_sleep.assert_not_called()


def test_new_customer_manual_flow_still_asks_referral():
    number = "+923001110012"

    turn = try_handle_qualification_step_turn(
        whatsapp_number=number,
        message="new customer",
        language="en",
    )

    assert turn is not None
    assert turn["accepted_fields"]["customer_type"] == "new_customer"
    assert turn["next_field"] == "referral_source"


def test_existing_customer_manual_selection_still_skips_referral():
    number = "+923001110013"

    turn = try_handle_qualification_step_turn(
        whatsapp_number=number,
        message="existing customer",
        language="en",
    )

    assert turn is not None
    assert turn["accepted_fields"]["customer_type"] == "existing_customer"
    assert turn["next_field"] == "business_type"
    assert "referral_source" not in turn["accepted_fields"]


def test_arabic_existing_customer_sends_arabic_twilio_messages(
    mock_twilio_send, mock_sleep
):
    number = "+923001110014"
    _make_qualified_session(number, language="ar")

    turn = maybe_auto_detect_existing_customer(
        whatsapp_number=number,
        language="ar",
        input_channel="whatsapp_text",
    )

    assert turn is not None
    assert turn["accepted_fields"]["customer_type"] == "existing_customer"
    assert turn["conversation_language"] == "ar"
    assert mock_twilio_send.call_args_list[0] == call(
        to_number=number, body=AR_CONNECTING
    )
    assert mock_twilio_send.call_args_list[1] == call(to_number=number, body=AR_NOURA)
    mock_sleep.assert_called_once_with(5)


def test_auto_detect_does_not_set_booking_flags(mock_twilio_send, mock_sleep):
    number = "+923001110015"
    _make_qualified_session(number)

    turn = maybe_auto_detect_existing_customer(
        whatsapp_number=number,
        language="en",
        input_channel="whatsapp_text",
    )

    assert turn is not None
    assert turn["qualification_status"] == "in_progress"
    assert turn.get("send_booking_link") is None
    assert turn.get("booking_link_sent") is None


def test_connecting_send_failure_skips_sleep_and_noura(mock_sleep):
    number = "+923001110017"
    _make_qualified_session(number)

    with patch(SEND_PATH, side_effect=RuntimeError("twilio down")):
        with pytest.raises(Exception, match="connecting message"):
            maybe_auto_detect_existing_customer(
                whatsapp_number=number,
                language="en",
                input_channel="whatsapp_text",
            )

    mock_sleep.assert_not_called()
    session = WhatsAppConversationSession.objects.get(whatsapp_number=number)
    assert session.existing_customer_connecting_sent_at is None
    assert session.existing_customer_followup_sent_at is None
    assert get_accepted_fields(number).get("customer_type") is None


def test_noura_send_failure_does_not_resend_connecting(mock_sleep):
    number = "+923001110018"
    _make_qualified_session(number)
    send_mock = MagicMock(side_effect=["SMconnecting001", RuntimeError("twilio down")])

    with patch(SEND_PATH, send_mock):
        with pytest.raises(Exception, match="Noura follow-up"):
            maybe_auto_detect_existing_customer(
                whatsapp_number=number,
                language="en",
                input_channel="whatsapp_text",
            )

    mock_sleep.assert_called_once_with(5)
    assert send_mock.call_count == 2
    assert send_mock.call_args_list[0] == call(to_number=number, body=EN_CONNECTING)
    session = WhatsAppConversationSession.objects.get(whatsapp_number=number)
    assert session.existing_customer_connecting_sent_at is not None
    assert session.existing_customer_noura_sent_at is None
    assert session.existing_customer_followup_sent_at is None
    assert get_accepted_fields(number).get("customer_type") is None


# --- channel behaviour -------------------------------------------------------


def test_text_handoff_returns_business_type_list_picker_not_numbered_body(
    mock_twilio_send, mock_sleep
):
    number = "+923001110020"
    _make_qualified_session(number)

    turn = maybe_auto_detect_existing_customer(
        whatsapp_number=number,
        language="en",
        input_channel="whatsapp_text",
    )
    assert turn is not None
    body = finalize_turn_response(
        turn,
        input_channel="whatsapp_text",
        conversation_language="en",
        whatsapp_number=number,
    )

    assert body["option_template"] == "business_type"
    assert body["reply_text"] == ""
    assert body["should_send_text"] is False
    assert body["should_send_audio"] is False
    assert body["should_send_qualification_question"] is True
    assert body["next_field"] == "business_type"
    assert body["qualification_step"] == "business_type"
    assert body["conversation_state"] == "WAITING_FOR_BUSINESS_TYPE"
    assert "What best describes your business?" not in body["reply_text"]


def test_voice_existing_customer_still_sends_whatsapp_text_only(
    mock_twilio_send, mock_sleep
):
    number = "+923001110021"
    _make_qualified_session(number)

    turn = maybe_auto_detect_existing_customer(
        whatsapp_number=number,
        language="en",
        input_channel="whatsapp_voice_note",
    )
    assert turn is not None
    body = finalize_turn_response(
        turn,
        input_channel="whatsapp_voice_note",
        conversation_language="en",
        whatsapp_number=number,
    )

    assert body.get("option_template") is None
    assert body["should_send_audio"] is False
    assert body["should_send_text"] is False
    assert mock_twilio_send.call_count == 2
    mock_sleep.assert_called_once_with(5)


def test_arabic_new_customer_gets_arabic_referral_intro(mock_twilio_send, mock_sleep):
    number = "+923001110023"
    WhatsAppConversationSession.objects.create(
        whatsapp_number=number,
        language="ar",
        language_selected_at=timezone.now(),
    )

    turn = maybe_auto_detect_existing_customer(
        whatsapp_number=number,
        language="ar",
        input_channel="whatsapp_text",
    )
    assert turn is not None
    assert turn["accepted_fields"]["customer_type"] == "new_customer"
    assert turn["next_field"] == "referral_source"
    assert turn["reply_text"] == AR_NEW_CUSTOMER_REFERRAL
    assert turn["conversation_language"] == "ar"
    mock_twilio_send.assert_not_called()
    mock_sleep.assert_not_called()


def test_text_new_customer_returns_referral_option_template(mock_twilio_send, mock_sleep):
    number = "+923001110024"

    turn = maybe_auto_detect_existing_customer(
        whatsapp_number=number,
        language="en",
        input_channel="whatsapp_text",
    )
    assert turn is not None
    body = finalize_turn_response(
        turn,
        input_channel="whatsapp_text",
        conversation_language="en",
        whatsapp_number=number,
    )

    assert body["option_template"] == "referral_source"
    assert body["reply_text"] == EN_NEW_CUSTOMER_REFERRAL
    assert body["should_send_text"] is True
    assert body["should_send_audio"] is False
    mock_twilio_send.assert_not_called()
    mock_sleep.assert_not_called()


def test_voice_new_customer_uses_spoken_intro_without_option_template(
    mock_twilio_send, mock_sleep
):
    number = "+923001110025"

    turn = maybe_auto_detect_existing_customer(
        whatsapp_number=number,
        language="en",
        input_channel="whatsapp_voice_note",
    )
    assert turn is not None
    body = finalize_turn_response(
        turn,
        input_channel="whatsapp_voice_note",
        conversation_language="en",
        whatsapp_number=number,
    )

    assert body.get("option_template") is None
    assert body["spoken_text"] == EN_NEW_CUSTOMER_REFERRAL_VOICE
    assert body["should_send_audio"] is True
    assert body["should_send_text"] is False
    mock_twilio_send.assert_not_called()
    mock_sleep.assert_not_called()


# --- API behaviour -----------------------------------------------------------


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@patch(SLEEP_PATH)
@patch(SEND_PATH, side_effect=["SMconnecting001", "SMnoura002"])
def test_api_known_existing_customer_runs_sync_handoff(
    mock_send, mock_sleep, mock_extract, client
):
    number = "+923001110030"
    _make_qualified_session(number)

    body = _post(client, "hello", number=number)

    assert body["accepted_fields"]["customer_type"] == "existing_customer"
    assert body["accepted_fields"]["existing_customer_followup_sent"] is True
    assert body["next_field"] == "business_type"
    assert body.get("option_template") == "business_type"
    assert body["conversation_state"] == "WAITING_FOR_BUSINESS_TYPE"
    assert body["reply_text"] == ""
    assert body["should_send_text"] is False
    assert body["should_send_qualification_question"] is True
    assert body["qualification_step"] == "business_type"
    assert body["qualification_complete"] is False
    assert body["human_handoff_requested"] is False
    assert "How did you hear about us?" not in (body.get("reply_text") or "")
    mock_extract.assert_not_called()
    mock_sleep.assert_called_once_with(5)
    assert mock_send.call_count == 2


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch(SLEEP_PATH)
@patch(SEND_PATH)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_api_unknown_customer_auto_assigned_new_and_asked_referral(
    mock_extract, mock_send, mock_sleep, client
):
    number = "+923001110031"

    body = _post(client, "hello", number=number)

    assert body["accepted_fields"]["customer_type"] == "new_customer"
    assert body["next_field"] == "referral_source"
    assert body["option_template"] == "referral_source"
    assert body["conversation_state"] == "WAITING_FOR_REFERRAL_SOURCE"
    assert body["reply_text"] == EN_NEW_CUSTOMER_REFERRAL
    mock_extract.assert_not_called()
    mock_send.assert_not_called()
    mock_sleep.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch(SLEEP_PATH)
@patch(SEND_PATH)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_api_customer_type_question_never_returned(
    mock_extract, mock_send, mock_sleep, client
):
    number = "+923001110032"

    body = _post(client, "hello", number=number)

    assert body["next_field"] != "customer_type"
    assert "new customer or an existing customer" not in body["reply_text"]
    mock_extract.assert_not_called()


# --- sync handoff invariants -------------------------------------------------


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@patch(SLEEP_PATH)
@patch(SEND_PATH, side_effect=["SMconnecting001", "SMnoura002"])
def test_duplicate_webhook_does_not_resend_messages(
    mock_send, mock_sleep, mock_extract, client
):
    number = "+923001110050"
    _make_qualified_session(number)
    message_sid = "SM0cc5a1d9e22bf9850ca24261ee23cef0"

    first = _post(client, "hello", number=number, message_sid=message_sid)
    assert first["accepted_fields"]["existing_customer_followup_sent"] is True
    assert first["conversation_state"] == "WAITING_FOR_BUSINESS_TYPE"
    assert first["should_send_qualification_question"] is True

    second = _post(client, "hello", number=number, message_sid=message_sid)
    assert second["accepted_fields"]["existing_customer_followup_sent"] is True
    # MessageSid idempotency returns the cached payload; Twilio is not called again.
    assert mock_send.call_count == 2
    mock_sleep.assert_called_once_with(5)
    mock_extract.assert_not_called()

    session = WhatsAppConversationSession.objects.get(whatsapp_number=number)
    assert session.existing_customer_followup_sent_at is not None


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@patch(SLEEP_PATH)
@patch(SEND_PATH, side_effect=["SMconnecting001", "SMnoura002", "SMextra1", "SMextra2"])
def test_second_distinct_webhook_does_not_resend_either_message(
    mock_send, mock_sleep, mock_extract, client
):
    number = "+923001110053"
    _make_qualified_session(number)

    first = _post(
        client,
        "hello",
        number=number,
        message_sid="SM0cc5a1d9e22bf9850ca24261ee23cef0",
    )
    assert first["accepted_fields"]["existing_customer_followup_sent"] is True

    second = _post(
        client,
        "ok",
        number=number,
        message_sid="SM0cc5a1d9e22bf9850ca24261ee23cef1",
    )
    assert second["accepted_fields"]["customer_type"] == "existing_customer"
    assert "referral_source" not in second.get("accepted_fields", {})
    assert second.get("option_template") != "referral_source"
    # Second inbound must not re-run connecting/sleep/noura.
    assert mock_send.call_count == 2
    mock_sleep.assert_called_once_with(5)


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@patch(SLEEP_PATH)
@patch(SEND_PATH, side_effect=["SMconnecting001", "SMnoura002"])
def test_existing_customer_flow_runs_inline_without_background_queue(
    mock_send, mock_sleep, mock_extract, client
):
    number = "+923001110052"
    _make_qualified_session(number)

    body = _post(client, "hello", number=number)
    assert body["conversation_state"] == "WAITING_FOR_BUSINESS_TYPE"
    assert body["should_send_qualification_question"] is True
    mock_sleep.assert_called_once_with(5)
    assert mock_send.call_count == 2


def test_accepted_fields_survive_simulated_memory_restart(mock_twilio_send, mock_sleep):
    """DB session is source of truth when the process-local overlay is wiped."""
    from apps.qualification.persistence.backends import get_persistence_backend

    number = "+923001110060"
    _make_qualified_session(number)

    turn = maybe_auto_detect_existing_customer(
        whatsapp_number=number,
        language="en",
        input_channel="whatsapp_text",
    )
    assert turn is not None
    assert turn["next_field"] == "business_type"

    session = WhatsAppConversationSession.objects.get(whatsapp_number=number)
    assert session.accepted_fields.get("customer_type") == "existing_customer"
    assert session.existing_customer_followup_sent_at is not None
    cycle_before = session.conversation_cycle

    # Simulate Django process restart with an in-memory backend wipe.
    get_persistence_backend().clear_conversations()
    clear_message_sid_cache()

    restored = get_accepted_fields(number)
    assert restored["customer_type"] == "existing_customer"
    assert restored["existing_customer_followup_sent"] is True
    assert restored["qualification_step"] == "business_type"

    # Auto-detect must not re-run handoff; customer_type already durable.
    assert (
        maybe_auto_detect_existing_customer(
            whatsapp_number=number,
            language="en",
            input_channel="whatsapp_text",
        )
        is None
    )
    assert mock_twilio_send.call_count == 2
    mock_sleep.assert_called_once_with(5)

    session.refresh_from_db()
    assert session.conversation_cycle == cycle_before
    assert session.existing_customer_followup_sent_at is not None


def test_new_conversation_cycle_resets_only_delivery_markers(mock_twilio_send, mock_sleep):
    from apps.qualification.services.conversation_restart_service import (
        restart_qualification_conversation,
    )

    number = "+923001110061"
    session = _make_qualified_session(number)
    maybe_auto_detect_existing_customer(
        whatsapp_number=number,
        language="en",
        input_channel="whatsapp_text",
    )
    session.refresh_from_db()
    assert session.existing_customer_followup_sent_at is not None
    assert session.qualified_at is not None
    cycle_before = session.conversation_cycle

    restart_qualification_conversation(whatsapp_number=number, session=session)
    session.refresh_from_db()

    assert session.qualified_at is not None
    assert session.existing_customer_connecting_sent_at is None
    assert session.existing_customer_noura_sent_at is None
    assert session.existing_customer_followup_sent_at is None
    assert session.existing_customer_business_type_picker_sent_at is None
    assert session.accepted_fields == {}
    assert session.conversation_cycle == cycle_before + 1
    assert get_accepted_fields(number) == {}


def test_stale_delivery_markers_reconciled_when_fields_empty():
    from apps.qualification.services.existing_customer_live_agent_service import (
        reconcile_stale_existing_customer_delivery_markers,
    )

    number = "+923001110062"
    now = timezone.now()
    WhatsAppConversationSession.objects.create(
        whatsapp_number=number,
        language="en",
        language_selected_at=now,
        qualified_at=now,
        existing_customer_connecting_sent_at=now,
        existing_customer_noura_sent_at=now,
        existing_customer_followup_sent_at=now,
        accepted_fields={},
    )

    reconcile_stale_existing_customer_delivery_markers(whatsapp_number=number)

    session = WhatsAppConversationSession.objects.get(whatsapp_number=number)
    assert session.existing_customer_connecting_sent_at is None
    assert session.existing_customer_followup_sent_at is None
    assert session.qualified_at == now
