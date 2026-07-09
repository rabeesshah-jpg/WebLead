"""Tests for WhatsApp voice-note configuration and failure handling."""

from __future__ import annotations

import json
import logging
import socket
import urllib.error
from io import BytesIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, override_settings

from apps.qualification.deepgram_client import (
    DeepgramRequestError,
    DeepgramResponseError,
    DeepgramTimeoutError,
)
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.openrouter_client import OpenRouterConfigurationError
from apps.qualification.persistence.cache_backend import reset_qualification_cache_backend_for_tests
from apps.qualification.services.transcription_service import clear_transcription_media_cache
from apps.qualification.tests.internal_api_test_helpers import (
    MOCK_VOICE_AUDIO_BYTES,
    MOCK_VOICE_AUDIO_DOWNLOAD,
    internal_api_auth_headers,
)
from apps.qualification.tests.test_internal_extract_endpoint import (
    N8N_VOICE_PAYLOAD,
    SAMPLE_FILTER_RESULT,
    VOICE_TRANSCRIPT,
    _voice_payload,
)
from apps.qualification.twilio_media import (
    TwilioMediaConfigurationError,
    TwilioMediaRequestError,
    TwilioMediaTimeoutError,
    TwilioMediaUnauthorizedError,
)
from apps.qualification.models import WhatsAppConversationSession
from apps.qualification.voice_note_config import get_voice_note_config_report

pytestmark = pytest.mark.django_db

EXTRACT_ENDPOINT = "/api/internal/qualification/extract/"
VOICE_WHATSAPP_NUMBER = "+923246271149"


@pytest.fixture(autouse=True)
def _voice_note_english_session():
    from django.utils import timezone

    WhatsAppConversationSession.objects.update_or_create(
        whatsapp_number=VOICE_WHATSAPP_NUMBER,
        defaults={
            "language": "en",
            "language_selected_at": timezone.now(),
        },
    )
    yield
    WhatsAppConversationSession.objects.filter(whatsapp_number=VOICE_WHATSAPP_NUMBER).delete()


@pytest.fixture(autouse=True)
def _reset_voice_note_test_state():
    clear_message_sid_cache()
    clear_transcription_media_cache()
    reset_qualification_cache_backend_for_tests()
    yield
    clear_message_sid_cache()
    clear_transcription_media_cache()
    reset_qualification_cache_backend_for_tests()


@pytest.fixture
def client() -> Client:
    return Client()


def _post_voice(client: Client, payload: dict | None = None) -> object:
    body = json.dumps(payload or dict(N8N_VOICE_PAYLOAD))
    return client.post(
        EXTRACT_ENDPOINT,
        data=body,
        content_type="application/json",
        **internal_api_auth_headers(),
    )


@override_settings(
    N8N_QUALIFICATION_API_SECRET="test-n8n-qualification-api-secret",
    TWILIO_ACCOUNT_SID="",
    TWILIO_AUTH_TOKEN="test-twilio-auth-token",
    DEEPGRAM_API_KEY="test-deepgram-api-key",
)
def test_missing_twilio_account_sid_returns_503_and_logs_event(client, caplog):
    with caplog.at_level(logging.ERROR, logger="apps.qualification"):
        response = _post_voice(client)

    assert response.status_code == 503
    assert response.json() == {"error": "Qualification service is unavailable."}
    assert "qualification_voice_missing_twilio_credentials" in caplog.text


@override_settings(
    N8N_QUALIFICATION_API_SECRET="test-n8n-qualification-api-secret",
    TWILIO_ACCOUNT_SID="ACtesttwilioaccountsidthirtyfour",
    TWILIO_AUTH_TOKEN="test-twilio-auth-token",
    DEEPGRAM_API_KEY="",
)
def test_missing_deepgram_api_key_returns_503_and_logs_event(client, caplog):
    with caplog.at_level(logging.ERROR, logger="apps.qualification"):
        response = _post_voice(client)

    assert response.status_code == 503
    assert "qualification_voice_missing_deepgram_credentials" in caplog.text


@override_settings(
    N8N_QUALIFICATION_API_SECRET="test-n8n-qualification-api-secret",
    TWILIO_ACCOUNT_SID="ACtesttwilioaccountsidthirtyfour",
    TWILIO_AUTH_TOKEN="test-twilio-auth-token",
    DEEPGRAM_API_KEY="test-deepgram-api-key",
)
@patch("apps.qualification.core.legacy_compat.download_twilio_media")
def test_twilio_unauthorized_returns_503_and_logs_event(mock_download, client, caplog):
    def _raise_unauthorized(*args: object, **kwargs: object) -> bytes:
        exc = TwilioMediaUnauthorizedError("Twilio media download unauthorized")
        exc.__cause__ = urllib.error.HTTPError(
            url="https://api.twilio.com/",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=BytesIO(b""),
        )
        raise exc

    mock_download.side_effect = _raise_unauthorized
    with caplog.at_level(logging.ERROR, logger="apps.qualification"):
        response = _post_voice(client)

    assert response.status_code == 502
    assert response.json() == {"error": "Twilio media download failed."}
    assert "twilio_media_download_failed" in caplog.text
    assert "qualification_voice_twilio_download_unauthorized" in caplog.text


@override_settings(
    N8N_QUALIFICATION_API_SECRET="test-n8n-qualification-api-secret",
    TWILIO_ACCOUNT_SID="ACtesttwilioaccountsidthirtyfour",
    TWILIO_AUTH_TOKEN="test-twilio-auth-token",
    DEEPGRAM_API_KEY="test-deepgram-api-key",
)
@patch(
    "apps.qualification.core.legacy_compat.download_twilio_media",
    side_effect=TwilioMediaTimeoutError("Twilio media download timed out"),
)
def test_twilio_download_timeout_returns_503_and_logs_event(mock_download, client, caplog):
    with caplog.at_level(logging.ERROR, logger="apps.qualification"):
        response = _post_voice(client)

    assert response.status_code == 502
    assert response.json() == {"error": "Twilio media download failed."}
    assert "twilio_media_download_failed" in caplog.text
    assert "qualification_voice_twilio_download_timeout" in caplog.text


@override_settings(
    N8N_QUALIFICATION_API_SECRET="test-n8n-qualification-api-secret",
    TWILIO_ACCOUNT_SID="ACtesttwilioaccountsidthirtyfour",
    TWILIO_AUTH_TOKEN="test-twilio-auth-token",
    DEEPGRAM_API_KEY="test-deepgram-api-key",
)
@patch("apps.qualification.core.legacy_compat.transcribe_audio")
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
def test_deepgram_non_success_returns_503_and_logs_event(
    mock_download,
    mock_transcribe,
    client,
    caplog,
):
    def _raise_deepgram_error(*args: object, **kwargs: object) -> str:
        exc = DeepgramRequestError("Deepgram request failed")
        exc.__cause__ = urllib.error.HTTPError(
            url="https://api.deepgram.com/",
            code=500,
            msg="Server Error",
            hdrs=None,
            fp=BytesIO(b""),
        )
        raise exc

    mock_transcribe.side_effect = _raise_deepgram_error
    with caplog.at_level(logging.ERROR, logger="apps.qualification"):
        response = _post_voice(client)

    assert response.status_code == 502
    assert response.json() == {"error": "Voice transcription failed."}
    assert "deepgram_transcription_failed" in caplog.text
    assert "qualification_voice_deepgram_request_failed" in caplog.text


@override_settings(
    N8N_QUALIFICATION_API_SECRET="test-n8n-qualification-api-secret",
    TWILIO_ACCOUNT_SID="ACtesttwilioaccountsidthirtyfour",
    TWILIO_AUTH_TOKEN="test-twilio-auth-token",
    DEEPGRAM_API_KEY="test-deepgram-api-key",
)
@patch(
    "apps.qualification.core.legacy_compat.transcribe_audio",
    side_effect=DeepgramTimeoutError("Deepgram request timed out"),
)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
def test_deepgram_timeout_returns_503_and_logs_event(
    mock_download,
    mock_transcribe,
    client,
    caplog,
):
    with caplog.at_level(logging.ERROR, logger="apps.qualification"):
        response = _post_voice(client)

    assert response.status_code == 502
    assert response.json() == {"error": "Voice transcription failed."}
    assert "deepgram_transcription_failed" in caplog.text
    assert "qualification_voice_deepgram_timeout" in caplog.text


@override_settings(
    N8N_QUALIFICATION_API_SECRET="test-n8n-qualification-api-secret",
    TWILIO_ACCOUNT_SID="ACtesttwilioaccountsidthirtyfour",
    TWILIO_AUTH_TOKEN="test-twilio-auth-token",
    DEEPGRAM_API_KEY="test-deepgram-api-key",
)
@patch("apps.qualification.core.legacy_compat.transcribe_audio", return_value=VOICE_TRANSCRIPT)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_valid_mocked_voice_pipeline_returns_200_with_voice_fields(
    mock_extract,
    mock_download,
    mock_transcribe,
    client,
):
    mock_extract.return_value = SAMPLE_FILTER_RESULT

    response = _post_voice(client)

    assert response.status_code == 200
    body = response.json()
    assert body["reply_mode"] == "voice"
    assert body["transcript"] == VOICE_TRANSCRIPT
    assert body["reply_text"]


@override_settings(
    TWILIO_ACCOUNT_SID="ACtesttwilioaccountsidthirtyfour",
    TWILIO_AUTH_TOKEN="test-twilio-auth-token",
    DEEPGRAM_API_KEY="test-deepgram-api-key",
)
def test_check_voice_note_config_ready(capsys):
    call_command("check_voice_note_config")
    output = capsys.readouterr().out
    assert "Twilio media download credentials: configured" in output
    assert "Deepgram API key: configured" in output
    assert "Voice-note configuration: READY" in output


@override_settings(
    TWILIO_ACCOUNT_SID="",
    TWILIO_AUTH_TOKEN="",
    DEEPGRAM_API_KEY="",
)
def test_check_voice_note_config_not_ready(capsys):
    with pytest.raises(SystemExit) as exc_info:
        call_command("check_voice_note_config")
    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "Twilio media download credentials: missing" in output
    assert "Deepgram API key: missing" in output
    assert "Voice-note configuration: NOT READY" in output


def test_voice_note_config_report_never_exposes_secret_values():
    report = get_voice_note_config_report()
    rendered = (
        f"{report.twilio_media_credentials}"
        f"{report.deepgram_api_key}"
        f"{report.deepgram_model}"
        f"{report.deepgram_base_url}"
        f"{report.ready}"
    )
    assert "test-twilio" not in rendered
    assert "api_key" not in rendered.lower() or report.deepgram_api_key in {"configured", "missing"}


@override_settings(
    TWILIO_ACCOUNT_SID="ACtesttwilioaccountsidthirtyfour",
    TWILIO_AUTH_TOKEN="test-twilio-auth-token",
    DEEPGRAM_API_KEY="test-deepgram-api-key",
    TWILIO_MEDIA_MAX_BYTES=1024,
)
@patch("apps.qualification.twilio_media.urllib.request.urlopen")
def test_twilio_media_download_enforces_size_limit(mock_urlopen):
    from apps.qualification.twilio_media import download_twilio_media

    class FakeResponse:
        headers = {"Content-Type": "audio/ogg"}

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def read(self, size: int = -1) -> bytes:
            return b"x" * 2048

    mock_urlopen.return_value = FakeResponse()
    media_url = (
        "https://api.twilio.com/2010-04-01/Accounts/ACtest/Media/MEtestvoice001"
    )

    with pytest.raises(TwilioMediaRequestError):
        download_twilio_media(media_url)


@override_settings(
    N8N_QUALIFICATION_API_SECRET="test-n8n-qualification-api-secret",
    TWILIO_ACCOUNT_SID="ACtesttwilioaccountsidthirtyfour",
    TWILIO_AUTH_TOKEN="test-twilio-auth-token",
    DEEPGRAM_API_KEY="test-deepgram-api-key",
    OPENROUTER_API_KEY="",
    OPENROUTER_MODEL="test/model",
)
@patch(
    "apps.qualification.qualification_turn.try_handle_rich_inbound_qualification_turn",
    return_value=None,
)
@patch(
    "apps.qualification.qualification_turn.extract_qualification_from_openrouter",
    side_effect=OpenRouterConfigurationError("OpenRouter API key is not configured"),
)
@patch("apps.qualification.core.legacy_compat.transcribe_audio", return_value=VOICE_TRANSCRIPT)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
def test_openrouter_missing_after_successful_transcription_logs_failure_type(
    mock_download,
    mock_transcribe,
    mock_extract,
    mock_rich,
    client,
    caplog,
):
    """Force OpenRouter path after transcription (bypass rich inbound)."""
    clear_message_sid_cache()
    with caplog.at_level(logging.ERROR, logger="apps.qualification"):
        response = _post_voice(
            client,
            _voice_payload(message_sid="MMbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"),
        )

    assert response.status_code == 503
    assert response.json() == {"error": "Qualification service is unavailable."}
    assert "QualificationServiceUnavailableError:OpenRouterConfigurationError" in caplog.text
    mock_extract.assert_called_once()
    mock_rich.assert_called_once()


@override_settings(
    TWILIO_ACCOUNT_SID="ACtesttwilioaccountsidthirtyfour",
    TWILIO_AUTH_TOKEN="test-twilio-auth-token",
)
@patch("apps.qualification.twilio_media.urllib.request.urlopen")
def test_twilio_media_download_maps_socket_timeout(mock_urlopen):
    from apps.qualification.twilio_media import download_twilio_media

    mock_urlopen.side_effect = urllib.error.URLError(socket.timeout("timed out"))
    media_url = (
        "https://api.twilio.com/2010-04-01/Accounts/ACtest/Media/MEtestvoice001"
    )

    with pytest.raises(TwilioMediaTimeoutError):
        download_twilio_media(media_url)
