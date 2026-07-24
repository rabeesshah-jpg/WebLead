"""Tests for booking completion reply text in extract responses."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import Client, override_settings

from apps.qualification.channels import (
    apply_outbound_channel_routing,
    finalize_turn_response,
)
from apps.qualification.conversation_state import clear_conversations, save_accepted_fields
from apps.qualification.domain.booking_completion import (
    build_booking_completion_reply,
    build_booking_link_message_body,
    resolve_booking_link,
)
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.models import QualificationFieldFilterResult
from apps.qualification.tests.internal_api_test_helpers import API_SECRET, internal_api_auth_headers

BOOKING_LINK = "https://booking.example.com/test-schedule"
ENDPOINT_PATH = "/api/internal/qualification/extract/"
WHATSAPP_NUMBER = "+923001234567"
BOOKING_REPLY_TEXT = get_customer_message(
    language="en",
    key="completion_with_booking_link",
    booking_link=BOOKING_LINK,
)


@override_settings(BOOKING_LINK=BOOKING_LINK)
def test_resolve_booking_link_reads_from_settings():
    assert resolve_booking_link() == BOOKING_LINK


def test_build_booking_link_message_body_includes_link():
    body = build_booking_link_message_body(language="en", booking_link=BOOKING_LINK)

    assert body == get_customer_message(
        language="en",
        key="completion_with_booking_link",
        booking_link=BOOKING_LINK,
    )
    assert BOOKING_LINK in body
    assert "Perfect, thank you" in body


def test_build_booking_completion_reply_puts_link_in_single_reply_text():
    result = build_booking_completion_reply(
        language="en",
        booking_link=BOOKING_LINK,
    )

    assert result["booking_link_sent"] is True
    assert result["send_booking_link"] is False
    assert result["booking_link"] == BOOKING_LINK
    assert result["reply_text"] == BOOKING_REPLY_TEXT
    assert BOOKING_LINK in result["reply_text"]
    assert BOOKING_LINK not in result["spoken_text"]
    assert BOOKING_LINK in str(result["whatsapp_text"])
    assert "I will send you a booking link" not in result["reply_text"]
    assert (
        "Perfect, thank you" in str(result["spoken_text"])
        and "booking link above" in str(result["spoken_text"]).lower()
    )


def test_build_booking_completion_reply_falls_back_when_link_missing():
    result = build_booking_completion_reply(language="en", booking_link="")

    assert result["booking_link_sent"] is False
    assert result["send_booking_link"] is False
    assert result["booking_link"] is None
    assert result["reply_text"] == get_customer_message(
        language="en",
        key="completion_pending_booking_link",
    )


@override_settings(BOOKING_LINK=BOOKING_LINK)
def test_apply_outbound_channel_routing_voice_in_progress_is_audio_only():
    routed = apply_outbound_channel_routing(
        {
            "conversation_language": "en",
            "reply_text": "May I know what type of website help you need?",
            "spoken_text": "May I know what type of website help you need?",
            "qualification_status": "in_progress"},
        input_channel="whatsapp_voice_note",
    )

    assert routed["should_send_audio"] is True
    assert routed["should_send_text"] is False
    assert routed["whatsapp_text"] == ""
    assert routed["reply_text"] == routed["spoken_text"]


@override_settings(BOOKING_LINK=BOOKING_LINK)
def test_apply_outbound_channel_routing_voice_first_booking_keeps_url_in_reply_text():
    spoken = get_customer_message(language="en", key="completion_spoken")
    text_with_link = get_customer_message(
        language="en",
        key="completion_with_booking_link",
        booking_link=BOOKING_LINK,
    )
    routed = apply_outbound_channel_routing(
        {
            "conversation_language": "en",
            "reply_text": text_with_link,
            "spoken_text": spoken,
            "whatsapp_text": text_with_link,
            "qualification_status": "completed",
            "send_booking_link": True,
            "booking_link_sent": True},
        input_channel="whatsapp_voice_note",
    )

    assert routed["reply_text"] == text_with_link
    assert BOOKING_LINK in routed["reply_text"]
    assert routed["spoken_text"] == spoken
    assert BOOKING_LINK not in routed["spoken_text"]
    assert routed["whatsapp_text"] == text_with_link
    assert routed["should_send_text"] is True
    assert routed["should_send_audio"] is True
    assert routed["contains_booking_link"] is True


@override_settings(BOOKING_LINK=BOOKING_LINK)
@pytest.mark.django_db
def test_finalize_turn_response_returns_single_reply_text_with_booking_link():
    finalized = finalize_turn_response(
        {
            "accepted_fields": {"project_type": "new_website"},
            "rejected_fields": {},
            "human_handoff_requested": False,
            "next_field": None,
            "reply_text": "legacy completion text",
            "qualification_status": "completed",
            "preferred_phone": WHATSAPP_NUMBER},
        input_channel="whatsapp_text",
        conversation_language="en",
        whatsapp_number=WHATSAPP_NUMBER,
    )

    assert finalized["accepted_fields"] == {"project_type": "new_website"}
    assert finalized["reply_mode"] == "text"
    assert finalized["conversation_language"] == "en"
    assert finalized["send_booking_link"] is True
    assert finalized["booking_link_sent"] is True
    assert finalized["booking_link"] == BOOKING_LINK
    assert finalized["reply_text"] == BOOKING_REPLY_TEXT
    assert BOOKING_LINK in finalized["reply_text"]
    assert BOOKING_LINK not in finalized["spoken_text"]
    assert "I will send you a booking link" not in finalized["reply_text"]
    assert finalized["should_send_text"] is True
    assert finalized["should_send_audio"] is False


@override_settings(BOOKING_LINK=BOOKING_LINK)
@pytest.mark.django_db
def test_finalize_voice_completion_speaks_without_url_and_sets_whatsapp_text():
    finalized = finalize_turn_response(
        {
            "accepted_fields": {"project_type": "new_website"},
            "rejected_fields": {},
            "human_handoff_requested": False,
            "next_field": None,
            "reply_text": "legacy completion text",
            "qualification_status": "completed",
            "preferred_phone": WHATSAPP_NUMBER},
        input_channel="whatsapp_voice_note",
        conversation_language="en",
        whatsapp_number=WHATSAPP_NUMBER,
    )

    assert finalized["reply_mode"] == "voice"
    assert BOOKING_LINK not in finalized["spoken_text"]
    assert BOOKING_LINK in finalized["reply_text"]
    assert finalized["reply_text"] == BOOKING_REPLY_TEXT
    assert finalized["spoken_text"] == get_customer_message(
        language="en",
        key="completion_spoken",
    )
    assert BOOKING_LINK in finalized["whatsapp_text"]
    assert finalized["send_booking_link"] is True
    assert finalized["booking_link_sent"] is True
    assert finalized["should_send_text"] is True
    assert finalized["should_send_audio"] is True
    assert finalized["contains_booking_link"] is True
    assert finalized["actions"] == []


@pytest.mark.django_db
@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_completed_extract_returns_single_reply_text_containing_booking_link(
    mock_extract,
    mock_twilio_booking_link_send,
    client,
):
    clear_conversations()
    clear_message_sid_cache()
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "project_type": "new_website",
            "requirements": "I need a new website for my restaurant",
            "referral_source": "Facebook"},
    )

    response = client.post(
        ENDPOINT_PATH,
        data={
            "message": "Yes",
            "whatsapp_number": WHATSAPP_NUMBER,
            "input_channel": "whatsapp_text",
            "message_sid": "SM0cc5a1d9e22bf9850ca24261ee23ce93"},
        content_type="application/json",
        **internal_api_auth_headers(),
    )

    body = response.json()
    assert body["qualification_status"] == "completed"
    assert body["accepted_fields"]["whatsapp_confirmed"] is True
    assert isinstance(body["reply_text"], str)
    assert body["reply_text"] == BOOKING_REPLY_TEXT
    assert BOOKING_LINK in body["reply_text"]
    assert "I will send you a booking link" not in body["reply_text"]
    assert body["send_booking_link"] is True
    assert body["booking_link_sent"] is True
    assert body["booking_link"] == BOOKING_LINK
    mock_twilio_booking_link_send.assert_not_called()
    mock_extract.assert_not_called()


@pytest.mark.django_db
@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK="")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_completed_extract_response_uses_fallback_when_booking_link_missing(mock_extract, client):
    clear_conversations()
    clear_message_sid_cache()
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "project_type": "new_website",
            "requirements": "I need a new website for my restaurant",
            "referral_source": "Facebook"},
    )

    response = client.post(
        ENDPOINT_PATH,
        data={
            "message": "Yes",
            "whatsapp_number": WHATSAPP_NUMBER,
            "input_channel": "whatsapp_text",
            "message_sid": "SM0cc5a1d9e22bf9850ca24261ee23ce94"},
        content_type="application/json",
        **internal_api_auth_headers(),
    )

    body = response.json()
    assert body["qualification_status"] == "completed"
    assert body["booking_link_sent"] is False
    assert body["send_booking_link"] is False
    assert body["booking_link"] is None
    assert body["reply_text"] == get_customer_message(
        language="en",
        key="completion_pending_booking_link",
    )
    mock_extract.assert_not_called()


@override_settings(BOOKING_LINK=BOOKING_LINK)
@pytest.mark.django_db
def test_first_booking_completion_voice_reply_text_includes_url_spoken_text_does_not():
    """Voice completion must expose the URL in reply_text for n8n text send."""
    for index, input_channel in enumerate(("whatsapp_text", "whatsapp_voice_note")):
        number = f"+92300123456{index}"
        finalized = finalize_turn_response(
            {
                "accepted_fields": {"project_type": "new_website"},
                "rejected_fields": {},
                "human_handoff_requested": False,
                "next_field": None,
                "reply_text": "legacy completion text",
                "qualification_status": "completed",
                "preferred_phone": number},
            input_channel=input_channel,
            conversation_language="en",
            whatsapp_number=number,
        )

        assert BOOKING_LINK in finalized["reply_text"]
        assert BOOKING_LINK not in finalized["spoken_text"]
        assert finalized["send_booking_link"] is True
        assert finalized["contains_booking_link"] is True
        if input_channel == "whatsapp_voice_note":
            assert "booking link above" in finalized["spoken_text"].lower()
            assert "booking link above" not in finalized["reply_text"].lower()


@override_settings(BOOKING_LINK=BOOKING_LINK)
@pytest.mark.django_db
def test_post_booking_completion_blocks_url_resend_for_text_and_voice():
    from apps.qualification.models import WhatsAppConversationSession
    from apps.qualification.services.conversation_session_service import mark_booking_link_sent

    session, _ = WhatsAppConversationSession.objects.get_or_create(
        whatsapp_number=WHATSAPP_NUMBER,
        defaults={"language": "en"},
    )
    mark_booking_link_sent(session=session)

    for input_channel in ("whatsapp_text", "whatsapp_voice_note"):
        finalized = finalize_turn_response(
            {
                "accepted_fields": {"project_type": "new_website"},
                "rejected_fields": {},
                "human_handoff_requested": False,
                "next_field": None,
                "reply_text": "legacy completion text",
                "qualification_status": "completed",
                "preferred_phone": WHATSAPP_NUMBER},
            input_channel=input_channel,
            conversation_language="en",
            whatsapp_number=WHATSAPP_NUMBER,
            user_message="Send link again",
        )

        assert BOOKING_LINK not in finalized["reply_text"]
        assert finalized["send_booking_link"] is False
        assert finalized["contains_booking_link"] is False
        assert finalized["booking_link_sent"] is True
        if input_channel == "whatsapp_voice_note":
            assert finalized["should_send_text"] is False
            assert finalized["whatsapp_text"] == ""
