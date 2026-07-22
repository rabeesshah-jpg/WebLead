"""Numbered multi-choice qualification questions (numeric or option-ID replies).

Replaces the old single ``project_type`` / free-text ``requirements`` steps with
five menu questions. Customers normally reply with the option number; the same
stable option IDs are accepted only for the current step (cross-step IDs are
rejected). Localized English/Arabic display text is stored separately from IDs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.qualification.domain.language_selection import (
    LANGUAGE_ARABIC,
    LANGUAGE_ENGLISH,
    normalize_conversation_language,
)

# Canonical step order after referral_source (new) / customer_type (existing).
QUALIFICATION_STEPS: tuple[str, ...] = (
    "business_type",
    "website_status",
    "paid_ads",
    "main_goal",
    "launch_timeline",
)

# Backward-compatible alias used throughout the conversation flow.
NUMBERED_QUALIFICATION_FIELDS: tuple[str, ...] = QUALIFICATION_STEPS
FIRST_NUMBERED_QUALIFICATION_FIELD = QUALIFICATION_STEPS[0]


@dataclass(frozen=True)
class NumberedOption:
    """One selectable option for a numbered qualification question."""

    number: int
    value: str
    labels: dict[str, str]


_BUSINESS_TYPE_OPTIONS: tuple[NumberedOption, ...] = (
    NumberedOption(
        1,
        "biz_local_service",
        {
            LANGUAGE_ENGLISH: "Local service business (clinic, salon, restaurant)",
            LANGUAGE_ARABIC: "عمل خدمات محلي (عيادة، صالون، مطعم)",
        },
    ),
    NumberedOption(
        2,
        "biz_coaching",
        {
            LANGUAGE_ENGLISH: "Coaching / consulting / online services",
            LANGUAGE_ARABIC: "تدريب / استشارات / خدمات عبر الإنترنت",
        },
    ),
    NumberedOption(
        3,
        "biz_ecommerce",
        {
            LANGUAGE_ENGLISH: "Ecommerce / online store",
            LANGUAGE_ARABIC: "تجارة إلكترونية / متجر إلكتروني",
        },
    ),
    NumberedOption(
        4,
        "biz_other",
        {
            LANGUAGE_ENGLISH: "Other",
            LANGUAGE_ARABIC: "أخرى",
        },
    ),
)

_WEBSITE_STATUS_OPTIONS: tuple[NumberedOption, ...] = (
    NumberedOption(
        1,
        "site_none",
        {
            LANGUAGE_ENGLISH: "No website yet",
            LANGUAGE_ARABIC: "لا يوجد موقع بعد",
        },
    ),
    NumberedOption(
        2,
        "site_basic",
        {
            LANGUAGE_ENGLISH: "Yes, a basic / DIY website",
            LANGUAGE_ARABIC: "نعم، موقع بسيط / ذاتي الصنع",
        },
    ),
    NumberedOption(
        3,
        "site_old_professional",
        {
            LANGUAGE_ENGLISH: "Yes, a professional site but 3+ years old",
            LANGUAGE_ARABIC: "نعم، موقع احترافي لكنه عمره أكثر من 3 سنوات",
        },
    ),
    NumberedOption(
        4,
        "site_modern",
        {
            LANGUAGE_ENGLISH: "Yes, a modern site we're mostly happy with",
            LANGUAGE_ARABIC: "نعم، موقع حديث ونحن راضون عنه إلى حد كبير",
        },
    ),
)

_PAID_ADS_OPTIONS: tuple[NumberedOption, ...] = (
    NumberedOption(
        1,
        "ads_none",
        {
            LANGUAGE_ENGLISH: "No",
            LANGUAGE_ARABIC: "لا",
        },
    ),
    NumberedOption(
        2,
        "ads_boost",
        {
            LANGUAGE_ENGLISH: "We occasionally boost posts",
            LANGUAGE_ARABIC: "نموّل المنشورات أحيانًا",
        },
    ),
    NumberedOption(
        3,
        "ads_lt_2k",
        {
            LANGUAGE_ENGLISH: "Yes, but less than $2,000 per month",
            LANGUAGE_ARABIC: "نعم، لكن أقل من 2,000 دولار شهريًا",
        },
    ),
    NumberedOption(
        4,
        "ads_2k_10k",
        {
            LANGUAGE_ENGLISH: "Yes, $2,000–$10,000 per month",
            LANGUAGE_ARABIC: "نعم، من 2,000 إلى 10,000 دولار شهريًا",
        },
    ),
    NumberedOption(
        5,
        "ads_gt_10k",
        {
            LANGUAGE_ENGLISH: "Yes, more than $10,000 per month",
            LANGUAGE_ARABIC: "نعم، أكثر من 10,000 دولار شهريًا",
        },
    ),
)

_MAIN_GOAL_OPTIONS: tuple[NumberedOption, ...] = (
    NumberedOption(
        1,
        "goal_website_only",
        {
            LANGUAGE_ENGLISH: (
                "A clean, professional website that I don't have to worry about"
            ),
            LANGUAGE_ARABIC: "موقع نظيف واحترافي لا أحتاج للقلق بشأنه",
        },
    ),
    NumberedOption(
        2,
        "goal_website_marketing",
        {
            LANGUAGE_ENGLISH: (
                "Website plus ongoing marketing so leads and sales grow every month"
            ),
            LANGUAGE_ARABIC: (
                "موقع مع تسويق مستمر حتى تنمو العملاء المحتملون والمبيعات كل شهر"
            ),
        },
    ),
    NumberedOption(
        3,
        "goal_more_customers",
        {
            LANGUAGE_ENGLISH: (
                "I just want more customers. I don't care where they come from"
            ),
            LANGUAGE_ARABIC: "أريد فقط المزيد من العملاء. لا يهمني من أين يأتون",
        },
    ),
)

_LAUNCH_TIMELINE_OPTIONS: tuple[NumberedOption, ...] = (
    NumberedOption(
        1,
        "timeline_30d",
        {
            LANGUAGE_ENGLISH: "Within 30 days",
            LANGUAGE_ARABIC: "خلال 30 يومًا",
        },
    ),
    NumberedOption(
        2,
        "timeline_1_3m",
        {
            LANGUAGE_ENGLISH: "1–3 months",
            LANGUAGE_ARABIC: "من شهر إلى 3 أشهر",
        },
    ),
    NumberedOption(
        3,
        "timeline_3_6m",
        {
            LANGUAGE_ENGLISH: "3–6 months",
            LANGUAGE_ARABIC: "من 3 إلى 6 أشهر",
        },
    ),
    NumberedOption(
        4,
        "timeline_exploring",
        {
            LANGUAGE_ENGLISH: "Just exploring options",
            LANGUAGE_ARABIC: "أتصفح الخيارات فقط",
        },
    ),
)

NUMBERED_QUALIFICATION_OPTIONS: dict[str, tuple[NumberedOption, ...]] = {
    "business_type": _BUSINESS_TYPE_OPTIONS,
    "website_status": _WEBSITE_STATUS_OPTIONS,
    "paid_ads": _PAID_ADS_OPTIONS,
    "main_goal": _MAIN_GOAL_OPTIONS,
    "launch_timeline": _LAUNCH_TIMELINE_OPTIONS,
}

# Stable option ID sets (language-independent).
QUALIFICATION_OPTIONS: dict[str, frozenset[str]] = {
    field: frozenset(option.value for option in options)
    for field, options in NUMBERED_QUALIFICATION_OPTIONS.items()
}

# Central Twilio list-picker / Body aliases → canonical stored option IDs.
# Right-hand values MUST stay in QUALIFICATION_OPTIONS (do not invent new storage IDs).
TWILIO_LIST_PICKER_OPTION_ALIASES: dict[str, dict[str, str]] = {
    "business_type": {
        "local_service": "biz_local_service",
        "coaching": "biz_coaching",
        "ecommerce": "biz_ecommerce",
        "other": "biz_other",
        "biz_local_service": "biz_local_service",
        "biz_coaching": "biz_coaching",
        "biz_ecommerce": "biz_ecommerce",
        "biz_other": "biz_other",
    },
    "website_status": {
        "no_website": "site_none",
        "basic_website": "site_basic",
        "old_professional": "site_old_professional",
        "professional_site": "site_old_professional",
        "site_old": "site_old_professional",
        "modern_site": "site_modern",
        "site_none": "site_none",
        "site_basic": "site_basic",
        "site_old_professional": "site_old_professional",
        "site_modern": "site_modern",
        "no website yet": "site_none",
        "yes, a basic / diy website": "site_basic",
        "old professional site": "site_old_professional",
        "professional website but more than 3 years old": "site_old_professional",
        "yes, a modern site we're mostly happy with": "site_modern",
    },
    "paid_ads": {
        "no_ads": "ads_none",
        "ads_none": "ads_none",
        "no": "ads_none",
        "boost": "ads_boost",
        "ads_boost": "ads_boost",
        "boost_posts": "ads_boost",
        "occasional_boost": "ads_boost",
        "ads_under_2k": "ads_lt_2k",
        "ads_lt_2k": "ads_lt_2k",
        "under_2k": "ads_lt_2k",
        "ads_2k_10k": "ads_2k_10k",
        "ads_mid": "ads_2k_10k",
        "ads_over_10k": "ads_gt_10k",
        "ads_gt_10k": "ads_gt_10k",
        "ads_high": "ads_gt_10k",
        "over_10k": "ads_gt_10k",
        "we occasionally boost posts": "ads_boost",
        "yes, but less than $2,000 per month": "ads_lt_2k",
        "yes, $2,000–$10,000 per month": "ads_2k_10k",
        "yes, $2,000-$10,000 per month": "ads_2k_10k",
        "yes, more than $10,000 per month": "ads_gt_10k",
    },
    "main_goal": {
        "website_only": "goal_website_only",
        "goal_website": "goal_website_only",
        "goal_website_only": "goal_website_only",
        "clean_website": "goal_website_only",
        "website_marketing": "goal_website_marketing",
        "goal_marketing": "goal_website_marketing",
        "goal_website_marketing": "goal_website_marketing",
        "marketing": "goal_website_marketing",
        "more_customers": "goal_more_customers",
        "goal_growth": "goal_more_customers",
        "goal_more_customers": "goal_more_customers",
        "customers": "goal_more_customers",
        "a clean, professional website that i don't have to worry about": (
            "goal_website_only"
        ),
        (
            "website plus ongoing marketing so leads and sales grow every month"
        ): "goal_website_marketing",
        (
            "i just want more customers. i don't care where they come from"
        ): "goal_more_customers",
    },
    "launch_timeline": {
        "within_30_days": "timeline_30d",
        "days_30": "timeline_30d",
        "30_days": "timeline_30d",
        "timeline_30d": "timeline_30d",
        "1_3_months": "timeline_1_3m",
        "months_1_3": "timeline_1_3m",
        "timeline_1_3m": "timeline_1_3m",
        "3_6_months": "timeline_3_6m",
        "months_3_6": "timeline_3_6m",
        "timeline_3_6m": "timeline_3_6m",
        "exploring": "timeline_exploring",
        "just_exploring": "timeline_exploring",
        "timeline_exploring": "timeline_exploring",
        "within 30 days": "timeline_30d",
        "1–3 months": "timeline_1_3m",
        "1-3 months": "timeline_1_3m",
        "3–6 months": "timeline_3_6m",
        "3-6 months": "timeline_3_6m",
        "just exploring options": "timeline_exploring",
    },
}


_QUESTION_PROMPTS: dict[str, dict[str, str]] = {
    "business_type": {
        LANGUAGE_ENGLISH: "What best describes your business?",
        LANGUAGE_ARABIC: "ما الذي يصف عملك بشكل أفضل؟",
    },
    "website_status": {
        LANGUAGE_ENGLISH: "Do you currently have a website?",
        LANGUAGE_ARABIC: "هل لديك موقع إلكتروني حاليًا؟",
    },
    "paid_ads": {
        LANGUAGE_ENGLISH: "Do you currently run paid ads?",
        LANGUAGE_ARABIC: "هل تشغّل إعلانات مدفوعة حاليًا؟",
    },
    "main_goal": {
        LANGUAGE_ENGLISH: "What are you mainly looking for from us right now?",
        LANGUAGE_ARABIC: "ما الذي تبحث عنه منا بشكل أساسي الآن؟",
    },
    "launch_timeline": {
        LANGUAGE_ENGLISH: (
            "How soon would you like to launch or relaunch your website or growth system?"
        ),
        LANGUAGE_ARABIC: (
            "متى ترغب في إطلاق أو إعادة إطلاق موقعك أو نظام النمو الخاص بك؟"
        ),
    },
}

_REPLY_HINTS: dict[str, dict[str, str]] = {
    "business_type": {
        LANGUAGE_ENGLISH: "Please reply with 1, 2, 3, or 4.",
        LANGUAGE_ARABIC: "يرجى الرد بالرقم 1 أو 2 أو 3 أو 4.",
    },
    "website_status": {
        LANGUAGE_ENGLISH: "Please reply with 1, 2, 3, or 4.",
        LANGUAGE_ARABIC: "يرجى الرد بالرقم 1 أو 2 أو 3 أو 4.",
    },
    "paid_ads": {
        LANGUAGE_ENGLISH: "Please reply with 1, 2, 3, 4, or 5.",
        LANGUAGE_ARABIC: "يرجى الرد بالرقم 1 أو 2 أو 3 أو 4 أو 5.",
    },
    "main_goal": {
        LANGUAGE_ENGLISH: "Please reply with 1, 2, or 3.",
        LANGUAGE_ARABIC: "يرجى الرد بالرقم 1 أو 2 أو 3.",
    },
    "launch_timeline": {
        LANGUAGE_ENGLISH: "Please reply with 1, 2, 3, or 4.",
        LANGUAGE_ARABIC: "يرجى الرد بالرقم 1 أو 2 أو 3 أو 4.",
    },
}


def is_numbered_qualification_field(field: str | None) -> bool:
    """Return True when ``field`` is one of the numbered qualification steps."""
    return field in NUMBERED_QUALIFICATION_OPTIONS


def option_label(option: NumberedOption, *, language: str) -> str:
    """Return the customer-facing label for an option in the selected language."""
    normalized = normalize_conversation_language(language)
    return option.labels.get(normalized) or option.labels[LANGUAGE_ENGLISH]


def format_numbered_question(*, field: str, language: str) -> str:
    """Build the full question text with numbered options and reply hint."""
    if field not in NUMBERED_QUALIFICATION_OPTIONS:
        raise KeyError(field)
    normalized = normalize_conversation_language(language)
    prompt = _QUESTION_PROMPTS[field][normalized]
    options = NUMBERED_QUALIFICATION_OPTIONS[field]
    lines = [prompt]
    for option in options:
        lines.append(f"{option.number}. {option_label(option, language=normalized)}")
    lines.append(_REPLY_HINTS[field][normalized])
    return "\n".join(lines)


def _extract_single_option_number(message: str | None) -> int | None:
    """Return an integer when the message is exactly one option number, else None."""
    if not message:
        return None
    collapsed = " ".join(str(message).split()).strip()
    if not collapsed.isdigit():
        return None
    if collapsed != str(int(collapsed)):
        return None
    return int(collapsed)


def _selection_payload(
    option: NumberedOption,
    *,
    language: str,
) -> dict[str, Any]:
    return {
        "value": option.value,
        "number": option.number,
        "answer": option_label(option, language=language),
    }


def _normalize_option_token(message: str | None) -> str:
    return " ".join(str(message or "").split()).strip()


def _option_by_canonical_id(field: str, canonical_id: str) -> NumberedOption | None:
    options = NUMBERED_QUALIFICATION_OPTIONS.get(field)
    if not options:
        return None
    for option in options:
        if option.value == canonical_id:
            return option
    return None


def resolve_canonical_option_id(field: str, message: str | None) -> str | None:
    """
    Resolve a raw reply to the canonical stored option ID for ``field``.

    Accepts option numbers, canonical IDs, Twilio list-picker aliases, and
    localized option labels. Returns ``None`` when unrecognized for ``field``.
    """
    options = NUMBERED_QUALIFICATION_OPTIONS.get(field)
    if not options:
        return None

    number = _extract_single_option_number(message)
    if number is not None:
        for option in options:
            if option.number == number:
                return option.value
        return None

    token = _normalize_option_token(message)
    if not token:
        return None

    for option in options:
        if option.value == token:
            return option.value

    aliases = TWILIO_LIST_PICKER_OPTION_ALIASES.get(field) or {}
    canonical_id = aliases.get(token.lower())
    if canonical_id and _option_by_canonical_id(field, canonical_id) is not None:
        return canonical_id

    needle = token.lower()
    for option in options:
        for label in option.labels.values():
            if _normalize_option_token(label).lower() == needle:
                return option.value
    return None


def normalize_numbered_qualification_answer(
    field: str,
    message: str | None,
    *,
    language: str = LANGUAGE_ENGLISH,
) -> dict[str, Any] | None:
    """
    Map a reply to stored selection data for the **current** ``field`` only.

    Accepts:
    - a single option number valid for ``field``
    - the stable option ID belonging to ``field``
    - Twilio list-picker item IDs / aliases for ``field``
    - localized option labels for ``field``

    Cross-step option IDs (for example ``ads_lt_2k`` while answering
    ``business_type``) return ``None`` and must not advance the flow.
    """
    canonical_id = resolve_canonical_option_id(field, message)
    if canonical_id is None:
        return None
    option = _option_by_canonical_id(field, canonical_id)
    if option is None:
        return None
    return _selection_payload(option, language=language)


def apply_numbered_selection(
    fields: dict[str, Any],
    field: str,
    selection: dict[str, Any],
) -> dict[str, Any]:
    """Persist option ID, selected number, and localized answer text."""
    updated = dict(fields)
    option_id = selection["value"]
    updated[field] = option_id
    updated[f"{field}_option_id"] = option_id
    updated[f"{field}_number"] = selection["number"]
    updated[f"{field}_answer"] = selection["answer"]
    return updated


def has_numbered_qualification_answer(fields: dict[str, Any], field: str) -> bool:
    """Return True when ``field`` has a stored canonical (or alias) option value."""
    return resolve_canonical_option_id(field, fields.get(field)) is not None


def canonicalize_numbered_fields(
    fields: dict[str, Any],
    *,
    language: str = LANGUAGE_ENGLISH,
) -> dict[str, Any]:
    """
    Rewrite any aliased numbered values to canonical IDs and fill selection metadata.

    Ensures already-answered steps are skipped even if a Twilio alias was stored
    before mapping existed.
    """
    updated = dict(fields)
    normalized_language = normalize_conversation_language(language)
    for field in NUMBERED_QUALIFICATION_FIELDS:
        raw = updated.get(field)
        canonical_id = resolve_canonical_option_id(field, raw if isinstance(raw, str) else None)
        if canonical_id is None:
            continue
        selection = normalize_numbered_qualification_answer(
            field,
            canonical_id,
            language=normalized_language,
        )
        if selection is None:
            continue
        if (
            updated.get(field) != selection["value"]
            or updated.get(f"{field}_option_id") != selection["value"]
            or updated.get(f"{field}_number") != selection["number"]
            or not updated.get(f"{field}_answer")
        ):
            updated = apply_numbered_selection(updated, field, selection)
    return updated


def compose_requirements_summary(
    fields: dict[str, Any],
    *,
    language: str = LANGUAGE_ENGLISH,
) -> str:
    """Build a human-readable requirements string from numbered answers."""
    normalized = normalize_conversation_language(language)
    parts: list[str] = []
    for field in NUMBERED_QUALIFICATION_FIELDS:
        answer = fields.get(f"{field}_answer")
        if isinstance(answer, str) and answer.strip():
            parts.append(answer.strip())
            continue
        value = fields.get(field)
        canonical_id = resolve_canonical_option_id(field, value if isinstance(value, str) else None)
        options = NUMBERED_QUALIFICATION_OPTIONS[field]
        for option in options:
            if option.value == (canonical_id or value):
                parts.append(option_label(option, language=normalized))
                break
    return " | ".join(parts)


def expected_option_tokens_for_field(field: str) -> list[str]:
    """Return canonical IDs and known Twilio aliases accepted for ``field``."""
    options = NUMBERED_QUALIFICATION_OPTIONS.get(field)
    if not options:
        return []
    tokens = {option.value for option in options}
    tokens.update((TWILIO_LIST_PICKER_OPTION_ALIASES.get(field) or {}).keys())
    return sorted(tokens)


def match_incoming_option_to_prior_step(
    *,
    incoming: str | None,
    current_field: str,
    answered_fields: dict[str, Any],
    prior_fields: tuple[str, ...],
) -> str | None:
    """
    Return a prior answered step when ``incoming`` belongs to that step's options.

    Pure option numbers are ignored here because ``1``/``2`` are ambiguous across
    steps; stale Twilio list-picker payloads use stable item IDs / labels.
    """
    if not incoming or not current_field:
        return None
    if _extract_single_option_number(incoming) is not None:
        return None

    for field in prior_fields:
        if field == current_field:
            break
        if field not in NUMBERED_QUALIFICATION_OPTIONS:
            continue
        if not has_numbered_qualification_answer(answered_fields, field):
            continue
        if resolve_canonical_option_id(field, incoming) is not None:
            return field
    return None


def build_qualification_state_machine_fields(
    *,
    next_field: str | None,
    qualification_status: str | None,
    conversation_language: str | None,
    reply_text: str | None = None,
    should_send_text: bool | None = None,
    should_send_qualification_question: bool | None = None,
) -> dict[str, Any]:
    """
    Derive n8n-friendly aliases for the numbered qualification state machine.

    Existing contract fields (``next_field``, ``conversation_language``,
    ``qualification_status``) remain the source of truth; these keys are additive.

    When ``should_send_qualification_question`` is provided (for example after a
    stale list-picker ignore), that explicit value wins.
    """
    language = normalize_conversation_language(conversation_language or LANGUAGE_ENGLISH)
    complete = qualification_status == "completed"
    is_numbered_step = is_numbered_qualification_field(next_field)
    # List-picker turns intentionally leave Body text empty; still advertise the step
    # so n8n can run Should Send Qualification Question → Send Qualification List Picker.
    # ``should_send_text`` / ``reply_text`` remain for callers but do not gate the
    # default flag. Explicit overrides (stale ignores) are honored.
    _ = should_send_text, reply_text
    if should_send_qualification_question is not None:
        should_ask = bool(should_send_qualification_question)
    else:
        should_ask = not complete and is_numbered_step
    return {
        "qualification_step": next_field if is_numbered_step else None,
        "language": language,
        "qualification_complete": complete,
        "should_send_qualification_question": should_ask,
    }
