"""Tests for render-audio DRF serializers."""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import override_settings

from apps.qualification.api.serializers import RenderAudioRequestSerializer, RenderAudioResponseSerializer
from apps.qualification.render_audio_views import _parse_render_audio_request
from apps.qualification.whatsapp_audio import InvalidRenderAudioRequestError

VALID_TEXT = "Thank you. How did you hear about us?"
VALID_PAYLOAD = {
    "text": VALID_TEXT,
    "voice": "F1",
    "lang": "en",
    "request_id": "SM_TEST_001"}

SUCCESS_RESPONSE = {
    "status": "rendered",
    "fallback_to_text": False,
    "conversation_language": "en",
    "media_url": "https://tunnel.example.com/media/whatsapp_voice_replies/00000000-0000-4000-8000-000000000001/",
    "content_type": "audio/ogg",
    "audio_url": "https://tunnel.example.com/media/whatsapp_voice_replies/00000000-0000-4000-8000-000000000001/",
    "audio_content_type": "audio/ogg",
    "request_id": "SM_TEST_001"}


def _validated_request(payload: dict[str, Any]) -> dict[str, Any]:
    serializer = RenderAudioRequestSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors
    return serializer.validated_data


def _parsed_request(payload: dict[str, Any]) -> dict[str, Any]:
    return _parse_render_audio_request(json.dumps(payload).encode("utf-8"))


def _assert_http_shape_parity(payload: dict[str, Any]) -> None:
    try:
        expected = _parsed_request(payload)
    except InvalidRenderAudioRequestError:
        serializer = RenderAudioRequestSerializer(data=payload)
        assert not serializer.is_valid()
        return

    validated = _validated_request(payload)
    assert validated["text"] == payload["text"]
    assert validated["voice"] == expected["voice"]
    assert validated["lang"] == expected["lang"]
    assert validated["request_id"] == expected["request_id"]


def test_valid_payload_matches_parser_shape():
    _assert_http_shape_parity(dict(VALID_PAYLOAD))


def test_minimal_valid_payload_with_defaults():
    payload = {"text": VALID_TEXT}
    validated = _validated_request(payload)
    assert validated["voice"] == "F1"
    assert validated["lang"] == "en"
    assert validated["request_id"] is None


def test_missing_text_is_invalid():
    serializer = RenderAudioRequestSerializer(data={"voice": "F1", "lang": "en"})
    assert not serializer.is_valid()


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_blank_text_passes_serializer_but_not_parser(text: str):
    serializer = RenderAudioRequestSerializer(data={"text": text})
    assert serializer.is_valid()
    with pytest.raises(InvalidRenderAudioRequestError):
        _parse_render_audio_request(json.dumps({"text": text}).encode("utf-8"))


@pytest.mark.parametrize("voice", ["", "   ", 123, None])
def test_invalid_voice_is_invalid(voice: object):
    serializer = RenderAudioRequestSerializer(data={"text": VALID_TEXT, "voice": voice})
    assert not serializer.is_valid()


@pytest.mark.parametrize("lang", ["", "   ", 123, None])
def test_invalid_lang_is_invalid(lang: object):
    serializer = RenderAudioRequestSerializer(data={"text": VALID_TEXT, "lang": lang})
    assert not serializer.is_valid()


@pytest.mark.parametrize("request_id", ["", "   ", "bad/id", 123])
def test_invalid_request_id_is_invalid(request_id: object):
    serializer = RenderAudioRequestSerializer(
        data={"text": VALID_TEXT, "request_id": request_id},
    )
    assert not serializer.is_valid()


def test_null_request_id_is_valid():
    validated = _validated_request({"text": VALID_TEXT, "request_id": None})
    assert validated["request_id"] is None


def test_omitted_request_id_is_valid():
    validated = _validated_request({"text": VALID_TEXT})
    assert validated["request_id"] is None


def test_extra_field_is_invalid():
    serializer = RenderAudioRequestSerializer(data={**VALID_PAYLOAD, "extra": "field"})
    assert not serializer.is_valid()


def test_non_string_text_is_invalid():
    serializer = RenderAudioRequestSerializer(data={"text": 123})
    assert not serializer.is_valid()


@override_settings(MAX_TTS_TEXT_LENGTH=10)
def test_request_serializer_does_not_validate_text_length():
    long_text = "this text is definitely too long for tts"
    serializer = RenderAudioRequestSerializer(data={"text": long_text, "voice": "F1", "lang": "en"})
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["text"] == long_text


def test_whatsapp_number_field_is_optional_and_validated():
    validated = _validated_request(
        {
            "text": VALID_TEXT,
            "whatsapp_number": "+923001234567",
            "conversation_language": "ar"},
    )
    assert validated["whatsapp_number"] == "+923001234567"
    assert validated["conversation_language"] == "ar"


def test_invalid_whatsapp_number_is_invalid():
    serializer = RenderAudioRequestSerializer(
        data={"text": VALID_TEXT, "whatsapp_number": "not-a-phone"},
    )
    assert not serializer.is_valid()


def test_response_serializer_success_payload_key_set():
    data = RenderAudioResponseSerializer(instance=dict(SUCCESS_RESPONSE)).data
    assert set(data.keys()) == {
        "status",
        "fallback_to_text",
        "conversation_language",
        "media_url",
        "content_type",
        "audio_url",
        "audio_content_type",
        "request_id"}


def test_response_serializer_accepts_success_payload():
    serializer = RenderAudioResponseSerializer(data=SUCCESS_RESPONSE)
    assert serializer.is_valid(), serializer.errors


def test_response_serializer_accepts_null_request_id():
    serializer = RenderAudioResponseSerializer(data=dict(SUCCESS_RESPONSE, request_id=None))
    assert serializer.is_valid(), serializer.errors


def test_response_serializer_instance_preserves_null_request_id():
    data = RenderAudioResponseSerializer(
        instance=dict(SUCCESS_RESPONSE, request_id=None),
    ).data
    assert data["request_id"] is None
