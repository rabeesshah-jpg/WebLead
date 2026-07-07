"""Parsing for WhatsApp menu and restart customer commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from apps.qualification.domain.language_selection import LANGUAGE_BUTTONS
from apps.qualification.domain.whatsapp_menu_config import (
    MenuOptionAction,
    menu_id_to_internal_action,
    resolve_menu_item_id,
)

MenuCommandAction = Literal["show_menu", "restart"]


@dataclass(frozen=True)
class ResolvedMenuAction:
    """Normalized menu routing decision from list-picker payload or typed command."""

    kind: Literal["command", "option"]
    command: MenuCommandAction | None = None
    option: MenuOptionAction | None = None
    menu_id: str | None = None
    source: Literal["button", "text"] = "text"


_MENU_COMMANDS: frozenset[str] = frozenset(
    {
        "menu",
        "/menu",
        "start",
        "/start",
    }
)
_RESTART_COMMANDS: frozenset[str] = frozenset(
    {
        "restart",
        "/restart",
    }
)


def _normalize_command_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.strip().split())


def parse_whatsapp_menu_command(value: str | None) -> MenuCommandAction | None:
    """
    Parse explicit menu or restart commands.

    ``restart`` and ``/restart`` restart immediately. ``menu``, ``/menu``,
    ``start``, and ``/start`` trigger the interactive list-picker menu.
    """
    normalized = _normalize_command_text(value)
    if not normalized:
        return None

    lowered = normalized.casefold()
    if lowered in _RESTART_COMMANDS:
        return "restart"
    if lowered in _MENU_COMMANDS:
        return "show_menu"
    return None


def parse_menu_button_payload(value: str | None) -> MenuOptionAction | None:
    """Parse a Twilio list-picker payload for menu actions."""
    menu_id = resolve_menu_item_id(button_payload=_normalize_command_text(value))
    if menu_id is None:
        return None
    return menu_id_to_internal_action(menu_id)


def parse_menu_item_id(*, button_payload: str | None = None) -> str | None:
    """Return the canonical menu item ID from a list-picker button payload."""
    return resolve_menu_item_id(button_payload=_normalize_command_text(button_payload) or None)


def is_language_button_payload(value: str | None) -> bool:
    """Return True when the payload belongs to the language picker, not the main menu."""
    normalized = _normalize_command_text(value)
    return normalized in LANGUAGE_BUTTONS


def resolve_menu_action(
    *,
    button_payload: str | None = None,
    message: str | None = None,
) -> ResolvedMenuAction | None:
    """
    Normalize list-picker payloads and typed menu commands into one routing decision.

    Only interactive list-picker ``ButtonPayload`` values and explicit menu/restart
    commands are accepted. Plain numeric text replies are not supported.
    """
    normalized_payload = _normalize_command_text(button_payload)
    if normalized_payload:
        menu_id = resolve_menu_item_id(button_payload=normalized_payload)
        if menu_id is not None:
            option = menu_id_to_internal_action(menu_id)
            if option is not None:
                return ResolvedMenuAction(
                    kind="option",
                    option=option,
                    menu_id=menu_id,
                    source="button",
                )

    normalized_message = _normalize_command_text(message)
    if not normalized_message:
        return None

    menu_command = parse_whatsapp_menu_command(normalized_message)
    if menu_command is not None:
        return ResolvedMenuAction(kind="command", command=menu_command, source="text")

    return None
