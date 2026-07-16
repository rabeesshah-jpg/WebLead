"""Centralized WhatsApp main menu configuration and ID-to-action mapping."""

from __future__ import annotations

import re
from typing import Literal, TypedDict

MenuItemAction = Literal[
    "continue_conversation",
    "restart_qualification",
    "open_language_picker",
    "handoff_human",
]

MenuOptionAction = Literal["continue", "restart", "change_language", "human_handoff"]


class MenuItem(TypedDict):
    id: str
    label: str
    action: MenuItemAction


MENU_ITEMS: list[MenuItem] = [
    {
        "id": "continue",
        "label": "Continue current conversation",
        "action": "continue_conversation",
    },
    {
        "id": "restart",
        "label": "Restart qualification",
        "action": "restart_qualification",
    },
    {
        "id": "language",
        "label": "Change language\nEnglish / Arabic",
        "action": "open_language_picker",
    },
    {
        "id": "human",
        "label": "Talk to human",
        "action": "handoff_human",
    },
]

MENU_ITEM_BY_ID: dict[str, MenuItem] = {item["id"]: item for item in MENU_ITEMS}
MENU_ITEM_IDS: frozenset[str] = frozenset(MENU_ITEM_BY_ID)

_MENU_ACTION_TO_INTERNAL: dict[MenuItemAction, MenuOptionAction] = {
    "continue_conversation": "continue",
    "restart_qualification": "restart",
    "open_language_picker": "change_language",
    "handoff_human": "human_handoff",
}

# Legacy Twilio list-picker payloads retained for backward compatibility.
_LEGACY_BUTTON_PAYLOAD_TO_MENU_ID: dict[str, str] = {
    "menu_continue": "continue",
    "menu_restart": "restart",
    "menu_change_language": "language",
    "menu_human_handoff": "human",
    "menu_language": "language",
    "menu_human": "human",
}

MENU_LIST_HEADER = "Menu"
MENU_LIST_BODY = "Please choose an option"
MENU_LIST_BUTTON_LABEL = "Menu"
MENU_LIST_SECTION_TITLE = "Main Options"
MENU_INSTANCE_ID = "main"

_LANGUAGE_BODY_MARKER = "change language"


def normalize_menu_payload(value: str | None) -> str:
    """Lowercase, trim, and collapse whitespace/newlines for stable menu matching."""
    if value is None:
        return ""
    collapsed = re.sub(r"\s+", " ", value.strip())
    return collapsed.casefold()


def _menu_label_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for item in MENU_ITEMS:
        menu_id = item["id"]
        label = item["label"]
        aliases[normalize_menu_payload(label)] = menu_id
        first_line = label.split("\n", 1)[0].strip()
        if first_line:
            aliases[normalize_menu_payload(first_line)] = menu_id
    for legacy_payload, menu_id in _LEGACY_BUTTON_PAYLOAD_TO_MENU_ID.items():
        aliases[normalize_menu_payload(legacy_payload)] = menu_id
    return aliases


def menu_id_to_internal_action(menu_id: str) -> MenuOptionAction | None:
    """Map a stable menu item ID to the internal routing action."""
    item = MENU_ITEM_BY_ID.get(menu_id)
    if item is None:
        return None
    return _MENU_ACTION_TO_INTERNAL[item["action"]]


def resolve_menu_item_id(*, button_payload: str | None = None) -> str | None:
    """
    Resolve a list-picker payload or visible Body text to a canonical menu item ID.

    Language selections accept ``language``, ``change language``, the full label,
    and any body containing ``change language``.
    """
    if not button_payload:
        return None

    raw = button_payload.strip()
    if not raw:
        return None

    normalized = normalize_menu_payload(raw)
    if not normalized:
        return None

    for item_id in MENU_ITEM_IDS:
        if item_id.casefold() == normalized:
            return item_id

    legacy_match = _LEGACY_BUTTON_PAYLOAD_TO_MENU_ID.get(raw)
    if legacy_match is not None:
        return legacy_match
    legacy_match = _LEGACY_BUTTON_PAYLOAD_TO_MENU_ID.get(normalized)
    if legacy_match is not None:
        return legacy_match

    alias_match = _menu_label_aliases().get(normalized)
    if alias_match is not None:
        return alias_match

    if _LANGUAGE_BODY_MARKER in normalized:
        return "language"

    return None


def handle_menu_selection(menu_id: str) -> MenuOptionAction | None:
    """Map a stable menu item ID to the internal routing action."""
    return menu_id_to_internal_action(menu_id)
