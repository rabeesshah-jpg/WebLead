"""Tests for WAHA outbound message helpers."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import override_settings

from apps.whatsapp.message_service import (
    send_language_picker,
    send_referral_source_list,
    send_whatsapp_menu,
    send_whatsapp_message,
)
from apps.whatsapp.waha_client import WahaApiError


@override_settings(
    WAHA_BASE_URL="https://waha.example.com",
    WAHA_API_KEY="test-waha-api-key",
    WAHA_SESSION="default",
)
@patch("apps.whatsapp.message_service.waha_client.send_text", return_value="msg-1")
def test_send_whatsapp_message(mock_send):
    assert send_whatsapp_message("+923246271149", "Hello") == "msg-1"
    mock_send.assert_called_once()


@override_settings(
    WAHA_BASE_URL="https://waha.example.com",
    WAHA_API_KEY="test-waha-api-key",
)
@patch("apps.whatsapp.message_service.waha_client.send_buttons", return_value="btn-1")
def test_send_language_picker_uses_buttons(mock_buttons):
    assert send_language_picker(to_number="+923246271149") == "btn-1"
    kwargs = mock_buttons.call_args.kwargs
    assert kwargs["buttons"][0]["id"] == "lang_en"
    assert kwargs["buttons"][1]["id"] == "lang_ar"


@override_settings(
    WAHA_BASE_URL="https://waha.example.com",
    WAHA_API_KEY="test-waha-api-key",
)
@patch(
    "apps.whatsapp.message_service.waha_client.send_buttons",
    side_effect=WahaApiError("not implemented", status_code=501),
)
@patch("apps.whatsapp.message_service.waha_client.send_text", return_value="fallback-1")
def test_send_language_picker_falls_back_to_text(mock_text, _mock_buttons):
    assert send_language_picker(to_number="+923246271149") == "fallback-1"
    mock_text.assert_called_once()


@override_settings(
    WAHA_BASE_URL="https://waha.example.com",
    WAHA_API_KEY="test-waha-api-key",
)
@patch("apps.whatsapp.message_service.waha_client.send_list", return_value="list-1")
def test_send_whatsapp_menu_and_referral_lists(mock_list):
    assert send_whatsapp_menu(to_number="+923246271149") == "list-1"
    assert send_referral_source_list(to_number="+923246271149") == "list-1"
    assert mock_list.call_count == 2
    first_sections = mock_list.call_args_list[0].kwargs["sections"]
    row_ids = [row["rowId"] for row in first_sections[0]["rows"]]
    assert "continue" in row_ids
