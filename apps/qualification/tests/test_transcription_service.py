"""Tests for VoiceNoteTranscriptionService."""

from __future__ import annotations

import urllib.error
from unittest.mock import ANY, MagicMock, patch

import pytest

from apps.qualification.deepgram_client import (
    DeepgramConfigurationError,
    DeepgramRequestError,
    DeepgramResponseError,
    DeepgramTimeoutError,
)
from apps.qualification.tests.internal_api_test_helpers import (
    MOCK_VOICE_AUDIO_BYTES,
    MOCK_VOICE_AUDIO_DOWNLOAD,
)
from apps.qualification.domain.extract_errors import ExtractStepFailure
from apps.qualification.services.transcription_service import (
    VoiceNoteTranscriptionService,
    clear_transcription_media_cache,
)
from apps.qualification.twilio_media import (
    TwilioMediaConfigurationError,
    TwilioMediaRequestError,
    TwilioMediaTimeoutError,
    TwilioMediaUnauthorizedError,
)
from apps.qualification.voice_note_config import VoiceNoteConfigurationError

MEDIA_URL = "https://api.twilio.com/2010-04-01/Accounts/ACtest/Media/MEtestvoice001"
MESSAGE_SID = "MM0cc5a1d9e22bf9850ca24261ee23ce90"
MEDIA_CONTENT_TYPE = "audio/ogg"
TRANSCRIPT = "I need a website for my bakery"


@pytest.fixture(autouse=True)
def _clear_media_cache():
    clear_transcription_media_cache()
    yield
    clear_transcription_media_cache()


def test_transcribe_downloads_and_returns_normalized_transcript():
    media_downloader = MagicMock(return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
    transcription_client = MagicMock(return_value=TRANSCRIPT)

    transcript = VoiceNoteTranscriptionService(
        media_downloader=media_downloader,
        transcription_client=transcription_client,
        dependency_validator=lambda: None,
    ).transcribe(
        media_url=MEDIA_URL,
        media_content_type=MEDIA_CONTENT_TYPE,
        message_sid=MESSAGE_SID,
        conversation_language="en",
    )

    assert transcript == TRANSCRIPT
    media_downloader.assert_called_once_with(MEDIA_URL)
    transcription_client.assert_called_once_with(
        MOCK_VOICE_AUDIO_BYTES,
        content_type=MEDIA_CONTENT_TYPE,
        transcription_config=ANY,
    )


@pytest.mark.parametrize(
    "error,expected_type",
    [
        (TwilioMediaUnauthorizedError("unauthorized"), ExtractStepFailure),
        (TwilioMediaTimeoutError("timeout"), ExtractStepFailure),
        (TwilioMediaRequestError("failed"), ExtractStepFailure),
    ],
)
def test_media_download_failures_propagate(error, expected_type):
    media_downloader = MagicMock(side_effect=error)

    with pytest.raises(expected_type):
        VoiceNoteTranscriptionService(
            media_downloader=media_downloader,
            transcription_client=MagicMock(),
            dependency_validator=lambda: None,
        ).transcribe(
            media_url=MEDIA_URL,
            media_content_type=MEDIA_CONTENT_TYPE,
            message_sid=MESSAGE_SID,
        )


@pytest.mark.parametrize(
    "error,expected_type",
    [
        (DeepgramTimeoutError("timeout"), ExtractStepFailure),
        (DeepgramRequestError("failed"), ExtractStepFailure),
        (DeepgramResponseError("empty transcript"), ExtractStepFailure),
    ],
)
def test_deepgram_failures_propagate(error, expected_type):
    with pytest.raises(expected_type):
        VoiceNoteTranscriptionService(
            media_downloader=MagicMock(return_value=MOCK_VOICE_AUDIO_DOWNLOAD),
            transcription_client=MagicMock(side_effect=error),
            dependency_validator=lambda: None,
        ).transcribe(
            media_url=MEDIA_URL,
            media_content_type=MEDIA_CONTENT_TYPE,
            message_sid=MESSAGE_SID,
        )


def test_missing_twilio_credentials_maps_to_twilio_configuration_error():
    dependency_validator = MagicMock(
        side_effect=VoiceNoteConfigurationError(
            log_event="qualification_voice_missing_twilio_credentials",
            message="Twilio credentials missing",
        ),
    )

    with pytest.raises(TwilioMediaConfigurationError):
        VoiceNoteTranscriptionService(
            media_downloader=MagicMock(),
            transcription_client=MagicMock(),
            dependency_validator=dependency_validator,
        ).transcribe(
            media_url=MEDIA_URL,
            media_content_type=MEDIA_CONTENT_TYPE,
            message_sid=MESSAGE_SID,
        )


def test_missing_deepgram_configuration_maps_to_deepgram_configuration_error():
    dependency_validator = MagicMock(
        side_effect=VoiceNoteConfigurationError(
            log_event="qualification_voice_missing_deepgram_api_key",
            message="Deepgram API key missing",
        ),
    )

    with pytest.raises(DeepgramConfigurationError):
        VoiceNoteTranscriptionService(
            media_downloader=MagicMock(),
            transcription_client=MagicMock(),
            dependency_validator=dependency_validator,
        ).transcribe(
            media_url=MEDIA_URL,
            media_content_type=MEDIA_CONTENT_TYPE,
            message_sid=MESSAGE_SID,
        )


@patch("apps.qualification.services.transcription_service.log_voice_note_event")
def test_transcribe_returns_plain_string_not_http_response(mock_log_event):
    transcript = VoiceNoteTranscriptionService(
        media_downloader=MagicMock(return_value=MOCK_VOICE_AUDIO_DOWNLOAD),
        transcription_client=MagicMock(return_value=TRANSCRIPT),
        dependency_validator=lambda: None,
    ).transcribe(
        media_url=MEDIA_URL,
        media_content_type=MEDIA_CONTENT_TYPE,
        message_sid=MESSAGE_SID,
        conversation_language="en",
    )

    assert isinstance(transcript, str)
    assert transcript == TRANSCRIPT


@patch("apps.qualification.services.transcription_service.log_voice_note_event")
def test_transcribe_does_not_return_provider_secrets_in_transcript(mock_log_event):
    transcript = VoiceNoteTranscriptionService(
        media_downloader=MagicMock(return_value=MOCK_VOICE_AUDIO_DOWNLOAD),
        transcription_client=MagicMock(return_value=TRANSCRIPT),
        dependency_validator=lambda: None,
    ).transcribe(
        media_url=MEDIA_URL,
        media_content_type=MEDIA_CONTENT_TYPE,
        message_sid=MESSAGE_SID,
        conversation_language="en",
    )

    assert transcript == TRANSCRIPT
    for call in mock_log_event.call_args_list:
        assert TRANSCRIPT not in str(call)
        assert MEDIA_URL not in str(call)


@patch("apps.qualification.services.transcription_service.log_latency_step")
def test_transcribe_logs_direct_audio_bytes_with_twilio_content_type(mock_log_step):
    media_downloader = MagicMock(return_value=(MOCK_VOICE_AUDIO_BYTES, "audio/ogg; codecs=opus"))
    transcription_client = MagicMock(return_value=TRANSCRIPT)

    VoiceNoteTranscriptionService(
        media_downloader=media_downloader,
        transcription_client=transcription_client,
        dependency_validator=lambda: None,
    ).transcribe(
        media_url=MEDIA_URL,
        media_content_type="audio/ogg",
        message_sid=MESSAGE_SID,
    )

    transcription_client.assert_called_once_with(
        MOCK_VOICE_AUDIO_BYTES,
        content_type="audio/ogg",
        transcription_config=ANY,
    )
    deepgram_log = next(
        call for call in mock_log_step.call_args_list if call.args[0] == "deepgram_transcription"
    )
    assert deepgram_log.kwargs["direct_audio_bytes"] is True
    assert deepgram_log.kwargs["media_content_type"] == "audio/ogg"
    assert deepgram_log.kwargs["status"] == "success"
