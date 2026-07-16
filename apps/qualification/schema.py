"""JSON Schema for lead-qualification structured extraction."""

from __future__ import annotations

EXTRACTION_JSON_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "project_type",
        "requirements",
        "referral_source",
        "whatsapp_confirmed",
        "preferred_phone",
        "human_handoff_requested",
        "confidence",
    ],
    "properties": {
        "project_type": {
            "type": ["string", "null"],
            "enum": ["new_website", "website_upgrade", "new_and_upgrade", None],
        },
        "requirements": {
            "type": ["string", "null"],
            "minLength": 1,
        },
        "referral_source": {
            "type": ["string", "null"],
            "minLength": 1,
        },
        "whatsapp_confirmed": {
            "type": ["boolean", "null"],
        },
        "preferred_phone": {
            "type": ["string", "null"],
            "pattern": r"^\+[1-9][0-9]{7,14}$",
        },
        "human_handoff_requested": {
            "type": "boolean",
        },
        "confidence": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "project_type",
                "requirements",
                "referral_source",
                "whatsapp_confirmed",
                "preferred_phone",
            ],
            "properties": {
                "project_type": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "requirements": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "referral_source": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "whatsapp_confirmed": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "preferred_phone": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
            },
        },
    },
}

QUALIFICATION_FIELD_NAMES: tuple[str, ...] = (
    "project_type",
    "requirements",
    "referral_source",
    "whatsapp_confirmed",
    "preferred_phone",
)

CONFIDENCE_FIELD_NAMES: tuple[str, ...] = QUALIFICATION_FIELD_NAMES
