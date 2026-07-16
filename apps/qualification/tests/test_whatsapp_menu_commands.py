"""Unit tests for WhatsApp menu command and payload parsing."""

from __future__ import annotations

import pytest

from apps.qualification.domain.whatsapp_menu_commands import (
    is_menu_command,
    parse_menu_button_payload,
    parse_whatsapp_menu_command,
    resolve_menu_action,
)


@pytest.mark.parametrize(
    "payload",
    [
        "continue",
        "restart",
        "language",
        "human",
        "menu_continue",
        "menu_restart",
        "menu_change_language",
        "menu_human_handoff",
        "menu_language",
        "menu_human",
    ],
)
def test_menu_button_payloads_map_to_actions(payload: str):
    assert parse_menu_button_payload(payload) is not None


def test_numeric_text_is_not_treated_as_menu_selection():
    assert resolve_menu_action(message="1") is None
    assert resolve_menu_action(message="2") is None


@pytest.mark.parametrize(
    "message",
    [
        "M",
        " M ",
        "\nM\n",
    ],
)
def test_exact_uppercase_m_opens_menu(message: str):
    assert is_menu_command(message) is True
    assert parse_whatsapp_menu_command(message) == "show_menu"
    resolved = resolve_menu_action(message=message)
    assert resolved is not None
    assert resolved.kind == "command"
    assert resolved.command == "show_menu"


@pytest.mark.parametrize(
    "message",
    [
        "m",
        "menu",
        "Menu",
        "MENU",
        "/menu",
        "i need your menu",
        "menu please",
        "open menu",
        "can you show menu",
        "I want M",
        "M please",
        "start",
        "/start",
    ],
)
def test_non_exact_uppercase_m_does_not_open_menu(message: str):
    assert is_menu_command(message) is False
    assert parse_whatsapp_menu_command(message) is None
    assert resolve_menu_action(message=message) is None


@pytest.mark.parametrize(
    "message",
    [
        "restart",
        "/restart",
        "start over",
        "new inquiry",
        "begin again",
        "reset",
    ],
)
def test_restart_commands_are_recognized(message: str):
    assert parse_whatsapp_menu_command(message) == "restart"
