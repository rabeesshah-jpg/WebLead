"""Tests for per-user qualification conversation locking."""

from __future__ import annotations

import threading
import time
from contextlib import ExitStack
from typing import Callable
from unittest.mock import MagicMock, patch

import pytest
from django.db import close_old_connections
from django.test import Client, override_settings

from apps.qualification.conversation_lock import (
    acquire_conversation_turn_lock,
    build_conversation_lock_timeout_response,
    reset_conversation_lock_backend_for_tests,
)
from apps.qualification.conversation_state import clear_conversations
from apps.qualification.domain.conversation_lock_key import normalize_conversation_lock_key
from apps.qualification.message_idempotency import (
    begin_idempotent_turn,
    cache_turn_response,
    clear_message_sid_cache,
)
from apps.qualification.models import WhatsAppConversationSession
from apps.qualification.qualification_turn import QualificationServiceRequestError
from apps.qualification.services.extract_service import ExtractService
from apps.qualification.services.render_audio_service import RenderAudioService
from apps.qualification.tests.internal_api_test_helpers import API_SECRET, internal_api_auth_headers

pytestmark = pytest.mark.django_db

WHATSAPP_A = "+923001234567"
WHATSAPP_B = "+923246271149"
MESSAGE_SID_A = "SM0cc5a1d9e22bf9850ca24261ee23cef1"
MESSAGE_SID_B = "SM1dd6b2e0f33cg0961db35372ff34deg2"
ENDPOINT_PATH = "/api/internal/qualification/extract/"
RENDER_ENDPOINT = "/api/internal/qualification/render-audio/"


def _text_payload(
    *,
    whatsapp_number: str,
    message: str,
    message_sid: str,
) -> dict:
    return {
        "whatsapp_number": whatsapp_number,
        "message": message,
        "input_channel": "whatsapp_text",
        "message_sid": message_sid}


def _turn_response(reply_text: str = "Hello there") -> dict:
    return {
        "accepted_fields": {},
        "rejected_fields": {},
        "human_handoff_requested": False,
        "next_field": "business_type",
        "reply_text": reply_text,
        "qualification_status": "in_progress",
        "preferred_phone": None,
        "conversation_language": "en"}


def _service(turn_handler: MagicMock | Callable[..., dict]) -> ExtractService:
    language_gate_service = MagicMock()
    language_gate_service.evaluate_turn.return_value = MagicMock(handled=False)
    menu_service = MagicMock()
    menu_service.evaluate_button_payload.return_value = MagicMock(handled=False)
    menu_service.evaluate_turn.return_value = MagicMock(handled=False)
    menu_service.evaluate_inactivity.return_value = MagicMock(handled=False)
    return ExtractService(
        turn_handler=turn_handler,
        language_gate_service=language_gate_service,
        menu_service=menu_service,
    )


def _thread_worker(target: Callable[..., None], *args) -> threading.Thread:
    def runner() -> None:
        close_old_connections()
        try:
            target(*args)
        finally:
            close_old_connections()

    return threading.Thread(target=runner)


def _session_mock(*, whatsapp_number: str) -> MagicMock:
    session = MagicMock(whatsapp_number=whatsapp_number)
    session.onboarding_intro_sent = True
    return session


def _db_free_extract_patches() -> ExitStack:
    """Avoid SQLite contention when exercising lock behavior across threads."""
    stack = ExitStack()
    session_factory = lambda *, whatsapp_number: (
        _session_mock(whatsapp_number=whatsapp_number),
        False,
    )
    stack.enter_context(
        patch(
            "apps.qualification.services.extract_service.get_or_create_conversation_session",
            side_effect=session_factory,
        )
    )
    # Onboarding also loads the session row; keep it off SQLite in parallel tests.
    stack.enter_context(
        patch(
            "apps.qualification.domain.onboarding.get_or_create_conversation_session",
            side_effect=session_factory,
        )
    )
    stack.enter_context(
        patch(
            "apps.qualification.domain.onboarding.mark_onboarding_intro_sent",
            side_effect=lambda session, **kwargs: session,
        )
    )
    stack.enter_context(
        patch("apps.qualification.services.extract_service.reconcile_stale_booking_link_sent_state")
    )
    stack.enter_context(
        patch("apps.qualification.services.extract_service.touch_session_last_message_at")
    )
    stack.enter_context(
        patch(
            "apps.qualification.services.extract_service.get_conversation_language",
            return_value="en",
        )
    )
    stack.enter_context(
        patch(
            "apps.qualification.services.extract_service.ensure_booking_link_delivery_on_response",
            side_effect=lambda response, **kwargs: response,
        )
    )
    return stack


@pytest.fixture(autouse=True)
def _reset_state():
    reset_conversation_lock_backend_for_tests()
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()
    yield
    reset_conversation_lock_backend_for_tests()
    clear_conversations()
    clear_message_sid_cache()
    WhatsAppConversationSession.objects.all().delete()


def test_normalize_conversation_lock_key_uses_per_user_prefix():
    assert (
        normalize_conversation_lock_key("whatsapp:+923001234567")
        == "qualification:conversation_lock:whatsapp:+923001234567"
    )
    assert (
        normalize_conversation_lock_key("+923246271149")
        == "qualification:conversation_lock:whatsapp:+923246271149"
    )
    assert normalize_conversation_lock_key(WHATSAPP_A) != normalize_conversation_lock_key(WHATSAPP_B)


def test_same_user_parallel_message_sids_are_serialized():
    concurrent = {"active": 0, "max": 0}
    lock = threading.Lock()
    start_barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def slow_handler(**kwargs):
        with lock:
            concurrent["active"] += 1
            concurrent["max"] = max(concurrent["max"], concurrent["active"])
        time.sleep(0.15)
        with lock:
            concurrent["active"] -= 1
        return _turn_response(reply_text=f"reply-{kwargs['message_sid']}")

    service = _service(slow_handler)
    results: list[dict] = []

    def run_turn(payload: dict) -> None:
        try:
            start_barrier.wait()
            results.append(service.run_turn(payload))
        except BaseException as exc:
            errors.append(exc)

    with _db_free_extract_patches():
        thread_a = _thread_worker(
            run_turn,
            _text_payload(whatsapp_number=WHATSAPP_A, message="first", message_sid=MESSAGE_SID_A),
        )
        thread_b = _thread_worker(
            run_turn,
            _text_payload(whatsapp_number=WHATSAPP_A, message="second", message_sid=MESSAGE_SID_B),
        )
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=5)
        thread_b.join(timeout=5)

    assert not errors
    assert concurrent["max"] == 1
    assert len(results) == 2
    replies = {item["reply_text"] for item in results}
    assert replies == {"reply-SM0cc5a1d9e22bf9850ca24261ee23cef1", "reply-SM1dd6b2e0f33cg0961db35372ff34deg2"}


def test_different_users_process_concurrently():
    concurrent = {"active": 0, "max": 0}
    state_lock = threading.Lock()
    start_barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def slow_handler(**kwargs):
        with state_lock:
            concurrent["active"] += 1
            concurrent["max"] = max(concurrent["max"], concurrent["active"])
        time.sleep(0.15)
        with state_lock:
            concurrent["active"] -= 1
        return _turn_response(reply_text=f"reply-{kwargs['whatsapp_number']}")

    service = _service(slow_handler)
    results: list[dict] = []

    def run_turn(payload: dict) -> None:
        try:
            start_barrier.wait()
            results.append(service.run_turn(payload))
        except BaseException as exc:
            errors.append(exc)

    with _db_free_extract_patches():
        thread_a = _thread_worker(
            run_turn,
            _text_payload(whatsapp_number=WHATSAPP_A, message="a", message_sid=MESSAGE_SID_A),
        )
        thread_b = _thread_worker(
            run_turn,
            _text_payload(whatsapp_number=WHATSAPP_B, message="b", message_sid=MESSAGE_SID_B),
        )
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=5)
        thread_b.join(timeout=5)

    assert not errors
    assert concurrent["max"] == 2
    assert len(results) == 2


@override_settings(QUALIFICATION_CONVERSATION_LOCK_WAIT_SECONDS=0.05)
def test_lock_timeout_returns_silent_http_payload():
    lock_key = normalize_conversation_lock_key(WHATSAPP_A)
    holder = acquire_conversation_turn_lock(lock_key)
    assert holder.acquired is True

    try:
        service = _service(MagicMock(return_value=_turn_response()))
        result = service.run_turn(
            _text_payload(
                whatsapp_number=WHATSAPP_A,
                message="queued",
                message_sid=MESSAGE_SID_B,
            )
        )
    finally:
        holder.release()

    assert result["reply_text"] == ""
    assert result["spoken_text"] == ""
    assert result["whatsapp_text"] == ""
    assert result["duplicate_or_locked"] is True
    assert result["lock_timeout"] is True
    assert result["tts_enqueued"] is False
    assert result["complete"] is False


def test_lock_is_released_after_turn_handler_exception():
    failing = MagicMock(side_effect=QualificationServiceRequestError("boom"))
    service = _service(failing)

    with _db_free_extract_patches():
        with pytest.raises(QualificationServiceRequestError):
            service.run_turn(
                _text_payload(
                    whatsapp_number=WHATSAPP_A,
                    message="fail",
                    message_sid=MESSAGE_SID_A,
                )
            )

        success = MagicMock(return_value=_turn_response(reply_text="recovered"))
        result = _service(success).run_turn(
            _text_payload(
                whatsapp_number=WHATSAPP_A,
                message="retry",
                message_sid=MESSAGE_SID_B,
            )
        )
    assert result["reply_text"] == "recovered"
    success.assert_called_once()


def test_message_sid_idempotency_still_returns_cached_response():
    payload = _turn_response(reply_text="cached-once")
    cache_turn_response(MESSAGE_SID_A, payload)
    turn_handler = MagicMock(return_value=_turn_response(reply_text="should-not-run"))

    result = _service(turn_handler).run_turn(
        _text_payload(
            whatsapp_number=WHATSAPP_A,
            message="duplicate",
            message_sid=MESSAGE_SID_A,
        )
    )

    assert result["reply_text"] == "cached-once"
    turn_handler.assert_not_called()
    assert begin_idempotent_turn(MESSAGE_SID_A) == payload


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.services.extract_service.VoiceNoteTranscriptionService")
def test_voice_and_text_close_together_for_same_user_are_serialized(mock_transcription_cls):
    transcription = MagicMock()
    transcription.transcribe.return_value = "voice transcript"
    mock_transcription_cls.return_value = transcription

    concurrent = {"active": 0, "max": 0}
    state_lock = threading.Lock()
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def slow_handler(**kwargs):
        with state_lock:
            concurrent["active"] += 1
            concurrent["max"] = max(concurrent["max"], concurrent["active"])
        time.sleep(0.15)
        with state_lock:
            concurrent["active"] -= 1
        return _turn_response(reply_text=f"reply-{kwargs.get('message_sid')}")

    service = _service(slow_handler)
    results: list[dict] = []

    def run_text() -> None:
        try:
            barrier.wait()
            results.append(
                service.run_turn(
                    _text_payload(
                        whatsapp_number=WHATSAPP_A,
                        message="text message",
                        message_sid=MESSAGE_SID_A,
                    )
                )
            )
        except BaseException as exc:
            errors.append(exc)

    def run_voice() -> None:
        try:
            barrier.wait()
            results.append(
                service.run_turn(
                    {
                        "whatsapp_number": WHATSAPP_A,
                        "message": None,
                        "input_channel": "whatsapp_voice_note",
                        "message_sid": MESSAGE_SID_B,
                        "media_url": "https://waha.example.com/api/files/true_923246271149@c.us_VOICE001.ogg",
                        "media_content_type": "audio/ogg"}
                )
            )
        except BaseException as exc:
            errors.append(exc)

    with _db_free_extract_patches():
        text_thread = _thread_worker(run_text)
        voice_thread = _thread_worker(run_voice)
        text_thread.start()
        voice_thread.start()
        text_thread.join(timeout=5)
        voice_thread.join(timeout=5)

    assert not errors
    assert concurrent["max"] == 1
    assert len(results) == 2


def test_render_audio_skips_empty_spoken_text():
    renderer = MagicMock()
    result = RenderAudioService(renderer=renderer).render(
        {
            "text": "   ",
            "whatsapp_number": WHATSAPP_A}
    )
    assert result["status"] == "skipped_empty"
    assert result["media_url"] is None
    renderer.assert_not_called()


def test_build_conversation_lock_timeout_response_has_no_fallback_copy():
    payload = build_conversation_lock_timeout_response(
        whatsapp_number=WHATSAPP_A,
        input_channel="whatsapp_text",
    )
    assert payload["reply_text"] == ""
    assert "processing it now" not in payload["reply_text"]


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
def test_lock_timeout_extract_endpoint_returns_http_200(client):
    lock_key = normalize_conversation_lock_key(WHATSAPP_A)
    holder = acquire_conversation_turn_lock(lock_key)
    assert holder.acquired is True
    try:
        with override_settings(QUALIFICATION_CONVERSATION_LOCK_WAIT_SECONDS=0.05):
            response = client.post(
                ENDPOINT_PATH,
                data=_text_payload(
                    whatsapp_number=WHATSAPP_A,
                    message="blocked",
                    message_sid=MESSAGE_SID_B,
                ),
                content_type="application/json",
                **internal_api_auth_headers(),
            )
    finally:
        holder.release()

    body = response.json()
    assert response.status_code == 200
    assert body["lock_timeout"] is True
    assert body["reply_text"] == ""


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
def test_lock_timeout_does_not_trigger_render_audio(client):
    lock_key = normalize_conversation_lock_key(WHATSAPP_A)
    holder = acquire_conversation_turn_lock(lock_key)
    assert holder.acquired is True
    try:
        with override_settings(QUALIFICATION_CONVERSATION_LOCK_WAIT_SECONDS=0.05):
            extract_response = client.post(
                ENDPOINT_PATH,
                data=_text_payload(
                    whatsapp_number=WHATSAPP_A,
                    message="blocked",
                    message_sid=MESSAGE_SID_B,
                ),
                content_type="application/json",
                **internal_api_auth_headers(),
            )
    finally:
        holder.release()

    extract_body = extract_response.json()
    assert extract_body["spoken_text"] == ""
    assert extract_body.get("tts_enqueued") is False

    render_response = client.post(
        RENDER_ENDPOINT,
        data={"text": "", "whatsapp_number": WHATSAPP_A},
        content_type="application/json",
        **internal_api_auth_headers(),
    )
    render_body = render_response.json()
    assert render_response.status_code == 200
    assert render_body["status"] == "skipped_empty"
    assert render_body["media_url"] is None
