"""Unit tests for centralized WhatsApp menu configuration."""

from __future__ import annotations

import pytest

from apps.qualification.domain.whatsapp_menu_config import (
    MENU_ITEMS,
    handle_menu_selection,
    resolve_menu_item_id,
)


@pytest.mark.parametrize(
    ("menu_id", "expected_action"),
    [
        ("continue", "continue"),
        ("restart", "restart"),
        ("language", "change_language"),
        ("human", "human_handoff"),
    ],
)
def test_handle_menu_selection_maps_stable_ids(menu_id: str, expected_action: str):
    assert handle_menu_selection(menu_id) == expected_action


@pytest.mark.parametrize(
    ("payload", "expected_menu_id"),
    [
        ("continue", "continue"),
        ("menu_continue", "continue"),
        ("menu_language", "language"),
        ("language", "language"),
        ("change language", "language"),
        ("Change language\nEnglish / Arabic", "language"),
    ],
)
def test_resolve_menu_item_id_supports_new_and_legacy_payloads(payload: str, expected_menu_id: str):
    assert resolve_menu_item_id(button_payload=payload) == expected_menu_id


def test_menu_items_define_list_picker_labels():
    labels = {item["label"] for item in MENU_ITEMS}
    assert "Continue current conversation" in labels
    assert "Change language\nEnglish / Arabic" in labels
    assert "Talk to human" in labels
