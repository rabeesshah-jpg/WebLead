"""Shared pytest fixtures for qualification tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def mock_twilio_booking_link_send():
    """Prevent real Twilio sends while exercising booking-link delivery logic."""
    with patch(
        "apps.qualification.services.booking_link_delivery_service.send_booking_link_whatsapp_text",
        return_value="SMbookinglink0000000000000001",
    ) as mock_send:
        yield mock_send


@pytest.fixture(autouse=True)
def mock_language_picker_send():
    """Prevent real Twilio language-picker sends during extract/menu API tests."""
    with patch(
        "apps.qualification.services.language_gate_service.send_language_picker",
        return_value="SMpicker000000000000000000000001",
    ) as mock_send:
        yield mock_send
