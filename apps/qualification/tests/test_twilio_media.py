"""Tests for Twilio media download helpers."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import override_settings

from apps.qualification.twilio_media import download_twilio_media

MEDIA_URL = "https://api.twilio.com/2010-04-01/Accounts/ACtest/Media/MEtestvoice001"


@override_settings(
    TWILIO_ACCOUNT_SID="ACtesttwilioaccountsidthirtyfour",
    TWILIO_AUTH_TOKEN="test-twilio-auth-token",
)
@patch("apps.qualification.twilio_media.urllib.request.urlopen")
def test_download_twilio_media_returns_bytes_and_content_type(mock_urlopen):
    class FakeResponse:
        headers = {"Content-Type": "audio/ogg"}
        _returned = False

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def read(self, size: int = -1) -> bytes:
            if self._returned:
                return b""
            self._returned = True
            return b"\x00" * 128

    mock_urlopen.return_value = FakeResponse()

    audio_bytes, content_type = download_twilio_media(MEDIA_URL)

    assert audio_bytes == b"\x00" * 128
    assert content_type == "audio/ogg"
