"""Unit tests for WhatsApp menu command and payload parsing."""

from __future__ import annotations

import pytest

from apps.qualification.domain.whatsapp_menu_commands import (
    parse_menu_button_payload,
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


def test_menu_command_still_parses():
    resolved = resolve_menu_action(message="menu")
    assert resolved is not None
    assert resolved.kind == "command"
    assert resolved.command == "show_menu"
