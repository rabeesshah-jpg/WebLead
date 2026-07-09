"""Deterministic inbound message classification for WhatsApp qualification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from apps.qualification.domain.confirmation_reply import (
    classify_whatsapp_confirmation_reply,
    normalize_confirmation_message,
)

ConfirmationReply = Literal["yes", "no", "unclear"]

SERVICE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bnew website\b|\bbrand new website\b|\bbuild a new website\b", "new_website"),
    (r"\bwebsite upgrade\b|\bupgrade (?:my |the |your )?website\b|\bexisting website\b|\bwebsite\b.*\bupgrade\b|\bupgrade\b.*\bwebsite\b", "website_upgrade"),
    (r"\bwebsite\b|\bweb site\b", "website"),
    (r"\bautomation\b", "automation"),
    (r"\bseo\b|\bsearch engine optimization\b", "seo"),
    (r"\bai chatbot\b|\bchatbot\b|\bchat bot\b", "ai_chatbot"),
    (r"\be[\s-]?commerce\b|\becommerce\b|\bonline store\b|\bonline shop\b", "ecommerce"),
)

QUESTION_SERVICES_PATTERNS: tuple[str, ...] = (
    r"what services do you provide",
    r"what do you (?:do|offer|provide)",
    r"which services",
    r"what can you help with",
)

QUESTION_LOCATION_PATTERNS: tuple[str, ...] = (
    r"where are you located",
    r"where (?:is|are) (?:you|your (?:office|team|company))",
    r"what(?:'s| is) your location",
    r"where do you operate",
)

QUESTION_PRICING_PATTERNS: tuple[str, ...] = (
    r"how much (?:does it|do you|would it) cost",
    r"what(?:'s| is) the (?:price|pricing|cost)",
    r"how much (?:for|to)",
    r"what are your (?:prices|rates)",
)

UNSUPPORTED_QUESTION_PATTERNS: tuple[str, ...] = (
    r"guarantee",
    r"\b1\s*million\b|\bone million\b|\bmillion sales\b",
    r"promise\b.*\bresults?\b",
    r"legal advice",
    r"refund guarantee",
    r"rank\s+(?:number\s+)?(?:one|1|#1)\b",
    r"number\s+1\s+on\s+google",
    r"enterprise\s+app\b.*\btomorrow\b|\btomorrow\b.*\benterprise\b",
)

_REQUIREMENT_HINT_PATTERNS: tuple[str, ...] = (
    r"\bi need\b",
    r"\bi want\b",
    r"\bi already have\b",
    r"\bi'm looking for\b",
    r"\bwe need\b",
    r"\bwe want\b",
    r"\blooking for\b",
    r"\becommerce\b",
    r"\bautomation\b",
    r"\bwebsite\b",
    r"\bupgrade\b",
)

_PHONE_PATTERN = re.compile(r"^\+?[1-9][0-9]{7,14}$")


@dataclass(frozen=True)
class InboundMessageClassification:
    """Multi-label classification for one inbound customer message."""

    yes_confirmation: bool = False
    no_confirmation: bool = False
    service_tokens: tuple[str, ...] = ()
    requirement_detail: bool = False
    service_request: bool = False
    user_question_services: bool = False
    user_question_location: bool = False
    user_question_pricing: bool = False
    unsupported_or_unclear_question: bool = False
    phone_number: bool = False
    irrelevant_or_unclear: bool = False
    raw_message: str = ""

    @property
    def has_answerable_question(self) -> bool:
        return any(
            (
                self.user_question_services,
                self.user_question_location,
                self.user_question_pricing,
            )
        )

    @property
    def has_user_question(self) -> bool:
        return self.has_answerable_question or self.unsupported_or_unclear_question


def classification_labels(classification: InboundMessageClassification) -> list[str]:
    """Map a multi-label classification to API-facing category strings."""
    labels: list[str] = []
    if classification.yes_confirmation:
        labels.append("yes_confirmation")
    if classification.no_confirmation:
        labels.append("no_confirmation")
    if classification.service_request:
        labels.append("service_request")
    if classification.requirement_detail:
        labels.append("requirement_detail")
    if classification.has_answerable_question:
        labels.append("user_question")
    if classification.unsupported_or_unclear_question:
        labels.append("unsupported_or_unclear_question")
    if classification.irrelevant_or_unclear:
        labels.append("irrelevant_or_unclear")
    if classification.phone_number:
        labels.append("phone_number")
    return labels


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _extract_service_tokens(normalized: str) -> list[str]:
    tokens: list[str] = []
    for pattern, token in SERVICE_PATTERNS:
        if re.search(pattern, normalized) and token not in tokens:
            tokens.append(token)
    if "website" in tokens and ("new_website" in tokens or "website_upgrade" in tokens):
        tokens.remove("website")
    return tokens


def classify_inbound_message(message: str) -> InboundMessageClassification:
    """Classify an inbound message into one or more conversation categories."""
    raw = " ".join(message.split()).strip()
    normalized = normalize_confirmation_message(raw)
    if not normalized:
        return InboundMessageClassification(irrelevant_or_unclear=True, raw_message=raw)

    confirmation = classify_whatsapp_confirmation_reply(raw)
    yes_confirmation = confirmation == "yes"
    no_confirmation = confirmation == "no"

    collapsed_phone = re.sub(r"[^\d+]", "", raw)
    phone_number = bool(_PHONE_PATTERN.fullmatch(collapsed_phone))

    service_tokens = _extract_service_tokens(normalized)
    service_request = bool(service_tokens) or _matches_any(normalized, _REQUIREMENT_HINT_PATTERNS)
    requirement_detail = service_request or _matches_any(normalized, _REQUIREMENT_HINT_PATTERNS)

    user_question_services = _matches_any(normalized, QUESTION_SERVICES_PATTERNS)
    user_question_location = _matches_any(normalized, QUESTION_LOCATION_PATTERNS)
    user_question_pricing = _matches_any(normalized, QUESTION_PRICING_PATTERNS)
    unsupported_or_unclear_question = _matches_any(normalized, UNSUPPORTED_QUESTION_PATTERNS)

    has_question_mark = "?" in raw
    has_other_question = has_question_mark and not (
        user_question_services or user_question_location or user_question_pricing
    )
    if has_other_question and not unsupported_or_unclear_question:
        unsupported_or_unclear_question = True

    irrelevant_or_unclear = (
        not yes_confirmation
        and not no_confirmation
        and not service_request
        and not requirement_detail
        and not phone_number
        and not user_question_services
        and not user_question_location
        and not user_question_pricing
        and not unsupported_or_unclear_question
        and confirmation == "unclear"
        and len(normalized.split()) <= 2
        and normalized in {"maybe", "idk", "hmm", "hm", "huh", "dunno", "not sure", "what"}
    )

    return InboundMessageClassification(
        yes_confirmation=yes_confirmation,
        no_confirmation=no_confirmation,
        service_tokens=tuple(service_tokens),
        requirement_detail=requirement_detail,
        service_request=service_request,
        user_question_services=user_question_services,
        user_question_location=user_question_location,
        user_question_pricing=user_question_pricing,
        unsupported_or_unclear_question=unsupported_or_unclear_question,
        phone_number=phone_number,
        irrelevant_or_unclear=irrelevant_or_unclear,
        raw_message=raw,
    )


def infer_project_type_from_services(service_tokens: tuple[str, ...]) -> str | None:
    """Map detected service tokens to a supported project_type value."""
    token_set = set(service_tokens)
    if "new_website" in token_set and "website_upgrade" in token_set:
        return "new_and_upgrade"
    if "new_website" in token_set:
        return "new_website"
    if "website_upgrade" in token_set:
        return "website_upgrade"
    if "website" in token_set:
        return "new_website"
    return None
