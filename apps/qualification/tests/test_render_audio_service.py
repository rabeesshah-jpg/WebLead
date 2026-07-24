"""Tests for RenderAudioService."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from apps.qualification.domain.messages import get_customer_message
from apps.qualification.render_audio_idempotency import clear_render_audio_cache
from apps.qualification.services.render_audio_service import RenderAudioService
from apps.qualification.whatsapp_audio import (
    InvalidRenderAudioRequestError,
    RenderAudioProcessingError,
    RenderAudioServiceUnavailableError,
)

PUBLIC_MEDIA_BASE_URL = "https://tunnel.example.com"
MEDIA_URL = f"{PUBLIC_MEDIA_BASE_URL}/media/whatsapp_voice_replies/00000000-0000-4000-8000-000000000001/"

VALIDATED_DATA = {
    "text": "Thank you. How did you hear about us?",
    "voice": "F1",
    "lang": "en",
    "request_id": "SM_TEST_001",
    "whatsapp_number": None,
    "conversation_language": None}


@pytest.fixture(autouse=True)
def _reset_render_cache():
    clear_render_audio_cache()
    yield
    clear_render_audio_cache()


@override_settings(PUBLIC_MEDIA_BASE_URL=PUBLIC_MEDIA_BASE_URL, MAX_TTS_TEXT_LENGTH=800)
def test_render_calls_renderer_with_configured_english_voice_and_returns_contract_payload():
    renderer = MagicMock(return_value=MEDIA_URL)

    result = RenderAudioService(renderer=renderer).render(
        {**VALIDATED_DATA, "text": "  Hello there  "},
    )

    renderer.assert_called_once_with(text="Hello there", voice="F1", lang="en")
    assert result["status"] == "rendered"
    assert result["fallback_to_text"] is False
    assert result["conversation_language"] == "en"
    assert result["media_url"] == MEDIA_URL
    assert result["audio_url"] == MEDIA_URL
    assert result["content_type"] == "audio/ogg"
    assert result["request_id"] == "SM_TEST_001"


@override_settings(MAX_TTS_TEXT_LENGTH=800)
def test_blank_text_returns_skipped_empty_without_renderer():
    renderer = MagicMock()
    result = RenderAudioService(renderer=renderer).render({**VALIDATED_DATA, "text": "   "})
    assert result["status"] == "skipped_empty"
    assert result["media_url"] is None
    renderer.assert_not_called()


@override_settings(MAX_TTS_TEXT_LENGTH=800)
def test_render_audio_sanitizes_onboarding_copy_before_tts():
    renderer = MagicMock(return_value=MEDIA_URL)
    long_onboarding = get_customer_message(language="en", key="onboarding_intro")
    safe_voice = get_customer_message(language="en", key="onboarding_intro_voice")

    result = RenderAudioService(renderer=renderer).render(
        {**VALIDATED_DATA, "text": long_onboarding, "conversation_language": "en"},
    )

    renderer.assert_called_once_with(text=safe_voice, voice="F1", lang="en")
    assert result["status"] == "rendered"
    assert "To open the menu" not in renderer.call_args.kwargs["text"]


@override_settings(MAX_TTS_TEXT_LENGTH=10)
def test_excessive_text_raises_invalid_request_error():
    with pytest.raises(InvalidRenderAudioRequestError):
        RenderAudioService(renderer=MagicMock()).render(
            {**VALIDATED_DATA, "text": "this text is definitely too long"},
        )


@override_settings(MAX_TTS_TEXT_LENGTH=800)
def test_service_unavailable_error_returns_english_text_fallback():
    renderer = MagicMock(side_effect=RenderAudioServiceUnavailableError())

    result = RenderAudioService(renderer=renderer).render(VALIDATED_DATA)

    assert result["status"] == "text_fallback"
    assert result["fallback_to_text"] is True
    assert result["fallback_reason"] == "english_tts_unavailable"


@override_settings(MAX_TTS_TEXT_LENGTH=800)
def test_processing_error_returns_english_text_fallback():
    renderer = MagicMock(side_effect=RenderAudioProcessingError())

    result = RenderAudioService(renderer=renderer).render(VALIDATED_DATA)

    assert result["fallback_to_text"] is True
    assert result["fallback_reason"] == "english_tts_unavailable"


@override_settings(MAX_TTS_TEXT_LENGTH=800, SUPERTONIC_ARABIC_ENABLED=False, SUPERTONIC_ARABIC_VOICE="M1")
@patch(
    "apps.qualification.services.render_audio_service.get_conversation_language",
    return_value="ar",
)
def test_arabic_disabled_config_returns_text_fallback_without_renderer(mock_language):
    renderer = MagicMock()

    result = RenderAudioService(renderer=renderer).render(
        {
            **VALIDATED_DATA,
            "whatsapp_number": "+923001234567"},
    )

    renderer.assert_not_called()
    assert result["fallback_to_text"] is True
    assert result["fallback_reason"] == "arabic_tts_unavailable"
    assert result["conversation_language"] == "ar"


def test_service_does_not_return_http_response_objects():
    renderer = MagicMock(return_value=MEDIA_URL)

    result = RenderAudioService(renderer=renderer).render(VALIDATED_DATA)

    assert isinstance(result, dict)
    assert "error" not in result
