"""Tests for extract failure logging helpers."""

from __future__ import annotations

import json
import logging

from apps.qualification.domain.extract_errors import ExtractFailureInfo
from apps.qualification.domain.extract_logging import log_extract_step_failed


def test_log_extract_step_failed_emits_safe_structured_payload(caplog):
    info = ExtractFailureInfo(
        failure_step="deepgram_transcription_failed",
        public_message="Voice transcription failed.",
        error_type="DeepgramTimeoutError",
        status_code=None,
        duration_ms=1200,
        details="Deepgram request timed out",
    )

    with caplog.at_level(logging.ERROR, logger="apps.qualification"):
        log_extract_step_failed(info, message_sid="MM0cc5a1d9e22bf9850ca24261ee23ce90")

    payload = json.loads(caplog.records[-1].message)
    assert payload == {
        "step": "deepgram_transcription_failed",
        "message_sid": "MM0cc5a1d9e22bf9850ca24261ee23ce90",
        "error_type": "DeepgramTimeoutError",
        "duration_ms": 1200,
        "details": "Deepgram request timed out",
    }
