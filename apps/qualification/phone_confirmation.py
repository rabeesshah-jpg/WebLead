"""Deterministic guardrails for phone-confirmation extraction fields."""

from __future__ import annotations

import re
from dataclasses import replace

from apps.qualification.models import ExtractionConfidence, QualificationExtraction

E164_IN_MESSAGE_PATTERN = re.compile(r"\+[1-9][0-9]{7,14}")

_CONFIRM_KNOWN_WHATSAPP_PHRASES = (
    "whatsapp number is the best",
    "this whatsapp number is the best",
    "this whatsapp number is",
    "this number is the best",
    "best number to reach me",
    "yes, this whatsapp",
    "use this whatsapp number",
    "use this number",
)

_REJECT_KNOWN_WHATSAPP_PHRASES = (
    "not the best number",
    "not the best",
    "don't use this number",
    "do not use this number",
    "different number",
    "another number",
    "contact me on +",
    "reach me on +",
    "please contact me on +",
)


def _normalize_phone(value: str) -> str:
    return "".join(value.split())


def _normalized_text(customer_message: str) -> str:
    return " ".join(customer_message.strip().lower().split())


def _phones_in_message(customer_message: str) -> frozenset[str]:
    normalized = "".join(customer_message.split())
    return frozenset(E164_IN_MESSAGE_PATTERN.findall(normalized))


def _is_bare_yes(customer_message: str) -> bool:
    normalized = _normalized_text(customer_message)
    return normalized in {"yes", "yes.", "yeah", "yeah."}


def _is_bare_no(customer_message: str) -> bool:
    normalized = _normalized_text(customer_message)
    return normalized in {"no", "no.", "nope", "nope."}


def _message_confirms_known_whatsapp(customer_message: str) -> bool:
    normalized = _normalized_text(customer_message)
    return any(phrase in normalized for phrase in _CONFIRM_KNOWN_WHATSAPP_PHRASES)


def _message_rejects_known_whatsapp(customer_message: str) -> bool:
    normalized = _normalized_text(customer_message)
    if normalized.startswith("no"):
        return True
    return any(phrase in normalized for phrase in _REJECT_KNOWN_WHATSAPP_PHRASES)


def _clear_phone_fields(extraction: QualificationExtraction) -> QualificationExtraction:
    return replace(
        extraction,
        whatsapp_confirmed=None,
        preferred_phone=None,
        confidence=replace(
            extraction.confidence,
            whatsapp_confirmed=0.0,
            preferred_phone=0.0,
        ),
    )


def apply_phone_confirmation_guard(
    extraction: QualificationExtraction,
    customer_message: str,
    known_whatsapp_number: str,
    *,
    phone_confirmation_question_asked: bool = False,
) -> QualificationExtraction:
    """Apply conservative phone-confirmation rules after model extraction."""
    if not phone_confirmation_question_asked:
        return _clear_phone_fields(extraction)

    known_phone = _normalize_phone(known_whatsapp_number)
    phones_in_message = _phones_in_message(customer_message)

    confirms = _message_confirms_known_whatsapp(customer_message)
    rejects = _message_rejects_known_whatsapp(customer_message)

    if _is_bare_yes(customer_message):
        confirms = True
        rejects = False
    elif _is_bare_no(customer_message):
        confirms = False
        rejects = True

    if confirms and rejects:
        return _clear_phone_fields(extraction)

    if confirms:
        return replace(
            extraction,
            whatsapp_confirmed=True,
            preferred_phone=known_phone,
            confidence=replace(
                extraction.confidence,
                whatsapp_confirmed=extraction.confidence.whatsapp_confirmed,
                preferred_phone=extraction.confidence.preferred_phone,
            ),
        )

    if rejects:
        preferred_phone = None
        phone_confidence = 0.0
        model_phone = extraction.preferred_phone
        if model_phone is not None:
            normalized_model_phone = _normalize_phone(model_phone)
            if normalized_model_phone in phones_in_message:
                preferred_phone = normalized_model_phone
                phone_confidence = extraction.confidence.preferred_phone

        if preferred_phone is None:
            alternate_phones = sorted(phone for phone in phones_in_message if phone != known_phone)
            if len(alternate_phones) == 1:
                preferred_phone = alternate_phones[0]
                phone_confidence = extraction.confidence.preferred_phone

        return replace(
            extraction,
            whatsapp_confirmed=False,
            preferred_phone=preferred_phone,
            confidence=replace(
                extraction.confidence,
                whatsapp_confirmed=extraction.confidence.whatsapp_confirmed,
                preferred_phone=phone_confidence,
            ),
        )

    return _clear_phone_fields(extraction)
