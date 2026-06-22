"""Parse and validate structured extraction responses."""

from __future__ import annotations

from typing import Any

from apps.qualification.models import ExtractionConfidence, QualificationExtraction
from apps.qualification.schema import CONFIDENCE_FIELD_NAMES, QUALIFICATION_FIELD_NAMES


class ExtractionParseError(ValueError):
    """Raised when model output does not match the extraction contract."""


def _require_key(payload: dict[str, Any], key: str) -> Any:
    if key not in payload:
        raise ExtractionParseError(f"Missing required field: {key}")
    return payload[key]


def _parse_optional_str(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ExtractionParseError(f"{field} must be a string or null")
    stripped = value.strip()
    return stripped if stripped else None


def _parse_project_type(value: Any) -> str | None:
    if value is None:
        return None
    if value not in ("new_website", "website_upgrade"):
        raise ExtractionParseError("project_type must be new_website, website_upgrade, or null")
    return value


def _parse_optional_bool(value: Any, field: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ExtractionParseError(f"{field} must be a boolean or null")
    return value


def _parse_confidence(value: Any) -> ExtractionConfidence:
    if not isinstance(value, dict):
        raise ExtractionParseError("confidence must be an object")

    scores: dict[str, float] = {}
    for field in CONFIDENCE_FIELD_NAMES:
        score = _require_key(value, field)
        if not isinstance(score, (int, float)):
            raise ExtractionParseError(f"confidence.{field} must be a number")
        score_f = float(score)
        if score_f < 0.0 or score_f > 1.0:
            raise ExtractionParseError(f"confidence.{field} must be between 0.0 and 1.0")
        scores[field] = score_f

    return ExtractionConfidence(**scores)


def parse_extraction_payload(payload: dict[str, Any]) -> QualificationExtraction:
    """Validate and normalize a structured extraction payload."""
    extra_keys = set(payload) - {
        *QUALIFICATION_FIELD_NAMES,
        "human_handoff_requested",
        "confidence",
    }
    if extra_keys:
        raise ExtractionParseError(f"Unexpected fields: {sorted(extra_keys)}")

    for field in QUALIFICATION_FIELD_NAMES:
        _require_key(payload, field)
    _require_key(payload, "human_handoff_requested")
    _require_key(payload, "confidence")

    handoff = payload["human_handoff_requested"]
    if not isinstance(handoff, bool):
        raise ExtractionParseError("human_handoff_requested must be a boolean")

    return QualificationExtraction(
        project_type=_parse_project_type(payload["project_type"]),
        requirements=_parse_optional_str(payload["requirements"], "requirements"),
        referral_source=_parse_optional_str(payload["referral_source"], "referral_source"),
        whatsapp_confirmed=_parse_optional_bool(
            payload["whatsapp_confirmed"],
            "whatsapp_confirmed",
        ),
        preferred_phone=_parse_optional_str(payload["preferred_phone"], "preferred_phone"),
        human_handoff_requested=handoff,
        confidence=_parse_confidence(payload["confidence"]),
    )
