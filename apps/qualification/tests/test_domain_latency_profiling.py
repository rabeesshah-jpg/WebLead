"""Tests for qualification latency profiling helpers."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from apps.qualification.domain.latency_profiling import (
    get_tracked_step_durations,
    log_latency_step,
    log_voice_turn_latency_summary,
    reset_step_duration_tracker,
    store_pending_voice_turn_summary,
)
from apps.qualification.persistence.cache_backend import reset_qualification_cache_backend_for_tests


@pytest.fixture(autouse=True)
def _reset_latency_state():
    reset_step_duration_tracker()
    reset_qualification_cache_backend_for_tests()
    yield
    reset_step_duration_tracker()
    reset_qualification_cache_backend_for_tests()


@patch("apps.qualification.domain.latency_profiling.logger")
def test_log_latency_step_emits_json_with_step_and_duration(mock_logger):
    log_latency_step(
        "twilio_media_download",
        42,
        message_sid="MM0cc5a1d9e22bf9850ca24261ee23ce90",
        media_url_present=True,
        audio_size_bytes=128,
        status="success",
    )

    payload = json.loads(mock_logger.info.call_args.args[0])
    assert payload["step"] == "twilio_media_download"
    assert payload["duration_ms"] == 42
    assert payload["message_sid"] == "MM0cc5a1d9e22bf9850ca24261ee23ce90"
    assert payload["status"] == "success"
    assert "media_url" not in payload


@patch("apps.qualification.domain.latency_profiling.logger")
def test_voice_turn_latency_summary_merges_extract_and_render_timings(mock_logger):
    message_sid = "MM0cc5a1d9e22bf9850ca24261ee23ce90"
    store_pending_voice_turn_summary(
        message_sid,
        step_durations={
            "twilio_media_download": 120,
            "deepgram_transcription": 450,
            "openrouter_call": 1800},
        extract_api_total_ms=2500,
    )

    log_voice_turn_latency_summary(
        message_sid,
        tts_generation_ms=900,
        render_api_total_ms=1100,
    )

    payload = json.loads(mock_logger.info.call_args.args[0])
    assert payload == {
        "step": "voice_turn_latency_summary",
        "message_sid": message_sid,
        "twilio_media_download_ms": 120,
        "deepgram_transcription_ms": 450,
        "openrouter_call_ms": 1800,
        "tts_generation_ms": 900,
        "api_total_ms": 3600}


def test_step_duration_tracker_records_summary_steps_only():
    log_latency_step("serializer_validation", 5, message_sid="MM123")
    log_latency_step("twilio_media_download", 10, message_sid="MM123")
    log_latency_step("deepgram_transcription", 20, message_sid="MM123")

    durations = get_tracked_step_durations()
    assert durations == {
        "twilio_media_download": 10,
        "deepgram_transcription": 20}
