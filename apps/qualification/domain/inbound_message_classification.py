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
    r"what do you offer",
    r"what do you provide",
    r"which services",
)

ROLE_QUESTION_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"tell me (?:about )?your role", "role"),
    (r"tell me your role", "role"),
    (r"what(?:'s| is) your (?:job|role)\??", "role"),
    (r"what your (?:job|role)\??", "role"),
    (r"what do you do\??", "what_do_you_do"),
    (r"how can you help me\??", "role"),
    (r"what can you help me with\??", "role"),
)

ABOUT_YOURSELF_PATTERNS: tuple[str, ...] = (
    r"tell me about your(?:self| self)",
    r"introduce yourself",
    r"(?:first |but )?tell me about you\b",
    r"^about you\??$",
    r"about yourself",
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
    r"what is the price",
)

QUESTION_TIMELINE_PATTERNS: tuple[str, ...] = (
    r"what(?:'s| is) the timeline",
    r"how long (?:will it|does it|would it) take",
    r"when will (?:it|the website|my website) be (?:ready|done|finished|live)",
    r"delivery time",
    r"how soon can you",
    r"turnaround time",
)

SMALL_TALK_GREETING_PATTERNS: tuple[str, ...] = (
    r"^(?:hi|hello|hey|hiya|good morning|good afternoon|good evening)(?:[!.,]?\s*)?$",
    r"^(?:hi|hello|hey)\s+there(?:[!.,]?\s*)?$",
    r"^(?:marhaba|ahlan|salam|assalamu alaikum)(?:[!.,]?\s*)?$",
)

SMALL_TALK_GREETING_PREFIX_PATTERNS: tuple[str, ...] = (
    r"^(?:hi|hello|hey|hiya|good morning|good afternoon|good evening)\b",
    r"^(?:assalamu?\s*(?:o|wa)?\s*alaikum|as\s*salamu\s*alaikum|salam|marhaba|ahlan)\b",
)

SMALL_TALK_WELLBEING_PATTERNS: tuple[str, ...] = (
    r"^how are you(?:\s+doing)?\??$",
    r"^how(?:'s| is) it going\??$",
    r"^how are things\??$",
    r"^how do you do\??$",
    r"^how r u\??$",
    r"^how are u\??$",
)

SMALL_TALK_WELLBEING_ANYWHERE_PATTERNS: tuple[str, ...] = (
    r"\bhow are you\b",
    r"\bhow(?:'s| is) it going\b",
    r"\bhow are things\b",
    r"\bhow r u\b",
    r"\bhow are u\b",
    r"\bhow're u\b",
)

IDENTITY_QUESTION_PATTERNS: tuple[str, ...] = (
    r"what(?:'s| is) your name\??",
    r"who are you\??",
    r"who is this\??",
    r"may i know your name\??",
    r"what should i call you\??",
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
    user_question_timeline: bool = False
    small_talk_greeting: bool = False
    small_talk_wellbeing: bool = False
    identity_question: bool = False
    about_yourself_question: bool = False
    role_question: bool = False
    role_question_kind: str | None = None
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
                self.user_question_timeline,
            )
        )

    @property
    def is_small_talk_or_identity(self) -> bool:
        return any(
            (
                self.small_talk_greeting,
                self.small_talk_wellbeing,
                self.identity_question,
                self.about_yourself_question,
                self.role_question,
            )
        )

    @property
    def is_persona_interaction(self) -> bool:
        return self.is_small_talk_or_identity

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
    if classification.small_talk_greeting:
        labels.append("small_talk_greeting")
    if classification.small_talk_wellbeing:
        labels.append("small_talk_wellbeing")
    if classification.identity_question:
        labels.append("identity_question")
    if classification.about_yourself_question:
        labels.append("about_yourself_question")
    if classification.role_question:
        labels.append("role_question")
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


def _match_role_question(normalized: str) -> tuple[bool, str | None]:
    for pattern, kind in ROLE_QUESTION_PATTERNS:
        if re.search(pattern, normalized):
            return True, kind
    return False, None


def _has_substantive_qualification_content(
    *,
    service_request: bool,
    requirement_detail: bool,
    phone_number: bool,
    user_question_services: bool,
    user_question_location: bool,
    user_question_pricing: bool,
    user_question_timeline: bool,
) -> bool:
    """Return True when the message carries real qualification content."""
    return any(
        (
            service_request,
            requirement_detail,
            phone_number,
            user_question_services,
            user_question_location,
            user_question_pricing,
            user_question_timeline,
        )
    )


_FILLER_ACKNOWLEDGMENT_WORDS: frozenset[str] = frozenset(
    {
        "nice",
        "good",
        "ok",
        "okay",
        "thanks",
        "thank",
        "you",
        "cool",
        "great",
        "sure",
        "alright",
        "fine",
        "bro",
        "brother",
        "yea",
        "yeah",
        "yep",
    }
)


def _is_filler_acknowledgment(normalized: str) -> bool:
    """Return True when the message is only brief filler with no qualification content."""
    words = normalized.split()
    if not words or len(words) > 4:
        return False
    return all(word in _FILLER_ACKNOWLEDGMENT_WORDS for word in words)


def infer_project_type_from_answer(message: str) -> str | None:
    """Map a short customer answer to a supported project_type value."""
    normalized = normalize_confirmation_message(message)
    if not normalized:
        return None
    if normalized == "both":
        return "new_and_upgrade"
    wants_new = bool(
        re.search(
            r"\b(?:new website|brand new website|new site|new web site)\b",
            normalized,
        )
    )
    wants_upgrade = bool(
        re.search(
            r"\b(?:upgrade(?:\s+existing)?\s+website|existing website|website upgrade)\b",
            normalized,
        )
    )
    if wants_new and wants_upgrade:
        return "new_and_upgrade"
    if wants_upgrade and not wants_new:
        return "website_upgrade"
    if wants_new:
        return "new_website"
    if re.fullmatch(r"(?:new )?website", normalized):
        return "new_website"
    if normalized in {"upgrade", "website upgrade"}:
        return "website_upgrade"
    return None


_DIRECT_PROJECT_TYPE_BLOCKERS: tuple[str, ...] = (
    r"\bi need\b",
    r"\bi want\b",
    r"\bi'm looking for\b",
    r"\bwe need\b",
    r"\bwe want\b",
    r"\bfor my\b",
    r"\bfor our\b",
    r"\bfor the\b",
)


def is_direct_project_type_answer(message: str) -> bool:
    """Return True when the message only answers project_type, not full requirements."""
    if not infer_project_type_from_answer(message):
        return False
    normalized = normalize_confirmation_message(message)
    return not _matches_any(normalized, _DIRECT_PROJECT_TYPE_BLOCKERS)


_ONBOARDING_GREETING_WORDS: frozenset[str] = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "hiya",
        "there",
        "good",
        "morning",
        "afternoon",
        "evening",
        "marhaba",
        "ahlan",
        "salam",
        "assalamu",
        "alaikum",
    }
)


def _is_greeting_with_filler(normalized: str) -> bool:
    """Return True for short greetings such as ``hello brother`` or ``hi there``."""
    words = normalized.split()
    if not words or len(words) > 4:
        return False
    allowed = _FILLER_ACKNOWLEDGMENT_WORDS | _ONBOARDING_GREETING_WORDS
    return all(word in allowed for word in words) and words[0] in _ONBOARDING_GREETING_WORDS


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
    user_question_timeline = _matches_any(normalized, QUESTION_TIMELINE_PATTERNS)

    has_qualification_content = _has_substantive_qualification_content(
        service_request=service_request,
        requirement_detail=requirement_detail,
        phone_number=phone_number,
        user_question_services=user_question_services,
        user_question_location=user_question_location,
        user_question_pricing=user_question_pricing,
        user_question_timeline=user_question_timeline,
    )

    about_yourself_question = _matches_any(normalized, ABOUT_YOURSELF_PATTERNS)
    identity_question = _matches_any(normalized, IDENTITY_QUESTION_PATTERNS)
    role_question, role_question_kind = _match_role_question(normalized)

    wellbeing_anywhere = _matches_any(normalized, SMALL_TALK_WELLBEING_ANYWHERE_PATTERNS)
    small_talk_wellbeing = wellbeing_anywhere or (
        not has_qualification_content
        and _matches_any(normalized, SMALL_TALK_WELLBEING_PATTERNS)
    )

    greeting_prefix = (
        not has_qualification_content
        and _matches_any(normalized, SMALL_TALK_GREETING_PREFIX_PATTERNS)
    )
    small_talk_greeting = (
        not has_qualification_content
        and _matches_any(normalized, SMALL_TALK_GREETING_PATTERNS)
    )
    if greeting_prefix and wellbeing_anywhere:
        small_talk_greeting = True
        small_talk_wellbeing = True
    elif greeting_prefix and _is_greeting_with_filler(normalized):
        small_talk_greeting = True

    unsupported_or_unclear_question = _matches_any(normalized, UNSUPPORTED_QUESTION_PATTERNS)

    has_question_mark = "?" in raw
    has_other_question = has_question_mark and not (
        user_question_services
        or user_question_location
        or user_question_pricing
        or user_question_timeline
        or small_talk_wellbeing
        or identity_question
        or about_yourself_question
        or role_question
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
        and not user_question_timeline
        and not small_talk_greeting
        and not small_talk_wellbeing
        and not identity_question
        and not about_yourself_question
        and not role_question
        and not unsupported_or_unclear_question
        and (
            _is_filler_acknowledgment(normalized)
            or (
                confirmation == "unclear"
                and len(normalized.split()) <= 2
                and normalized
                in {"maybe", "idk", "hmm", "hm", "huh", "dunno", "not sure", "what"}
            )
        )
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
        user_question_timeline=user_question_timeline,
        small_talk_greeting=small_talk_greeting,
        small_talk_wellbeing=small_talk_wellbeing,
        identity_question=identity_question,
        about_yourself_question=about_yourself_question,
        role_question=role_question,
        role_question_kind=role_question_kind,
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
