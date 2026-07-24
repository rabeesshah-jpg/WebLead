"""Tests for ExtractService."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from apps.qualification.conversation_state import clear_conversations
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.message_idempotency import cache_turn_response, clear_message_sid_cache
from apps.qualification.models import WhatsAppConversationSession
from apps.qualification.models import QualificationFieldFilterResult, RejectedQualificationField
from apps.qualification.qualification_turn import QualificationServiceRequestError
from apps.qualification.services.extract_service import ExtractService

pytestmark = pytest.mark.django_db

VALID_MESSAGE = "I need a new website for a restaurant"
VALID_WHATSAPP_NUMBER = "+923001234567"
WAHA_MEDIA_URL = "https://waha.example.com/api/files/true_923246271149@c.us_VOICE001.ogg"
MESSAGE_SID = "SM0cc5a1d9e22bf9850ca24261ee23ce90"
VOICE_TRANSCRIPT = "I need a website for my bakery"
REFERRAL_QUESTION = "Thank you. How did you hear about us?"


def _intro_prefixed_text(*, body: str) -> str:
    intro = get_customer_message(language="en", key="onboarding_intro")
    return f"{intro}\n\n{body}".strip()


def _expected_turn_response(*, channel: str = "text") -> dict:
    body = REFERRAL_QUESTION
    text_reply = _intro_prefixed_text(body=body)
    voice_intro = get_customer_message(language="en", key="onboarding_intro_voice")
    if channel == "voice":
        spoken = voice_intro
        reply = spoken
    else:
        spoken = text_reply
        reply = text_reply
    payload = {
        "accepted_fields": {
            "project_type": "new_website",
            "requirements": "website for a restaurant"},
        "rejected_fields": {"referral_source": "value_missing"},
        "human_handoff_requested": False,
        "next_field": "referral_source",
        "reply_text": reply,
        "qualification_status": "in_progress",
        "conversation_language": "en",
        "preferred_phone": None,
        "reply_mode": "text",
        "spoken_text": spoken,
        "whatsapp_text": text_reply,
        "actions": [],
        "send_booking_link": False,
        "booking_link_sent": False,
        "booking_link": None}
    return payload


SAMPLE_FILTER_RESULT = QualificationFieldFilterResult(
    accepted_fields={
        "project_type": "new_website",
        "requirements": "website for a restaurant"},
    rejected_fields=(
        RejectedQualificationField(field_name="referral_source", reason="null value"),
    ),
    human_handoff_requested=False,
)

TEXT_VALIDATED_DATA = {
    "whatsapp_number": VALID_WHATSAPP_NUMBER,
    "message": VALID_MESSAGE,
    "input_channel": "whatsapp_text",
    "message_sid": None,
    "media_url": None,
    "media_content_type": None}

VOICE_VALIDATED_DATA = {
    "whatsapp_number": VALID_WHATSAPP_NUMBER,
    "message": None,
    "input_channel": "whatsapp_voice_note",
    "message_sid": None,
    "media_url": WAHA_MEDIA_URL,
    "media_content_type": "audio/ogg"}


@pytest.fixture(autouse=True)
def _clear_idempotency_cache():
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()
    yield
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()


def test_extract_service_run_turn_returns_plain_dict_not_response():
    turn_handler = MagicMock(return_value={"accepted_fields": {}, "rejected_fields": {}})
    result = ExtractService(turn_handler=turn_handler).run_turn(TEXT_VALIDATED_DATA)
    assert isinstance(result, dict)
    assert not hasattr(result, "status_code")


@patch("apps.qualification.services.extract_service.run_qualification_turn")
def test_text_input_does_not_call_transcription_service(mock_turn_handler):
    mock_turn_handler.return_value = {
        "accepted_fields": {},
        "rejected_fields": {},
        "human_handoff_requested": False,
        "next_field": "referral_source",
        "reply_text": "Thank you. How did you hear about us?",
        "qualification_status": "in_progress",
        "preferred_phone": None}
    transcription_service = MagicMock()

    ExtractService(
        transcription_service=transcription_service,
        turn_handler=mock_turn_handler,
    ).run_turn(TEXT_VALIDATED_DATA)

    transcription_service.transcribe.assert_not_called()
    mock_turn_handler.assert_called_once_with(
        whatsapp_number=VALID_WHATSAPP_NUMBER,
        message=VALID_MESSAGE,
        message_sid=None,
        for_voice=False,
    )


@patch("apps.qualification.services.extract_service.run_qualification_turn")
def test_voice_input_calls_transcription_service_once(mock_turn_handler):
    transcription_service = MagicMock()
    transcription_service.transcribe.return_value = VOICE_TRANSCRIPT
    mock_turn_handler.return_value = {
        "accepted_fields": {},
        "rejected_fields": {},
        "human_handoff_requested": False,
        "next_field": "referral_source",
        "reply_text": "Thank you. How did you hear about us?",
        "qualification_status": "in_progress",
        "preferred_phone": None}

    ExtractService(
        transcription_service=transcription_service,
        turn_handler=mock_turn_handler,
    ).run_turn(VOICE_VALIDATED_DATA)

    transcription_service.transcribe.assert_called_once_with(
        media_url=WAHA_MEDIA_URL,
        media_content_type="audio/ogg",
        message_sid=None,
        conversation_language="en",
    )
    mock_turn_handler.assert_called_once_with(
        whatsapp_number=VALID_WHATSAPP_NUMBER,
        message=VOICE_TRANSCRIPT,
        message_sid=None,
        for_voice=True,
    )


@patch("apps.qualification.services.extract_service.run_qualification_turn")
def test_text_turn_returns_expected_payload(mock_turn_handler):
    mock_turn_handler.return_value = {
        "accepted_fields": SAMPLE_FILTER_RESULT.accepted_fields,
        "rejected_fields": {"referral_source": "value_missing"},
        "human_handoff_requested": False,
        "next_field": "referral_source",
        "reply_text": "Thank you. How did you hear about us?",
        "qualification_status": "in_progress",
        "preferred_phone": None}

    result = ExtractService(turn_handler=mock_turn_handler).run_turn(TEXT_VALIDATED_DATA)

    assert result == _expected_turn_response()


@patch("apps.qualification.services.extract_service.run_qualification_turn")
def test_voice_turn_returns_expected_payload_with_transcript(mock_turn_handler):
    mock_turn_handler.return_value = {
        "accepted_fields": SAMPLE_FILTER_RESULT.accepted_fields,
        "rejected_fields": {"referral_source": "value_missing"},
        "human_handoff_requested": False,
        "next_field": "referral_source",
        "reply_text": "Thank you. How did you hear about us?",
        "qualification_status": "in_progress",
        "preferred_phone": None}
    transcription_service = MagicMock()
    transcription_service.transcribe.return_value = VOICE_TRANSCRIPT

    result = ExtractService(
        transcription_service=transcription_service,
        turn_handler=mock_turn_handler,
    ).run_turn(VOICE_VALIDATED_DATA)

    expected = _expected_turn_response(channel="voice")
    expected["reply_mode"] = "voice"
    expected["transcript"] = VOICE_TRANSCRIPT
    assert result == expected


@patch("apps.qualification.services.extract_service.run_qualification_turn")
def test_duplicate_message_sid_returns_cached_payload_without_second_turn(mock_turn_handler):
    mock_turn_handler.return_value = {
        "accepted_fields": SAMPLE_FILTER_RESULT.accepted_fields,
        "rejected_fields": {"referral_source": "value_missing"},
        "human_handoff_requested": False,
        "next_field": "referral_source",
        "reply_text": "Thank you. How did you hear about us?",
        "qualification_status": "in_progress",
        "preferred_phone": None}
    validated_data = {**TEXT_VALIDATED_DATA, "message_sid": MESSAGE_SID}
    service = ExtractService(turn_handler=mock_turn_handler)

    first = service.run_turn(validated_data)
    second = service.run_turn(validated_data)

    assert first == second
    mock_turn_handler.assert_called_once()


@patch("apps.qualification.services.extract_service.run_qualification_turn")
def test_cached_message_sid_short_circuits_before_transcription(mock_turn_handler):
    cached_payload = _expected_turn_response()
    cache_turn_response(MESSAGE_SID, cached_payload)
    transcription_service = MagicMock()

    result = ExtractService(
        transcription_service=transcription_service,
        turn_handler=mock_turn_handler,
    ).run_turn({**VOICE_VALIDATED_DATA, "message_sid": MESSAGE_SID})

    assert result == cached_payload
    transcription_service.transcribe.assert_not_called()
    mock_turn_handler.assert_not_called()


@patch("apps.qualification.services.extract_service.run_qualification_turn")
def test_service_exceptions_propagate(mock_turn_handler):
    mock_turn_handler.side_effect = QualificationServiceRequestError()

    with pytest.raises(QualificationServiceRequestError):
        ExtractService(turn_handler=mock_turn_handler).run_turn(TEXT_VALIDATED_DATA)
