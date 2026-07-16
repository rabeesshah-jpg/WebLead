"""Tests for Twilio language-picker configuration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.conf import settings
from django.test import override_settings

from apps.qualification.integrations.twilio_language_picker import (
    TwilioLanguagePickerConfigurationError,
    send_language_picker,
)


@override_settings(TWILIO_LANGUAGE_PICKER_CONTENT_SID="")
def test_twilio_language_picker_content_sid_defaults_empty_in_tests():
    assert settings.TWILIO_LANGUAGE_PICKER_CONTENT_SID == ""


def test_existing_twilio_auth_settings_unchanged():
    assert settings.TWILIO_AUTH_TOKEN == "test-twilio-auth-token"
    assert settings.TWILIO_ACCOUNT_SID == "ACtesttwilioaccountsidthirtyfour"


@override_settings(
    TWILIO_LANGUAGE_PICKER_CONTENT_SID="HXtestcontentsidfortest0000000000",
    TWILIO_ACCOUNT_SID="ACtesttwilioaccountsidthirtyfour",
    TWILIO_AUTH_TOKEN="test-twilio-auth-token",
    TWILIO_WHATSAPP_FROM_NUMBER="whatsapp:+15557654321",
)
@patch("apps.qualification.integrations.twilio_language_picker.Client")
def test_send_language_picker_uses_configured_content_sid(mock_client_cls: MagicMock):
    mock_message = MagicMock()
    mock_message.sid = "SMlanguagepickersent000000000000"
    mock_client_cls.return_value.messages.create.return_value = mock_message

    message_sid = send_language_picker(to_number="whatsapp:+15551234567")

    assert message_sid == "SMlanguagepickersent000000000000"
    mock_client_cls.return_value.messages.create.assert_called_once_with(
        from_="whatsapp:+15557654321",
        to="whatsapp:+15551234567",
        content_sid="HXtestcontentsidfortest0000000000",
    )


@override_settings(
    TWILIO_LANGUAGE_PICKER_CONTENT_SID="",
    TWILIO_ACCOUNT_SID="ACtesttwilioaccountsidthirtyfour",
    TWILIO_AUTH_TOKEN="test-twilio-auth-token",
    TWILIO_WHATSAPP_FROM_NUMBER="whatsapp:+15557654321",
)
def test_send_language_picker_raises_when_content_sid_missing():
    with pytest.raises(TwilioLanguagePickerConfigurationError):
        send_language_picker(to_number="whatsapp:+15551234567")
