"""Shared pytest fixtures for qualification tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def mock_twilio_booking_link_send():
    """Prevent real WhatsApp sends while exercising booking-link delivery logic."""
    with patch(
        "apps.qualification.services.booking_link_delivery_service.send_booking_link_whatsapp_text",
        return_value="SMbookinglink0000000000000001",
    ) as mock_send:
        yield mock_send


@pytest.fixture(autouse=True)
def mock_language_picker_send():
    """Prevent real language-picker sends during extract/menu API tests."""
    with patch(
        "apps.qualification.services.language_gate_service.send_language_picker",
        return_value="SMpicker000000000000000000000001",
    ) as mock_send:
        yield mock_send


@pytest.fixture(autouse=True)
def mock_waha_option_template_send():
    """Prevent real WAHA interactive sends when option_template is attached."""
    with patch(
        "apps.whatsapp.message_service.deliver_option_template",
        return_value="waha-option-1",
    ) as mock_send:
        yield mock_send


@pytest.fixture(autouse=True)
def mock_waha_menu_and_business_sends():
    """Prevent real WAHA list/button sends from menu and existing-customer paths."""
    with (
        patch(
            "apps.whatsapp.message_service.send_whatsapp_menu",
            return_value="waha-menu-1",
        ),
        patch(
            "apps.whatsapp.message_service.send_business_type_list",
            return_value="waha-biz-1",
        ),
        patch(
            "apps.whatsapp.waha_client.send_text",
            return_value="waha-text-1",
        ),
        patch(
            "apps.whatsapp.waha_client.send_buttons",
            return_value="waha-btn-1",
        ),
        patch(
            "apps.whatsapp.waha_client.send_list",
            return_value="waha-list-1",
        ),
    ):
        yield
