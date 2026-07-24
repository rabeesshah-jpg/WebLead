"""Tests for WhatsApp main menu via WAHA compatibility shim."""

from __future__ import annotations

from unittest.mock import patch

from django.test import override_settings

from apps.qualification.integrations.twilio_whatsapp_menu import send_whatsapp_menu


@override_settings(
    WAHA_BASE_URL="https://waha.example.com",
    WAHA_API_KEY="test-waha-api-key",
)
@patch(
    "apps.whatsapp.message_service.waha_client.send_list",
    return_value="waha-menu-1",
)
def test_send_whatsapp_menu_uses_waha_list(mock_list):
    message_id = send_whatsapp_menu(to_number="+15551234567")
    assert message_id == "waha-menu-1"
    mock_list.assert_called_once()
