"""Parse and validate structured extraction responses."""

from __future__ import annotations

import json
import logging
from typing import Any

from apps.qualification.domain.llm_json_repair import (
    build_llm_json_parse_candidates,
    safe_raw_response_prefix,
)
from apps.qualification.models import ExtractionConfidence, QualificationExtraction
from apps.qualification.schema import CONFIDENCE_FIELD_NAMES, QUALIFICATION_FIELD_NAMES

from apps.qualification.domain.validators import E164_PHONE_PATTERN, is_valid_e164_phone_number

logger = logging.getLogger("apps.qualification")

_ROOT_FIELD_NAMES = frozenset(
    {
        *QUALIFICATION_FIELD_NAMES,
        "human_handoff_requested",
        "confidence",
    }
)


class ExtractionParseError(ValueError):
    """Raised when model output does not match the extraction contract."""


def _require_key(payload: dict[str, Any], key: str) -> Any:
    if key not in payload:
        raise ExtractionParseError(f"Missing required field: {key}")
    return payload[key]


def _parse_non_empty_optional_str(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ExtractionParseError(f"{field} must be a string or null")
    stripped = value.strip()
    if not stripped:
        raise ExtractionParseError(f"{field} must be a non-empty string or null")
    return stripped


def _parse_project_type(value: Any) -> str | None:
    if value is None:
        return None
    if value not in ("new_website", "website_upgrade", "new_and_upgrade"):
        raise ExtractionParseError(
            "project_type must be new_website, website_upgrade, new_and_upgrade, or null"
        )
    return value


def _parse_optional_bool(value: Any, field: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ExtractionParseError(f"{field} must be a boolean or null")
    return value


def _parse_preferred_phone(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ExtractionParseError("preferred_phone must be a string or null")
    normalized = "".join(value.split())
    if not normalized:
        return None
    if not is_valid_e164_phone_number(normalized):
        raise ExtractionParseError("preferred_phone must be a valid E.164 number or null")
    return normalized


def _parse_confidence_score(score: Any, field: str) -> float:
    if isinstance(score, bool):
        raise ExtractionParseError(f"confidence.{field} must be a number")
    if not isinstance(score, (int, float)):
        raise ExtractionParseError(f"confidence.{field} must be a number")
    score_f = float(score)
    if score_f < 0.0 or score_f > 1.0:
        raise ExtractionParseError(f"confidence.{field} must be between 0.0 and 1.0")
    return score_f


def _parse_confidence(value: Any) -> ExtractionConfidence:
    if not isinstance(value, dict):
        raise ExtractionParseError("confidence must be an object")

    extra_keys = set(value) - set(CONFIDENCE_FIELD_NAMES)
    if extra_keys:
        raise ExtractionParseError(f"Unexpected confidence fields: {sorted(extra_keys)}")

    scores: dict[str, float] = {}
    for field in CONFIDENCE_FIELD_NAMES:
        score = _require_key(value, field)
        scores[field] = _parse_confidence_score(score, field)

    return ExtractionConfidence(**scores)


def _validate_null_field_confidence_pairing(
    *,
    project_type: str | None,
    requirements: str | None,
    referral_source: str | None,
    whatsapp_confirmed: bool | None,
    preferred_phone: str | None,
    confidence: ExtractionConfidence,
) -> None:
    field_values = {
        "project_type": project_type,
        "requirements": requirements,
        "referral_source": referral_source,
        "whatsapp_confirmed": whatsapp_confirmed,
        "preferred_phone": preferred_phone,
    }
    for field, value in field_values.items():
        score = getattr(confidence, field)
        if value is None and score != 0.0:
            raise ExtractionParseError(f"confidence.{field} must be 0.0 when {field} is null")


def parse_extraction_payload(payload: dict[str, Any]) -> QualificationExtraction:
    """Validate and normalize a structured extraction payload."""
    if not isinstance(payload, dict):
        raise ExtractionParseError("Extraction response must be a JSON object")

    extra_keys = set(payload) - _ROOT_FIELD_NAMES
    if extra_keys:
        raise ExtractionParseError(f"Unexpected fields: {sorted(extra_keys)}")

    for field in QUALIFICATION_FIELD_NAMES:
        _require_key(payload, field)
    _require_key(payload, "human_handoff_requested")
    _require_key(payload, "confidence")

    handoff = payload["human_handoff_requested"]
    if not isinstance(handoff, bool):
        raise ExtractionParseError("human_handoff_requested must be a boolean")

    project_type = _parse_project_type(payload["project_type"])
    requirements = _parse_non_empty_optional_str(payload["requirements"], "requirements")
    referral_source = _parse_non_empty_optional_str(payload["referral_source"], "referral_source")
    whatsapp_confirmed = _parse_optional_bool(payload["whatsapp_confirmed"], "whatsapp_confirmed")
    preferred_phone = _parse_preferred_phone(payload["preferred_phone"])
    confidence = _parse_confidence(payload["confidence"])

    _validate_null_field_confidence_pairing(
        project_type=project_type,
        requirements=requirements,
        referral_source=referral_source,
        whatsapp_confirmed=whatsapp_confirmed,
        preferred_phone=preferred_phone,
        confidence=confidence,
    )

    return QualificationExtraction(
        project_type=project_type,
        requirements=requirements,
        referral_source=referral_source,
        whatsapp_confirmed=whatsapp_confirmed,
        preferred_phone=preferred_phone,
        human_handoff_requested=handoff,
        confidence=confidence,
    )


def _log_llm_parse_event(*, event_name: str, **context: Any) -> None:
    payload = {"event": event_name, **context}
    logger.info(json.dumps(payload, separators=(",", ":")))


def parse_extraction_json(
    raw_json: str,
    *,
    message_sid: str | None = None,
) -> QualificationExtraction:
    """Parse and validate raw JSON text from a model extraction response."""
    raw_response_length = len(raw_json)
    raw_response_prefix = safe_raw_response_prefix(raw_json)
    candidates = build_llm_json_parse_candidates(raw_json)
    parse_repair_attempted = len(candidates) > 1 or candidates[0] != raw_json.strip()

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if not isinstance(parsed, dict):
            last_error = ExtractionParseError("Extraction response must be a JSON object")
            continue
        try:
            result = parse_extraction_payload(parsed)
        except ExtractionParseError as exc:
            last_error = exc
            continue
        if parse_repair_attempted:
            _log_llm_parse_event(
                event_name="llm_extraction_parse_repaired",
                message_sid=message_sid,
                raw_response_prefix=raw_response_prefix,
                raw_response_length=raw_response_length,
                parse_repair_attempted=True,
                parse_repair_success=True,
                llm_parse_failed=False,
            )
        return result

    _log_llm_parse_event(
        event_name="llm_extraction_parse_failed",
        message_sid=message_sid,
        raw_response_prefix=raw_response_prefix,
        raw_response_length=raw_response_length,
        parse_repair_attempted=parse_repair_attempted,
        parse_repair_success=False,
        llm_parse_failed=True,
        error_type=type(last_error).__name__ if last_error else "ExtractionParseError",
    )
    if isinstance(last_error, ExtractionParseError):
        raise last_error
    raise ExtractionParseError("Invalid JSON in extraction response") from last_error
