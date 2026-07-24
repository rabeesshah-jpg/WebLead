"""Tests for WAHA media download (compat shim download_twilio_media)."""

from __future__ import annotations

from unittest.mock import patch

from django.test import override_settings

from apps.qualification.twilio_media import download_twilio_media

MEDIA_URL = "https://waha.example.com/api/files/true_923246271149@c.us_VOICE001.ogg"


@override_settings(
    WAHA_BASE_URL="https://waha.example.com",
    WAHA_API_KEY="test-waha-api-key",
)
@patch("apps.whatsapp.waha_client.urllib.request.urlopen")
def test_download_waha_media_returns_bytes_and_content_type(mock_urlopen):
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
