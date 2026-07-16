"""Tests for Twilio inbound DRF serializer validation."""

from __future__ import annotations

import pytest

from apps.webhooks.serializers import TwilioInboundSerializer

STANDARD_TEXT_PARAMS = {
    "MessageSid": "SM0cc5a1d9e22bf9850ca24261ee23ce90",
    "From": "whatsapp:+15551234567",
    "Body": "Hello from customer",
    "NumMedia": "0",
}

QUICK_REPLY_PARAMS = {
    **STANDARD_TEXT_PARAMS,
    "Body": "English",
    "ButtonPayload": "lang_en",
    "ButtonText": "English",
    "ButtonType": "quick_reply",
}

VOICE_NOTE_PARAMS = {
    "MessageSid": "MM0cc5a1d9e22bf9850ca24261ee23ce90",
    "From": "whatsapp:+15551234567",
    "Body": "",
    "NumMedia": "1",
    "MediaUrl0": "https://api.twilio.com/2010-04-01/Accounts/ACtest/Media/MEvoice001",
}


def test_standard_text_message_validates_without_button_fields():
    serializer = TwilioInboundSerializer(data=STANDARD_TEXT_PARAMS)
    assert serializer.is_valid(), serializer.errors
    assert serializer.button_payload is None


def test_quick_reply_message_validates_with_button_fields():
    serializer = TwilioInboundSerializer(data=QUICK_REPLY_PARAMS)
    assert serializer.is_valid(), serializer.errors
    assert serializer.button_payload == "lang_en"
    assert serializer.validated_data["ButtonText"] == "English"
    assert serializer.validated_data["ButtonType"] == "quick_reply"


def test_voice_note_message_validates_with_media_fields():
    serializer = TwilioInboundSerializer(data=VOICE_NOTE_PARAMS)
    assert serializer.is_valid(), serializer.errors
    extract_payload = serializer.to_extract_request_payload()
    assert extract_payload["input_channel"] == "whatsapp_voice_note"
    assert extract_payload["media_url"] == VOICE_NOTE_PARAMS["MediaUrl0"]
    assert extract_payload["message_sid"] == VOICE_NOTE_PARAMS["MessageSid"]


def test_message_sid_and_from_remain_required():
    serializer = TwilioInboundSerializer(data={"Body": "Hi"})
    assert not serializer.is_valid()
    assert "MessageSid" in serializer.errors
    assert "From" in serializer.errors
