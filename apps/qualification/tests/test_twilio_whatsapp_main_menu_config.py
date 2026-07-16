"""Tests for Twilio list-picker WhatsApp main menu configuration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.conf import settings
from django.test import override_settings

from apps.qualification.integrations.twilio_whatsapp_menu import (
    TwilioWhatsAppMenuConfigurationError,
    TwilioWhatsAppMenuSendError,
    send_whatsapp_menu,
)


@override_settings(TWILIO_WHATSAPP_MENU_CONTENT_SID="")
def test_twilio_whatsapp_menu_content_sid_defaults_empty_in_tests():
    assert settings.TWILIO_WHATSAPP_MENU_CONTENT_SID == ""


@override_settings(
    TWILIO_WHATSAPP_MENU_CONTENT_SID="HXtestmainmenucontentsid00000000",
    TWILIO_ACCOUNT_SID="ACtesttwilioaccountsidthirtyfour",
    TWILIO_AUTH_TOKEN="test-twilio-auth-token",
    TWILIO_WHATSAPP_FROM_NUMBER="whatsapp:+15557654321",
)
@patch("apps.qualification.integrations.twilio_whatsapp_menu.Client")
def test_send_whatsapp_menu_uses_configured_content_sid(mock_client_cls: MagicMock):
    mock_message = MagicMock()
    mock_message.sid = "SMmainmenusent0000000000000000"
    mock_message.status = "queued"
    mock_client_cls.return_value.messages.create.return_value = mock_message

    message_sid = send_whatsapp_menu(to_number="whatsapp:+15551234567")

    assert message_sid == "SMmainmenusent0000000000000000"
    mock_client_cls.return_value.messages.create.assert_called_once_with(
        from_="whatsapp:+15557654321",
        to="whatsapp:+15551234567",
        content_sid="HXtestmainmenucontentsid00000000",
    )


@override_settings(
    TWILIO_WHATSAPP_MENU_CONTENT_SID="",
    TWILIO_ACCOUNT_SID="ACtesttwilioaccountsidthirtyfour",
    TWILIO_AUTH_TOKEN="test-twilio-auth-token",
    TWILIO_WHATSAPP_FROM_NUMBER="whatsapp:+15557654321",
)
def test_send_whatsapp_menu_raises_when_content_sid_missing():
    with pytest.raises(TwilioWhatsAppMenuConfigurationError, match="TWILIO_WHATSAPP_MENU_CONTENT_SID"):
        send_whatsapp_menu(to_number="whatsapp:+15551234567")


@override_settings(
    TWILIO_WHATSAPP_MENU_CONTENT_SID="HXtestmainmenucontentsid00000000",
    TWILIO_ACCOUNT_SID="ACtesttwilioaccountsidthirtyfour",
    TWILIO_AUTH_TOKEN="test-twilio-auth-token",
    TWILIO_WHATSAPP_FROM_NUMBER="whatsapp:+15557654321",
)
@patch("apps.qualification.integrations.twilio_whatsapp_menu.Client")
def test_send_whatsapp_menu_raises_on_twilio_api_failure(mock_client_cls: MagicMock):
    mock_client_cls.return_value.messages.create.side_effect = RuntimeError("twilio down")

    with pytest.raises(TwilioWhatsAppMenuSendError, match="Twilio WhatsApp menu send failed"):
        send_whatsapp_menu(to_number="whatsapp:+15551234567")
