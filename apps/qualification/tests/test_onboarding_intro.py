"""Regression tests for first-contact WhatsApp onboarding (not idle-triggered)."""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from apps.qualification.conversation_state import (
    clear_conversations,
    get_accepted_fields,
    save_accepted_fields,
)
from apps.qualification.domain.language_selection import LANGUAGE_ARABIC, LANGUAGE_ENGLISH
from apps.qualification.domain.messages import get_customer_message, get_language_changed_confirmation_message
from apps.qualification.domain.tts_safety import spoken_text_contains_url
from apps.qualification.domain.whatsapp_menu_commands import is_menu_command
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.models import QualificationFieldFilterResult, WhatsAppConversationSession
from apps.qualification.tests.internal_api_test_helpers import (
    API_SECRET,
    MOCK_VOICE_AUDIO_DOWNLOAD,
    internal_api_auth_headers,
)

# language_gate unstubs LanguageGateService + WhatsAppMenuService (see root conftest).
pytestmark = [pytest.mark.django_db, pytest.mark.language_gate]

ENDPOINT_PATH = "/api/internal/qualification/extract/"
WHATSAPP_NUMBER = "+923001234567"
MEDIA_URL = "https://api.twilio.com/2010-04-01/Accounts/ACtest/Media/MEtestvoice001"

SETTINGS = {
    "TWILIO_LANGUAGE_PICKER_CONTENT_SID": "HXtestcontentsidfortest0000000000",
    "TWILIO_WHATSAPP_FROM_NUMBER": "whatsapp:+15557654321",
    "TWILIO_WHATSAPP_MENU_CONTENT_SID": "HXtestmainmenucontentsid00000000",
    "LEAD_QUALIFICATION_ENABLED": True,
    "N8N_QUALIFICATION_API_SECRET": API_SECRET,
    "ONBOARDING_REINTRO_AFTER_SECONDS": 7200,
    "SESSION_IDLE_RESET_SECONDS": 7200,
}


def _post(client: Client, payload: dict) -> object:
    return client.post(
        ENDPOINT_PATH,
        data=json.dumps(payload),
        content_type="application/json",
        **internal_api_auth_headers(secret=API_SECRET),
    )


def _text(*, message: str, message_sid: str, button_payload: str | None = None) -> dict:
    payload = {
        "message": message,
        "whatsapp_number": WHATSAPP_NUMBER,
        "input_channel": "whatsapp_text",
        "message_sid": message_sid,
    }
    if button_payload is not None:
        payload["button_payload"] = button_payload
    return payload


def _seed_english_session(
    *,
    onboarded: bool = True,
    last_message_at=None,
) -> WhatsAppConversationSession:
    return WhatsAppConversationSession.objects.create(
        whatsapp_number=WHATSAPP_NUMBER,
        language=LANGUAGE_ENGLISH,
        language_selected_at=timezone.now(),
        onboarding_intro_sent=onboarded,
        last_message_at=last_message_at,
        last_onboarding_intro_at=timezone.now() if onboarded else None,
    )


@pytest.fixture
def client() -> Client:
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()
    return Client()


@pytest.fixture(autouse=True)
def _reset_state():
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()
    yield
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()


@override_settings(**SETTINGS)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@patch("apps.qualification.services.language_gate_service.send_language_picker")
def test_first_text_message_sends_onboarding_intro_once(
    mock_send_picker,
    mock_extract,
    client,
):
    mock_send_picker.return_value = "SMlangpickersent0000000000000000"
    mock_extract.return_value = QualificationFieldFilterResult(
        accepted_fields={"project_type": "new_website"},
        rejected_fields=(),
        human_handoff_requested=False,
    )

    first = _post(
        client,
        _text(message="hi", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce01"),
    )
    assert first.status_code == 200
    assert first.json()["status"] == "awaiting_language_selection"

    second = _post(
        client,
        _text(
            message="English",
            message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce02",
            button_payload="lang_en",
        ),
    )
    body = second.json()
    intro = get_customer_message(language=LANGUAGE_ENGLISH, key="onboarding_intro")
    question = get_customer_message(language=LANGUAGE_ENGLISH, key="project_type")
    assert second.status_code == 200
    assert intro in body["reply_text"]
    assert question in body["reply_text"]
    assert body["reply_text"].startswith(intro)
    session = WhatsAppConversationSession.objects.get(whatsapp_number=WHATSAPP_NUMBER)
    assert session.onboarding_intro_sent is True
    assert session.last_onboarding_intro_at is not None

    third = _post(
        client,
        _text(message="I need a website", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce03"),
    )
    third_body = third.json()
    assert intro not in third_body["reply_text"]
    session.refresh_from_db()
    assert session.onboarding_intro_sent is True


@override_settings(**SETTINGS)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.core.legacy_compat.transcribe_audio", return_value="hello")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_first_voice_note_small_talk_skips_onboarding_intro(
    mock_extract,
    mock_transcribe,
    mock_download,
    client,
):
    _seed_english_session(onboarded=False)

    response = _post(
        client,
        {
            "whatsapp_number": WHATSAPP_NUMBER,
            "input_channel": "whatsapp_voice_note",
            "message_sid": "SM0cc5a1d9e22bf9850ca24261ee23ce10",
            "media_url": MEDIA_URL,
            "media_content_type": "audio/ogg",
        },
    )
    body = response.json()
    text_intro = get_customer_message(language=LANGUAGE_ENGLISH, key="onboarding_intro")
    assert response.status_code == 200
    assert text_intro not in body.get("whatsapp_text", "")
    assert "Hi!" in body["reply_text"]
    assert "new website" in body["spoken_text"].lower()
    assert body["spoken_text"] == body["reply_text"]
    assert body["should_send_audio"] is True
    assert body["should_send_text"] is False
    assert body.get("whatsapp_text", "") == ""
    assert "To open the menu" not in body["spoken_text"]
    assert len(body["spoken_text"]) <= 180
    assert spoken_text_contains_url(body["spoken_text"]) is False
    mock_transcribe.assert_called_once()
    mock_download.assert_called_once()
    mock_extract.assert_not_called()


@override_settings(**SETTINGS)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.core.legacy_compat.transcribe_audio", return_value="I need a new website")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_first_voice_website_request_asks_project_question_not_phone(
    mock_extract,
    mock_transcribe,
    mock_download,
    client,
):
    _seed_english_session(onboarded=False)

    response = _post(
        client,
        {
            "whatsapp_number": WHATSAPP_NUMBER,
            "input_channel": "whatsapp_voice_note",
            "message_sid": "SM0cc5a1d9e22bf9850ca24261ee23ce11",
            "media_url": MEDIA_URL,
            "media_content_type": "audio/ogg",
        },
    )
    body = response.json()
    text_intro = get_customer_message(language=LANGUAGE_ENGLISH, key="onboarding_intro")
    assert response.status_code == 200
    assert text_intro not in body.get("whatsapp_text", "")
    assert body.get("whatsapp_text", "") == ""
    assert body["should_send_audio"] is True
    assert body["should_send_text"] is False
    assert body["next_field"] != "whatsapp_confirmed"
    assert "best number to reach you" not in body["spoken_text"].lower()
    assert "To open the menu" not in body["spoken_text"]
    assert "How did you hear" in body["spoken_text"] or "Thank you" in body["spoken_text"]
    assert len(body["spoken_text"]) <= 180
    mock_extract.assert_not_called()
    fields = get_accepted_fields(WHATSAPP_NUMBER)
    assert fields.get("project_type") == "new_website"
    assert fields.get("requirements")


@override_settings(**SETTINGS)
def test_finalize_voice_turn_uses_spoken_text_not_reply_text_for_tts():
    from apps.qualification.channels import finalize_turn_response

    text_intro = get_customer_message(language=LANGUAGE_ENGLISH, key="onboarding_intro")
    voice_intro = get_customer_message(language=LANGUAGE_ENGLISH, key="onboarding_intro_voice")
    question = get_customer_message(language=LANGUAGE_ENGLISH, key="requirements")
    whatsapp_text = f"{text_intro}\n\n{question}"

    finalized = finalize_turn_response(
        {
            "reply_text": whatsapp_text,
            "whatsapp_text": whatsapp_text,
            "spoken_text": voice_intro,
            "qualification_status": "in_progress",
        },
        input_channel="whatsapp_voice_note",
        transcript="hello",
        conversation_language=LANGUAGE_ENGLISH,
    )

    assert finalized["spoken_text"] == voice_intro
    assert finalized["reply_text"] == voice_intro
    assert finalized["whatsapp_text"] == ""
    assert finalized["should_send_audio"] is True
    assert finalized["should_send_text"] is False
    assert "To open the menu" not in finalized["spoken_text"]


@override_settings(**SETTINGS)
def test_sanitize_spoken_text_strips_onboarding_copy_before_tts():
    from apps.qualification.domain.tts_safety import (
        get_safe_voice_fallback,
        sanitize_spoken_text_for_tts,
        spoken_text_contains_onboarding_copy,
    )

    long_onboarding = get_customer_message(language=LANGUAGE_ENGLISH, key="onboarding_intro")
    spoken = sanitize_spoken_text_for_tts(long_onboarding, language=LANGUAGE_ENGLISH)
    assert spoken_text_contains_onboarding_copy(long_onboarding) is True
    assert spoken == get_safe_voice_fallback(language=LANGUAGE_ENGLISH)
    assert "To open the menu" not in spoken
    assert len(spoken) <= 180


@override_settings(**SETTINGS)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
def test_message_within_two_hours_skips_onboarding_intro(
    mock_send_menu,
    mock_extract,
    client,
):
    mock_extract.return_value = QualificationFieldFilterResult(
        accepted_fields={},
        rejected_fields=(),
        human_handoff_requested=False,
    )
    _seed_english_session(
        onboarded=True,
        last_message_at=timezone.now() - timedelta(minutes=10),
    )
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {"project_type": "new_website", "requirements": "restaurant website"},
    )

    response = _post(
        client,
        _text(message="Hello", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce50"),
    )
    body = response.json()
    intro = get_customer_message(language=LANGUAGE_ENGLISH, key="onboarding_intro")
    welcome = get_customer_message(language=LANGUAGE_ENGLISH, key="onboarding_welcome_back")
    assert response.status_code == 200
    assert body.get("status") != "awaiting_menu_selection"
    assert intro not in body["reply_text"]
    assert welcome not in body["reply_text"]
    mock_send_menu.assert_not_called()
    assert get_accepted_fields(WHATSAPP_NUMBER)["requirements"] == "restaurant website"


@override_settings(**SETTINGS)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
def test_message_after_two_hours_preserves_qualification_state(
    mock_send_menu,
    mock_extract,
    client,
):
    mock_extract.return_value = QualificationFieldFilterResult(
        accepted_fields={},
        rejected_fields=(),
        human_handoff_requested=False,
    )
    _seed_english_session(
        onboarded=True,
        last_message_at=timezone.now() - timedelta(seconds=7201),
    )
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {"project_type": "new_website", "requirements": "restaurant website"},
    )

    response = _post(
        client,
        _text(message="Hello brother", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce51"),
    )
    body = response.json()
    intro = get_customer_message(language=LANGUAGE_ENGLISH, key="onboarding_intro")
    assert response.status_code == 200
    assert body.get("status") != "awaiting_menu_selection"
    assert "How to use this chat" not in body["reply_text"]
    assert intro not in body["reply_text"]
    assert body["next_field"] == "referral_source"
    assert body["reply_text"].startswith("Hi!")
    assert get_accepted_fields(WHATSAPP_NUMBER)["project_type"] == "new_website"
    assert get_accepted_fields(WHATSAPP_NUMBER)["requirements"] == "restaurant website"
    mock_send_menu.assert_not_called()
    mock_extract.assert_not_called()


@override_settings(**SETTINGS)
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.core.legacy_compat.transcribe_audio", return_value="Hello brother")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
def test_voice_after_two_hours_preserves_qualification_state(
    mock_send_menu,
    mock_extract,
    mock_transcribe,
    mock_download,
    client,
):
    mock_extract.return_value = QualificationFieldFilterResult(
        accepted_fields={},
        rejected_fields=(),
        human_handoff_requested=False,
    )
    _seed_english_session(
        onboarded=True,
        last_message_at=timezone.now() - timedelta(seconds=7201),
    )
    save_accepted_fields(WHATSAPP_NUMBER, {"project_type": "new_website"})

    response = _post(
        client,
        {
            "whatsapp_number": WHATSAPP_NUMBER,
            "input_channel": "whatsapp_voice_note",
            "message_sid": "SM0cc5a1d9e22bf9850ca24261ee23ce52",
            "media_url": MEDIA_URL,
            "media_content_type": "audio/ogg",
        },
    )
    body = response.json()
    intro = get_customer_message(language=LANGUAGE_ENGLISH, key="onboarding_intro")
    assert response.status_code == 200
    assert body.get("status") != "awaiting_menu_selection"
    assert intro not in body["whatsapp_text"]
    assert body["next_field"] == "requirements"
    assert get_accepted_fields(WHATSAPP_NUMBER)["project_type"] == "new_website"
    assert body["reply_text"].startswith("Hi!")
    assert "To open the menu" not in body["spoken_text"]
    mock_send_menu.assert_not_called()
    mock_transcribe.assert_called_once()
    mock_extract.assert_not_called()


@override_settings(**{**SETTINGS, "ONBOARDING_REINTRO_AFTER_SECONDS": 60})
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
def test_message_after_sixty_one_seconds_preserves_state(
    mock_send_menu,
    mock_extract,
    client,
):
    mock_extract.return_value = QualificationFieldFilterResult(
        accepted_fields={},
        rejected_fields=(),
        human_handoff_requested=False,
    )
    _seed_english_session(
        onboarded=True,
        last_message_at=timezone.now() - timedelta(seconds=301),
    )
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "project_type": "new_website",
            "requirements": "restaurant website",
            "referral_source": "Facebook",
        },
    )

    response = _post(
        client,
        _text(message="Hello again", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce60"),
    )
    body = response.json()

    assert response.status_code == 200
    assert body["next_field"] is None
    assert get_accepted_fields(WHATSAPP_NUMBER)["referral_source"] == "Facebook"
    intro = get_customer_message(language=LANGUAGE_ENGLISH, key="onboarding_intro")
    assert intro not in body["reply_text"]
    mock_send_menu.assert_not_called()
    mock_extract.assert_not_called()


@override_settings(**{**SETTINGS, "ONBOARDING_REINTRO_AFTER_SECONDS": 60})
@patch("apps.qualification.core.legacy_compat.download_twilio_media", return_value=MOCK_VOICE_AUDIO_DOWNLOAD)
@patch("apps.qualification.core.legacy_compat.transcribe_audio", return_value="I am back now")
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
def test_voice_after_sixty_one_seconds_preserves_state(
    mock_send_menu,
    mock_extract,
    mock_transcribe,
    mock_download,
    client,
):
    mock_extract.return_value = QualificationFieldFilterResult(
        accepted_fields={},
        rejected_fields=(),
        human_handoff_requested=False,
    )
    _seed_english_session(
        onboarded=True,
        last_message_at=timezone.now() - timedelta(seconds=301),
    )
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "project_type": "new_website",
            "requirements": "restaurant website",
            "referral_source": "Facebook",
        },
    )

    response = _post(
        client,
        {
            "whatsapp_number": WHATSAPP_NUMBER,
            "input_channel": "whatsapp_voice_note",
            "message_sid": "SM0cc5a1d9e22bf9850ca24261ee23ce61",
            "media_url": MEDIA_URL,
            "media_content_type": "audio/ogg",
        },
    )
    body = response.json()
    intro = get_customer_message(language=LANGUAGE_ENGLISH, key="onboarding_intro")

    assert response.status_code == 200
    assert intro not in body["whatsapp_text"]
    assert body["next_field"] is None
    assert get_accepted_fields(WHATSAPP_NUMBER)["requirements"] == "restaurant website"
    mock_transcribe.assert_called_once()
    mock_extract.assert_not_called()


@override_settings(**{**SETTINGS, "ONBOARDING_REINTRO_AFTER_SECONDS": 60})
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_long_gap_idempotency_cache_still_works(mock_extract, client):
    mock_extract.return_value = QualificationFieldFilterResult(
        accepted_fields={},
        rejected_fields=(),
        human_handoff_requested=False,
    )
    _seed_english_session(
        onboarded=True,
        last_message_at=timezone.now() - timedelta(seconds=301),
    )
    save_accepted_fields(WHATSAPP_NUMBER, {"project_type": "new_website"})
    message_sid = "SM0cc5a1d9e22bf9850ca24261ee23ce62"

    first = _post(client, _text(message="Hello brother", message_sid=message_sid))
    second = _post(client, _text(message="Hello brother", message_sid=message_sid))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    mock_extract.assert_not_called()


@override_settings(**{**SETTINGS, "ONBOARDING_REINTRO_AFTER_SECONDS": 60})
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_hello_brother_after_long_gap_preserves_state(mock_extract, client):
    mock_extract.return_value = QualificationFieldFilterResult(
        accepted_fields={},
        rejected_fields=(),
        human_handoff_requested=False,
    )
    _seed_english_session(
        onboarded=True,
        last_message_at=timezone.now() - timedelta(seconds=301),
    )
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "project_type": "new_website",
            "requirements": "ecommerce",
            "referral_source": "Instagram",
            "whatsapp_confirmed": True,
            "preferred_phone": WHATSAPP_NUMBER,
        },
    )

    response = _post(
        client,
        _text(message="Hello brother", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce63"),
    )
    body = response.json()
    intro = get_customer_message(language=LANGUAGE_ENGLISH, key="onboarding_intro")

    assert response.status_code == 200
    assert intro not in body["reply_text"]
    assert body["qualification_status"] == "completed"
    assert get_accepted_fields(WHATSAPP_NUMBER)["referral_source"] == "Instagram"
    mock_extract.assert_not_called()


@override_settings(**SETTINGS)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_hello_brother_small_talk_repeats_current_question(mock_extract, client):
    mock_extract.return_value = QualificationFieldFilterResult(
        accepted_fields={},
        rejected_fields=(),
        human_handoff_requested=False,
    )
    _seed_english_session(
        onboarded=True,
        last_message_at=timezone.now() - timedelta(seconds=30),
    )
    save_accepted_fields(WHATSAPP_NUMBER, {"project_type": "new_website"})

    response = _post(
        client,
        _text(message="Hello brother", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce64"),
    )
    body = response.json()
    intro = get_customer_message(language=LANGUAGE_ENGLISH, key="onboarding_intro")

    assert response.status_code == 200
    assert intro not in body["reply_text"]
    assert body["accepted_fields"]["project_type"] == "new_website"
    assert body["reply_text"].startswith("Hi!")
    assert "May I know what type of website help you need" in body["reply_text"]
    mock_extract.assert_not_called()


@override_settings(**SETTINGS)
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
def test_exact_uppercase_m_opens_menu_without_intro_again(mock_send_menu, client):
    mock_send_menu.return_value = "SMmainmenusent0000000000000000"
    _seed_english_session(onboarded=True, last_message_at=timezone.now())
    save_accepted_fields(WHATSAPP_NUMBER, {"project_type": "new_website"})

    response = _post(
        client,
        _text(message="M", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce20"),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "awaiting_menu_selection"
    mock_send_menu.assert_called_once()
    assert is_menu_command("M") is True


@pytest.mark.parametrize("message", ["m", "menu", "/menu", "i need your menu", "M please", "Hello"])
def test_non_exact_m_is_not_menu_command(message: str):
    assert is_menu_command(message) is False


@override_settings(**SETTINGS)
@patch("apps.qualification.services.whatsapp_menu_service.send_language_picker")
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
def test_change_language_from_menu_opens_picker_and_continues(
    mock_send_menu,
    mock_send_picker,
    client,
):
    mock_send_menu.return_value = "SMmainmenusent0000000000000001"
    mock_send_picker.return_value = "SMlangpickersent0000000000000001"
    _seed_english_session(onboarded=True, last_message_at=timezone.now())
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {
            "project_type": "new_website",
            "requirements": "restaurant website",
        },
    )

    _post(client, _text(message="M", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce30"))
    picker = _post(
        client,
        _text(
            message="Change language",
            message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce31",
            button_payload="language",
        ),
    )
    assert picker.json()["status"] == "awaiting_language_selection"
    mock_send_picker.assert_called_once()

    arabic = _post(
        client,
        _text(
            message="العربية",
            message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce32",
            button_payload="lang_ar",
        ),
    )
    body = arabic.json()
    confirmation = get_language_changed_confirmation_message(language=LANGUAGE_ARABIC)
    question = get_customer_message(language=LANGUAGE_ARABIC, key="referral_source")
    assert confirmation in body["reply_text"]
    assert question in body["reply_text"]
    assert get_accepted_fields(WHATSAPP_NUMBER)["requirements"] == "restaurant website"
    intro = get_customer_message(language=LANGUAGE_ARABIC, key="onboarding_intro")
    assert intro not in body["reply_text"]


@override_settings(**SETTINGS)
@patch("apps.qualification.services.whatsapp_menu_service.send_whatsapp_menu")
def test_restart_resets_onboarding_intro_flag(mock_send_menu, client):
    mock_send_menu.return_value = "SMmainmenusent0000000000000002"
    session = _seed_english_session(onboarded=True, last_message_at=timezone.now())
    save_accepted_fields(WHATSAPP_NUMBER, {"project_type": "new_website"})

    _post(client, _text(message="M", message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce40"))
    _post(
        client,
        _text(
            message="Restart qualification",
            message_sid="SM0cc5a1d9e22bf9850ca24261ee23ce41",
            button_payload="restart",
        ),
    )
    session.refresh_from_db()
    assert session.onboarding_intro_sent is False
    assert session.last_onboarding_intro_at is None
    assert get_accepted_fields(WHATSAPP_NUMBER) == {}
