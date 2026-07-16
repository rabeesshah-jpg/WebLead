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

    Cross-step option IDs (for example ``ads_lt_2k`` while answering
    ``business_type``) return ``None`` and must not advance the flow.
    """
    options = NUMBERED_QUALIFICATION_OPTIONS.get(field)
    if not options:
        return None

    number = _extract_single_option_number(message)
    if number is not None:
        for option in options:
            if option.number == number:
                return _selection_payload(option, language=language)
        return None

    option_id = " ".join(str(message or "").split()).strip()
    if not option_id:
        return None
    for option in options:
        if option.value == option_id:
            return _selection_payload(option, language=language)
    return None


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
    """Return True when ``field`` has a stored canonical option ID."""
    options = NUMBERED_QUALIFICATION_OPTIONS.get(field)
    if not options:
        return False
    value = fields.get(field)
    return any(option.value == value for option in options)


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
        options = NUMBERED_QUALIFICATION_OPTIONS[field]
        for option in options:
            if option.value == value:
                parts.append(option_label(option, language=normalized))
                break
    return " | ".join(parts)


def build_qualification_state_machine_fields(
    *,
    next_field: str | None,
    qualification_status: str | None,
    conversation_language: str | None,
    reply_text: str | None = None,
    should_send_text: bool | None = None,
) -> dict[str, Any]:
    """
    Derive n8n-friendly aliases for the numbered qualification state machine.

    Existing contract fields (``next_field``, ``conversation_language``,
    ``qualification_status``) remain the source of truth; these keys are additive.
    """
    language = normalize_conversation_language(conversation_language or LANGUAGE_ENGLISH)
    complete = qualification_status == "completed"
    is_numbered_step = is_numbered_qualification_field(next_field)
    # List-picker turns intentionally leave Body text empty; still advertise the step
    # so n8n can run Should Send Qualification Question → Send Qualification List Picker.
    # ``should_send_text`` / ``reply_text`` remain for callers but do not gate this flag.
    _ = should_send_text, reply_text
    should_ask = not complete and is_numbered_step
    return {
        "qualification_step": next_field if is_numbered_step else None,
        "language": language,
        "qualification_complete": complete,
        "should_send_qualification_question": should_ask,
    }
