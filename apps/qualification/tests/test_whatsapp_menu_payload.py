"""Unit tests for WhatsApp interactive menu payload extraction."""

from __future__ import annotations

import pytest

from apps.qualification.domain.whatsapp_menu_config import resolve_menu_item_id
from apps.qualification.domain.whatsapp_menu_payload import (
    extract_menu_selection_payload,
    normalize_menu_selection_token,
)


@pytest.mark.parametrize(
    ("request_data", "expected_menu_id"),
    [
        ({"button_payload": "language"}, "language"),
        ({"ButtonPayload": "language"}, "language"),
        ({"button_payload": "menu_language"}, "language"),
        ({"message": "language"}, "language"),
        ({"message": "Change language\nEnglish / Arabic"}, "language"),
        ({"message": "Change language"}, "language"),
        ({"message": "WebLead Connect: Please choose an option: Change language"}, "language"),
        (
            {
                "interactive_data": '{"data":{"context":{"buttonPayload":"language"}}}'},
            "language",
        ),
        (
            {
                "channel_metadata": (
                    '{"data":{"context":{"buttonPayload":"language","buttonType":"ACTION"}}}'
                )},
            "language",
        ),
    ],
)
def test_extract_menu_selection_payload_resolves_language_action(
    request_data: dict,
    expected_menu_id: str,
):
    menu_id, debug = extract_menu_selection_payload(request_data)
    assert menu_id == expected_menu_id
    assert debug["resolved_menu_item_id"] == expected_menu_id


def test_extract_menu_selection_payload_body_only_language_sets_fallback_used():
    menu_id, debug = extract_menu_selection_payload({"message": "language"})
    assert menu_id == "language"
    assert debug["fallback_used"] is True
    assert debug["raw_body"] == "language"
    assert debug["raw_button_payload"] is None


def test_extract_menu_selection_payload_button_payload_does_not_set_fallback_used():
    menu_id, debug = extract_menu_selection_payload({"button_payload": "language"})
    assert menu_id == "language"
    assert debug["fallback_used"] is False


def test_extract_menu_selection_payload_ignores_unrelated_body():
    menu_id, debug = extract_menu_selection_payload({"message": "I need a new website"})
    assert menu_id is None
    assert debug["resolved_menu_item_id"] is None
    assert debug["fallback_used"] is False


@pytest.mark.parametrize(
    ("body", "expected_menu_id"),
    [
        ("restart", "restart"),
        ("continue", "continue"),
        ("human", "human"),
    ],
)
def test_extract_menu_selection_payload_resolves_other_menu_ids_without_misclassifying_language(
    body: str,
    expected_menu_id: str,
):
    menu_id, debug = extract_menu_selection_payload({"message": body})
    assert menu_id == expected_menu_id
    assert menu_id != "language"
    assert debug["fallback_used"] is True


@pytest.mark.parametrize(
    ("payload", "expected_menu_id"),
    [
        ("language", "language"),
        ("Language", "language"),
        ("change language", "language"),
        ("change language english / arabic", "language"),
        ("Change language\nEnglish / Arabic", "language"),
        ("WebLead Connect: Please choose an option: Change language", "language"),
        ("I would like to change language please", "language"),
        ("restart", "restart"),
        ("continue", "continue"),
        ("human", "human"),
        ("random text", None),
    ],
)
def test_resolve_menu_item_id_maps_language_and_other_menu_patterns(
    payload: str,
    expected_menu_id: str | None,
):
    assert resolve_menu_item_id(button_payload=payload) == expected_menu_id


def test_normalize_menu_selection_token_collapses_newlines():
    assert normalize_menu_selection_token("Change language\nEnglish / Arabic") == (
        "change language english / arabic"
    )
