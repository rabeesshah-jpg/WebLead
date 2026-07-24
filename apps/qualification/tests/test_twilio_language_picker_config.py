"""Tests for language-picker via WAHA compatibility shim."""

from __future__ import annotations

from unittest.mock import patch

from django.conf import settings
from django.test import override_settings

from apps.qualification.integrations.twilio_language_picker import send_language_picker


def test_waha_settings_present_in_tests():
    assert settings.WAHA_BASE_URL
    assert settings.WAHA_API_KEY


@override_settings(
    WAHA_BASE_URL="https://waha.example.com",
    WAHA_API_KEY="test-waha-api-key",
)
@patch(
    "apps.whatsapp.message_service.waha_client.send_buttons",
    return_value="waha-lang-1",
)
def test_send_language_picker_uses_waha_buttons(mock_buttons):
    message_id = send_language_picker(to_number="+15551234567")
    assert message_id == "waha-lang-1"
    mock_buttons.assert_called_once()
