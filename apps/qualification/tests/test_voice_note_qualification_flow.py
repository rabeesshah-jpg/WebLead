"""Tests that WhatsApp voice notes follow the same qualification flow as text."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from apps.qualification.conversation_state import (
    clear_conversations,
    get_accepted_fields,
    save_accepted_fields,
)
from apps.qualification.domain.extract_errors import (
    VOICE_TRANSCRIPTION_FAILED,
    ExtractFailureInfo,
    ExtractStepFailure,
)
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.models import QualificationFieldFilterResult, WhatsAppConversationSession
from apps.qualification.services.conversation_session_service import mark_booking_link_sent
from apps.qualification.tests.internal_api_test_helpers import (
    API_SECRET,
    MOCK_VOICE_AUDIO_DOWNLOAD,
    internal_api_auth_headers,
)

BOOKING_LINK = "https://booking.example.com/test-schedule"

pytestmark = pytest.mark.django_db

ENDPOINT_PATH = "/api/internal/qualification/extract/"
WHATSAPP_NUMBER = "+923001234567"
MEDIA_URL = "https://api.twilio.com/2010-04-01/Accounts/ACtest/Media/MEtestvoice001"


def _post_voice(
    client: Client,
    *,
    transcript: str | None = None,
    message: str | None = None,
    message_sid: str,
    mock_transcribe,
) -> object:
    if transcript is not None:
        mock_transcribe.return_value = transcript
    return client.post(
        ENDPOINT_PATH,
        data=json.dumps(
            {
                "whatsapp_number": WHATSAPP_NUMBER,
                "input_channel": "whatsapp_voice_note",
                "message_sid": message_sid,
                "media_url": MEDIA_URL,
                "media_content_type": "audio/ogg",
                **({"message": message} if message is not None else {}),
            }
        ),
        content_type="application/json",
        **internal_api_auth_headers(),
    )


@pytest.fixture
def client() -> Client:
    clear_conversations()
    clear_message_sid_cache()
    return Client()


@pytest.fixture(autouse=True)
def _english_session():
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()
    WhatsAppConversationSession.objects.create(
        whatsapp_number=WHATSAPP_NUMBER,
        language="en",
        language_selected_at=timezone.now(),
        onboarding_intro_sent=True,
    )
    yield
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.core.legacy_compat.transcribe_audio")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_voice_both_captures_project_type_and_asks_requirements(
    mock_extract,
    mock_transcribe,
    mock_download,
    client,
):
    response = _post_voice(
        client,
        transcript="Both",
        message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce90",
        mock_transcribe=mock_transcribe,
    )
    body = response.json()

    assert response.status_code == 200
    assert body["transcript"] == "Both"
    assert body["accepted_fields"]["project_type"] == "new_and_upgrade"
    assert body["next_field"] == "requirements"
    assert body["should_send_audio"] is True
    assert body["should_send_text"] is False
    assert body.get("whatsapp_text", "") == ""
    assert "May I know what type of website help you need" in body["spoken_text"]
    mock_extract.assert_not_called()
    mock_transcribe.assert_called_once()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.core.legacy_compat.transcribe_audio")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_voice_ecommerce_captures_requirements_and_asks_referral(
    mock_extract,
    mock_transcribe,
    mock_download,
    client,
):
    save_accepted_fields(WHATSAPP_NUMBER, {"project_type": "new_website"})

    response = _post_voice(
        client,
        transcript="I need an ecommerce website",
        message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce91",
        mock_transcribe=mock_transcribe,
    )
    body = response.json()

    assert response.status_code == 200
    assert "ecommerce" in body["accepted_fields"]["requirements"].lower()
    assert body["next_field"] == "referral_source"
    assert body["should_send_audio"] is True
    assert body["should_send_text"] is False
    assert "How did you hear about Good Websites" in body["spoken_text"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.core.legacy_compat.transcribe_audio")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_voice_referral_captures_source_and_completes_without_confirmation(
    mock_extract,
    mock_transcribe,
    mock_download,
    client,
):
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "project_type": "new_website",
            "requirements": "ecommerce website",
        },
    )
    mock_extract.return_value = QualificationFieldFilterResult(
        accepted_fields={"referral_source": "My friend told me"},
        rejected_fields=(),
        human_handoff_requested=False,
    )

    response = _post_voice(
        client,
        transcript="My friend told me",
        message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce92",
        mock_transcribe=mock_transcribe,
    )
    body = response.json()

    assert response.status_code == 200
    assert body["accepted_fields"]["referral_source"] == "My friend told me"
    assert body["next_field"] is None
    assert body["qualification_status"] == "completed"
    assert body["should_send_audio"] is True
    assert body["should_send_text"] is True
    assert BOOKING_LINK in body["reply_text"]
    assert BOOKING_LINK not in body["spoken_text"]
    assert "best contact number" not in body["spoken_text"]
    assert body["booking_link_sent"] is True
    mock_extract.assert_called_once()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.core.legacy_compat.transcribe_audio")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_voice_small_talk_repeats_current_question_without_onboarding(
    mock_extract,
    mock_transcribe,
    mock_download,
    client,
):
    response = _post_voice(
        client,
        transcript="How are you?",
        message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce93",
        mock_transcribe=mock_transcribe,
    )
    body = response.json()

    assert response.status_code == 200
    assert "doing well" in body["spoken_text"]
    assert "new website" in body["spoken_text"].lower()
    assert body["should_send_audio"] is True
    assert body["should_send_text"] is False
    assert body.get("whatsapp_text", "") == ""
    assert body["qualification_status"] == "in_progress"
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.core.legacy_compat.transcribe_audio")
def test_voice_empty_transcription_asks_retry_without_handoff(
    mock_transcribe,
    mock_download,
    client,
):
    mock_transcribe.side_effect = ExtractStepFailure(
        ExtractFailureInfo(
            failure_step="deepgram_transcription_failed",
            public_message=VOICE_TRANSCRIPTION_FAILED,
            error_type="DeepgramResponseError",
            details="Deepgram transcript is empty",
        )
    )

    response = _post_voice(
        client,
        message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce94",
        mock_transcribe=mock_transcribe,
    )
    body = response.json()

    assert response.status_code == 200
    assert body["qualification_status"] == "in_progress"
    assert body["human_handoff_requested"] is False
    assert body["reply_text"] == get_customer_message(
        language="en",
        key="voice_transcription_unclear_spoken",
    )
    assert body["spoken_text"] == body["reply_text"]
    assert body["text_fallback_reply"] == get_customer_message(
        language="en",
        key="voice_transcription_unclear",
    )
    assert body["should_send_audio"] is True
    assert body["should_send_text"] is False
    assert "team member will follow up" not in body["reply_text"]


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.core.legacy_compat.transcribe_audio")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_voice_ignores_body_when_media_is_present(
    mock_extract,
    mock_transcribe,
    mock_download,
    client,
):
    response = _post_voice(
        client,
        transcript="Both",
        message="please ignore this body text",
        message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce95",
        mock_transcribe=mock_transcribe,
    )
    body = response.json()

    assert response.status_code == 200
    assert body["transcript"] == "Both"
    assert body["accepted_fields"]["project_type"] == "new_and_upgrade"
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.core.legacy_compat.transcribe_audio")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_text_and_voice_share_same_session_state(
    mock_extract,
    mock_transcribe,
    mock_download,
    client,
):
    text_response = client.post(
        ENDPOINT_PATH,
        data=json.dumps(
            {
                "message": "Both",
                "whatsapp_number": WHATSAPP_NUMBER,
                "input_channel": "whatsapp_text",
                "message_sid": "SM0cc5a1d9e22bf9850ca24261ee23ce96",
            }
        ),
        content_type="application/json",
        **internal_api_auth_headers(),
    )
    assert text_response.json()["accepted_fields"]["project_type"] == "new_and_upgrade"

    voice_response = _post_voice(
        client,
        transcript="I need an ecommerce website",
        message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce97",
        mock_transcribe=mock_transcribe,
    )
    voice_body = voice_response.json()

    assert voice_body["accepted_fields"]["project_type"] == "new_and_upgrade"
    assert "ecommerce" in voice_body["accepted_fields"]["requirements"].lower()
    assert get_accepted_fields(WHATSAPP_NUMBER)["requirements"] == voice_body["accepted_fields"]["requirements"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.core.legacy_compat.transcribe_audio")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_voice_after_booking_link_does_not_resend_url(
    mock_extract,
    mock_transcribe,
    mock_download,
    client,
):
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "project_type": "new_website",
            "requirements": "ecommerce",
            "referral_source": "friend",
            "whatsapp_confirmed": True,
            "preferred_phone": WHATSAPP_NUMBER,
        },
    )
    session = WhatsAppConversationSession.objects.get(whatsapp_number=WHATSAPP_NUMBER)
    mark_booking_link_sent(session)

    response = _post_voice(
        client,
        transcript="Thanks",
        message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce98",
        mock_transcribe=mock_transcribe,
    )
    body = response.json()

    assert response.status_code == 200
    assert body["qualification_status"] == "completed"
    assert BOOKING_LINK not in body["whatsapp_text"]
    assert "booking link above" in body["spoken_text"]
    assert body["should_send_audio"] is True
    assert body["should_send_text"] is False
    mock_extract.assert_not_called()


COMPLETION_REPLY_TEXT = get_customer_message(
    language="en",
    key="completion_with_booking_link",
    booking_link=BOOKING_LINK,
)
COMPLETION_SPOKEN = get_customer_message(language="en", key="completion_spoken")


def _reach_whatsapp_confirmation_prompt() -> None:
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "project_type": "new_website",
            "requirements": "I need a new website for my restaurant",
            "referral_source": "Facebook",
        },
    )


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.core.legacy_compat.transcribe_audio")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_voice_qualification_sends_booking_link_once(
    mock_extract,
    mock_transcribe,
    mock_download,
    mock_twilio_booking_link_send,
    client,
):
    _reach_whatsapp_confirmation_prompt()

    response = _post_voice(
        client,
        transcript="Yes",
        message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce99",
        mock_transcribe=mock_transcribe,
    )
    body = response.json()

    assert response.status_code == 200
    assert body["qualification_status"] == "completed"
    assert body["whatsapp_text"] == COMPLETION_REPLY_TEXT
    assert body["reply_text"] == COMPLETION_REPLY_TEXT
    assert BOOKING_LINK in body["reply_text"]
    assert body["spoken_text"] == COMPLETION_SPOKEN
    assert BOOKING_LINK not in body["spoken_text"]
    assert body["send_booking_link"] is True
    assert body["booking_link_sent"] is True
    assert body.get("conversation_state") == "BOOKING_LINK_SENT"
    assert body["should_send_text"] is True
    assert body["should_send_audio"] is True
    assert body["contains_booking_link"] is True
    mock_twilio_booking_link_send.assert_not_called()
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.core.legacy_compat.transcribe_audio")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_voice_how_are_you_after_booking_link_does_not_resend_url(
    mock_extract,
    mock_transcribe,
    mock_download,
    client,
):
    _reach_whatsapp_confirmation_prompt()
    _post_voice(
        client,
        transcript="Yes",
        message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce9a",
        mock_transcribe=mock_transcribe,
    )

    response = _post_voice(
        client,
        transcript="How are you?",
        message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce9b",
        mock_transcribe=mock_transcribe,
    )
    body = response.json()

    assert BOOKING_LINK not in body["whatsapp_text"]
    assert body.get("whatsapp_text", "") == ""
    assert "doing well" in body["spoken_text"]
    assert "booking link above" in body["spoken_text"]
    assert body["should_send_audio"] is True
    assert body["should_send_text"] is False
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET, BOOKING_LINK=BOOKING_LINK)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.core.legacy_compat.transcribe_audio")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_voice_send_link_again_does_not_resend_url(
    mock_extract,
    mock_transcribe,
    mock_download,
    client,
):
    _reach_whatsapp_confirmation_prompt()
    _post_voice(
        client,
        transcript="Yes",
        message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce9c",
        mock_transcribe=mock_transcribe,
    )

    response = _post_voice(
        client,
        transcript="Send link again",
        message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce9d",
        mock_transcribe=mock_transcribe,
    )
    body = response.json()

    assert BOOKING_LINK not in body["whatsapp_text"]
    assert body.get("whatsapp_text", "") == ""
    assert "already shared above" in body["spoken_text"]
    assert body["should_send_audio"] is True
    assert body["should_send_text"] is False
    mock_extract.assert_not_called()
