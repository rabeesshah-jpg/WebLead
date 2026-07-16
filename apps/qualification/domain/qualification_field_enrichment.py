"""Apply inbound message classification to persisted qualification fields."""

from __future__ import annotations

import re
from typing import Any

from apps.qualification.domain.inbound_message_classification import (
    InboundMessageClassification,
    infer_project_type_from_services,
)

VALID_PROJECT_TYPES = frozenset({"new_website", "website_upgrade", "new_and_upgrade"})


def _normalize_service_token(token: str) -> str:
    return token


def merge_services_required(
    existing: list[str] | tuple[str, ...] | None,
    new_tokens: tuple[str, ...],
) -> list[str]:
    """Merge service tokens without duplicates, preserving order."""
    merged: list[str] = []
    seen: set[str] = set()
    for token in list(existing or ()) + list(new_tokens):
        normalized = _normalize_service_token(token)
        if normalized in seen:
            continue
        seen.add(normalized)
        merged.append(normalized)
    return merged


def _normalize_requirement_text(value: str) -> str:
    cleaned = " ".join(value.split()).strip()
    return cleaned.rstrip(".,!?;:\"'").strip().lower()


def merge_requirements(existing: str | None, new_text: str) -> str:
    """Append requirement text without duplicating the same phrase."""
    cleaned = " ".join(new_text.split()).strip()
    if not cleaned:
        return existing or ""
    if not existing:
        return cleaned
    existing_normalized = _normalize_requirement_text(existing)
    cleaned_normalized = _normalize_requirement_text(cleaned)
    if cleaned_normalized in existing_normalized:
        return existing
    if existing_normalized in cleaned_normalized:
        return cleaned
    return f"{existing} {cleaned}".strip()


def infer_project_type_from_message(
    message: str,
    service_tokens: tuple[str, ...],
) -> str | None:
    """Infer project_type from message wording and detected service tokens."""
    normalized = message.lower()
    wants_new = bool(
        re.search(
            r"\bnew website\b|\bnew site\b|\bbrand new website\b|\bbuild a new one\b|\bnew one\b",
            normalized,
        )
    )
    wants_upgrade = bool(
        re.search(
            r"\bupgrade\b|\bexisting website\b|\bwebsite to upgrade\b",
            normalized,
        )
    )
    if wants_new and wants_upgrade:
        return "new_and_upgrade"
    return infer_project_type_from_services(service_tokens)


def apply_classification_to_fields(
    fields: dict[str, Any],
    classification: InboundMessageClassification,
) -> dict[str, Any]:
    """Return field updates derived from an inbound message classification."""
    if classification.is_small_talk_or_identity:
        return {}
    if not classification.service_request and not classification.requirement_detail:
        return {}

    updates: dict[str, Any] = {}
    message = classification.raw_message

    if classification.service_tokens:
        updates["services_required"] = merge_services_required(
            fields.get("services_required"),
            classification.service_tokens,
        )

    inferred = infer_project_type_from_message(message, classification.service_tokens)
    if inferred and not fields.get("project_type"):
        updates["project_type"] = inferred

    if classification.requirement_detail and message:
        updates["requirements"] = merge_requirements(fields.get("requirements"), message)

    normalized = message.lower()
    if "ecommerce" in normalized or "e-commerce" in normalized or "online store" in normalized:
        updates["website_type"] = "ecommerce"
        if not fields.get("project_type") and "project_type" not in updates:
            updates["project_type"] = "new_website"

    return updates
