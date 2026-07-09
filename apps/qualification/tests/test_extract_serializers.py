"""Tests for extract endpoint DRF serializers."""

from __future__ import annotations

import json
from typing import Any

import pytest

from apps.qualification.api.serializers import ExtractRequestSerializer, ExtractResponseSerializer
from apps.qualification.views import InvalidExtractRequestError, _parse_extract_request

VALID_MESSAGE = "I need a new website for a restaurant"
VALID_WHATSAPP_NUMBER = "+923001234567"
TWILIO_MEDIA_URL = "https://api.twilio.com/2010-04-01/Accounts/ACtest/Media/MEtestvoice001"

N8N_TEXT_PAYLOAD = {
    "message": "I need a website for my bakery",
    "whatsapp_number": "+923246271149",
    "input_channel": "whatsapp_text",
    "message_sid": "SM0cc5a1d9e22bf9850ca24261ee23ce90",
    "media_url": None,
    "media_content_type": None,
}
N8N_VOICE_PAYLOAD = {
    "message": "",
    "whatsapp_number": "+923246271149",
    "input_channel": "whatsapp_voice_note",
    "message_sid": "MM0cc5a1d9e22bf9850ca24261ee23ce90",
    "media_url": (
        "https://api.twilio.com/2010-04-01/Accounts/ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx/"
        "Messages/MM0cc5a1d9e22bf9850ca24261ee23ce90/Media/MEyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy"
    ),
    "media_content_type": "audio/ogg",
}

TEXT_RESPONSE_PAYLOAD = {
    "accepted_fields": {
        "project_type": "new_website",
        "requirements": "website for a restaurant",
    },
    "rejected_fields": {"referral_source": "value_missing"},
    "human_handoff_requested": False,
    "next_field": "referral_source",
    "reply_text": "Thank you. How did you hear about us?",
    "qualification_status": "in_progress",
    "conversation_language": "en",
    "preferred_phone": None,
    "reply_mode": "text",
    "send_booking_link": False,
    "booking_link_sent": False,
    "booking_link": None,
}

VOICE_RESPONSE_PAYLOAD = {
    **TEXT_RESPONSE_PAYLOAD,
    "reply_mode": "voice",
    "transcript": "I need a website for my bakery",
}


def _validated_request(payload: dict[str, Any]) -> dict[str, Any]:
    serializer = ExtractRequestSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors
    return serializer.validated_data


def _parsed_request(payload: dict[str, Any]) -> dict[str, Any]:
    turn_request = _parse_extract_request(json.dumps(payload).encode("utf-8"))
    serializer = ExtractRequestSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors
    validated = serializer.validated_data
    return {
        "whatsapp_number": turn_request.whatsapp_number,
        "message": turn_request.message,
        "input_channel": turn_request.input_channel,
        "message_sid": turn_request.message_sid,
        "media_url": turn_request.media_url,
        "media_content_type": turn_request.media_content_type,
        "button_payload": validated["button_payload"],
        "button_text": validated["button_text"],
        "button_type": validated["button_type"],
        "interactive_data": validated["interactive_data"],
        "channel_metadata": validated["channel_metadata"],
        "call_sid": turn_request.call_sid,
        "utterance_id": turn_request.utterance_id,
        "is_final": turn_request.is_final,
        "event_source": turn_request.event_source,
    }


def _assert_request_parity(payload: dict[str, Any]) -> None:
    try:
        expected = _parsed_request(payload)
    except InvalidExtractRequestError:
        serializer = ExtractRequestSerializer(data=payload)
        assert not serializer.is_valid()
        return

    assert _validated_request(payload) == expected


def test_valid_text_payload_matches_parser():
    payload = {
        "message": VALID_MESSAGE,
        "whatsapp_number": VALID_WHATSAPP_NUMBER,
        "input_channel": "whatsapp_text",
    }
    _assert_request_parity(payload)


def test_valid_n8n_text_payload_matches_parser():
    _assert_request_parity(dict(N8N_TEXT_PAYLOAD))


def test_valid_n8n_voice_payload_matches_parser():
    _assert_request_parity(dict(N8N_VOICE_PAYLOAD))


def test_valid_voice_payload_without_message_matches_parser():
    payload = {
        "whatsapp_number": VALID_WHATSAPP_NUMBER,
        "input_channel": "whatsapp_voice_note",
        "message_sid": "MM0cc5a1d9e22bf9850ca24261ee23ce90",
        "media_url": TWILIO_MEDIA_URL,
        "media_content_type": "audio/ogg",
    }
    _assert_request_parity(payload)


def test_missing_whatsapp_number_is_invalid():
    serializer = ExtractRequestSerializer(
        data={"message": VALID_MESSAGE, "input_channel": "whatsapp_text"},
    )
    assert not serializer.is_valid()


@pytest.mark.parametrize(
    "whatsapp_number",
    ["923001234567", "+0123456789", "+92300", "not-a-phone", 923001234567],
)
def test_invalid_whatsapp_number_is_invalid(whatsapp_number: object):
    serializer = ExtractRequestSerializer(
        data={
            "message": VALID_MESSAGE,
            "whatsapp_number": whatsapp_number,
            "input_channel": "whatsapp_text",
        },
    )
    assert not serializer.is_valid()


@pytest.mark.parametrize("input_channel", ["whatsapp", "WHATSAPP_TEXT", "sms", 123])
def test_invalid_input_channel_is_invalid(input_channel: object):
    serializer = ExtractRequestSerializer(
        data={
            "message": VALID_MESSAGE,
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": input_channel,
        },
    )
    assert not serializer.is_valid()


def test_text_channel_missing_message_is_invalid():
    serializer = ExtractRequestSerializer(data={"whatsapp_number": VALID_WHATSAPP_NUMBER})
    assert not serializer.is_valid()


@pytest.mark.parametrize("message", ["", "   ", "\n\t"])
def test_text_channel_blank_message_is_invalid(message: str):
    serializer = ExtractRequestSerializer(
        data={
            "message": message,
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_text",
        },
    )
    assert not serializer.is_valid()


@pytest.mark.parametrize(
    "payload",
    [
        {
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_voice_note",
            "media_url": None,
            "media_content_type": "audio/ogg",
        },
        {
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_voice_note",
            "media_url": TWILIO_MEDIA_URL,
            "media_content_type": "video/mp4",
        },
        {
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_voice_note",
            "media_url": TWILIO_MEDIA_URL,
            "media_content_type": "audio/ogg",
        },
    ],
)
def test_voice_channel_invalid_media_fields_are_invalid(payload: dict[str, object]):
    serializer = ExtractRequestSerializer(data=payload)
    assert not serializer.is_valid()


@pytest.mark.parametrize(
    "message_sid",
    [
        "MM0cc5a1d9e22bf9850ca24261ee23ce90/../../../etc/passwd",
        "MM<script>alert(1)</script>xxxxxxxxxxxxxx",
        "MMtooshort",
        "XX0cc5a1d9e22bf9850ca24261ee23ce90",
    ],
)
def test_invalid_message_sid_is_invalid(message_sid: str):
    serializer = ExtractRequestSerializer(
        data={
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_voice_note",
            "media_url": TWILIO_MEDIA_URL,
            "media_content_type": "audio/ogg",
            "message_sid": message_sid,
        },
    )
    assert not serializer.is_valid()


@pytest.mark.parametrize(
    "message_sid",
    [
        "SM0cc5a1d9e22bf9850ca24261ee23ce90",
        "MM0cc5a1d9e22bf9850ca24261ee23ce90",
    ],
)
def test_valid_message_sid_values_match_parser(message_sid: str):
    _assert_request_parity(
        {
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_voice_note",
            "media_url": TWILIO_MEDIA_URL,
            "media_content_type": "audio/ogg",
            "message_sid": message_sid,
        },
    )


def test_extra_request_field_is_invalid():
    serializer = ExtractRequestSerializer(
        data={
            "message": VALID_MESSAGE,
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "extra": "field",
        },
    )
    assert not serializer.is_valid()


def test_voice_channel_defaults_missing_media_content_type_to_audio_ogg():
    validated = _validated_request(
        {
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_voice_note",
            "message_sid": "MM0cc5a1d9e22bf9850ca24261ee23ce90",
            "media_url": TWILIO_MEDIA_URL,
        },
    )
    assert validated["media_content_type"] == "audio/ogg"


def test_voice_channel_requires_message_sid_when_media_url_present():
    serializer = ExtractRequestSerializer(
        data={
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_voice_note",
            "media_url": TWILIO_MEDIA_URL,
            "media_content_type": "audio/ogg",
        },
    )
    assert not serializer.is_valid()


def test_media_url_without_input_channel_infers_voice_note():
    validated = _validated_request(
        {
            "message": "",
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "message_sid": "MM0cc5a1d9e22bf9850ca24261ee23ce90",
            "media_url": TWILIO_MEDIA_URL,
        },
    )
    assert validated["input_channel"] == "whatsapp_voice_note"
    assert validated["media_content_type"] == "audio/ogg"


def test_text_channel_ignores_media_fields_in_validated_output():
    validated = _validated_request(
        {
            "message": VALID_MESSAGE,
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_text",
            "media_url": TWILIO_MEDIA_URL,
            "media_content_type": "audio/ogg",
        },
    )
    assert validated["media_url"] is None
    assert validated["media_content_type"] is None


@pytest.mark.parametrize(
    "message_value",
    [
        pytest.param({"message": ""}, id="empty-string"),
        pytest.param({}, id="omitted"),
        pytest.param({"message": None}, id="null"),
        pytest.param({"message": "   "}, id="whitespace"),
    ],
)
def test_voice_channel_blank_or_missing_message_variants_match_parser(message_value: dict):
    payload = {
        "whatsapp_number": VALID_WHATSAPP_NUMBER,
        "input_channel": "whatsapp_voice_note",
        "message_sid": "MM0cc5a1d9e22bf9850ca24261ee23ce90",
        "media_url": TWILIO_MEDIA_URL,
        "media_content_type": "audio/ogg",
    }
    if "message" in message_value:
        payload["message"] = message_value["message"]
    _assert_request_parity(payload)


@pytest.mark.parametrize("payload", [[], "string-root", 123])
def test_non_object_json_root_is_invalid(payload: object):
    serializer = ExtractRequestSerializer(data=payload)
    assert not serializer.is_valid()


def test_text_response_representation_omits_transcript_key():
    data = ExtractResponseSerializer(instance=dict(TEXT_RESPONSE_PAYLOAD)).data
    assert set(data.keys()) == set(TEXT_RESPONSE_PAYLOAD.keys())
    assert "transcript" not in data


def test_voice_response_representation_includes_transcript_key():
    data = ExtractResponseSerializer(instance=dict(VOICE_RESPONSE_PAYLOAD)).data
    assert data["transcript"] == VOICE_RESPONSE_PAYLOAD["transcript"]
    assert set(data.keys()) == set(VOICE_RESPONSE_PAYLOAD.keys())


def test_response_serializer_accepts_text_contract_payload():
    serializer = ExtractResponseSerializer(data=TEXT_RESPONSE_PAYLOAD)
    assert serializer.is_valid(), serializer.errors


def test_response_serializer_accepts_voice_contract_payload_with_transcript():
    serializer = ExtractResponseSerializer(data=VOICE_RESPONSE_PAYLOAD)
    assert serializer.is_valid(), serializer.errors


@pytest.mark.parametrize(
    "payload",
    [
        N8N_TEXT_PAYLOAD,
        N8N_VOICE_PAYLOAD,
        {
            "message": VALID_MESSAGE,
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_text",
        },
        {
            "whatsapp_number": VALID_WHATSAPP_NUMBER,
            "input_channel": "whatsapp_voice_note",
            "message_sid": "MM0cc5a1d9e22bf9850ca24261ee23ce90",
            "media_url": TWILIO_MEDIA_URL,
            "media_content_type": "audio/ogg",
        },
    ],
)
def test_parser_parity_for_existing_contract_payloads(payload: dict[str, Any]):
    _assert_request_parity(payload)


def test_extract_serializer_accepts_optional_button_fields():
    payload = {
        "message": "English",
        "whatsapp_number": VALID_WHATSAPP_NUMBER,
        "input_channel": "whatsapp_text",
        "message_sid": "SM0cc5a1d9e22bf9850ca24261ee23ce90",
        "button_payload": "lang_en",
        "button_text": "English",
        "button_type": "quick_reply",
    }
    validated = _validated_request(payload)
    assert validated["button_payload"] == "lang_en"
    assert validated["button_text"] == "English"
    assert validated["button_type"] == "quick_reply"


def test_extract_serializer_rejects_unknown_fields_with_button_payload_present():
    payload = {
        "message": VALID_MESSAGE,
        "whatsapp_number": VALID_WHATSAPP_NUMBER,
        "input_channel": "whatsapp_text",
        "button_payload": "lang_en",
        "unexpected": "value",
    }
    serializer = ExtractRequestSerializer(data=payload)
    assert not serializer.is_valid()
