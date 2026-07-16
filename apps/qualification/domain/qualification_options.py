"""Deterministic option normalization for the menu-driven qualification flow.

Customers answer the ``customer_type``, ``referral_source``, and numbered
qualification questions either by typing a number (list-picker fallback) or by
typing a keyword / option ID. These helpers map those answers to the canonical
stored values used by the conversation state and n8n lead store. They work
identically for WhatsApp text and for transcribed voice notes.
"""

from __future__ import annotations

import re

from apps.qualification.domain.inbound_message_classification import (
    infer_project_type_from_answer,
    infer_project_type_from_services,
    _extract_service_tokens,
)

# --- customer_type -----------------------------------------------------------

CUSTOMER_TYPE_NEW = "new_customer"
CUSTOMER_TYPE_EXISTING = "existing_customer"

VALID_CUSTOMER_TYPES = frozenset({CUSTOMER_TYPE_NEW, CUSTOMER_TYPE_EXISTING})

# --- referral_source ---------------------------------------------------------

REFERRAL_GOOGLE = "google"
REFERRAL_INSTAGRAM = "instagram"
REFERRAL_FACEBOOK = "facebook"
REFERRAL_FRIEND = "friend_referral"
REFERRAL_OTHER = "other"

VALID_REFERRAL_SOURCES = frozenset(
    {
        REFERRAL_GOOGLE,
        REFERRAL_INSTAGRAM,
        REFERRAL_FACEBOOK,
        REFERRAL_FRIEND,
        REFERRAL_OTHER,
    }
)

# Twilio list-picker item IDs sent by n8n for the referral source template.
TWILIO_REFERRAL_SOURCE_BUTTON_IDS: dict[str, str] = {
    "google": REFERRAL_GOOGLE,
    "instagram": REFERRAL_INSTAGRAM,
    "facebook": REFERRAL_FACEBOOK,
    "friend_referral": REFERRAL_FRIEND,
    "other": REFERRAL_OTHER,
}

# Arabic referral labels and common variants. "other" is checked last so a label
# that also contains a platform name resolves to the platform.
_ARABIC_REFERRAL_MATCHERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (REFERRAL_GOOGLE, ("جوجل", "قوقل", "غوغل", "جوجول")),
    (REFERRAL_INSTAGRAM, ("إنستغرام", "انستغرام", "انستقرام", "إنستقرام", "انستا")),
    (REFERRAL_FACEBOOK, ("فيسبوك", "فيس بوك", "فيسبك")),
    (REFERRAL_FRIEND, ("صديق", "إحالة", "احالة", "ترشيح", "توصية", "صاحب")),
    (REFERRAL_OTHER, ("أخرى", "اخرى", "غير ذلك", "غيره", "شيء آخر")),
)

# --- project_type ------------------------------------------------------------

PROJECT_NEW_WEBSITE = "new_website"
PROJECT_WEBSITE_UPGRADE = "website_upgrade"
PROJECT_BOTH = "new_and_upgrade"

# Twilio quick-reply button IDs sent by n8n for the project type template.
TWILIO_PROJECT_TYPE_BUTTON_IDS: dict[str, str] = {
    "new_website": PROJECT_NEW_WEBSITE,
    "website_upgrade": PROJECT_WEBSITE_UPGRADE,
    "both": PROJECT_BOTH,
}

# Arabic project_type button labels and common variants. "both" is checked first
# so labels containing multiple cues resolve correctly.
_ARABIC_PROJECT_TYPE_BOTH_WORDS = ("كلاهما", "كليهما", "الاثنين", "الاثنان", "كلا")
_ARABIC_PROJECT_TYPE_UPGRADE_WORDS = ("تحديث", "ترقية", "تطوير", "موجود", "حالي", "قائم")
_ARABIC_PROJECT_TYPE_NEW_WORDS = ("جديد", "جديدة")


def _match_arabic_project_type(text: str) -> str | None:
    """Map an Arabic project_type answer to its canonical value."""
    if any(word in text for word in _ARABIC_PROJECT_TYPE_BOTH_WORDS):
        return PROJECT_BOTH
    if any(word in text for word in _ARABIC_PROJECT_TYPE_UPGRADE_WORDS):
        return PROJECT_WEBSITE_UPGRADE
    if any(word in text for word in _ARABIC_PROJECT_TYPE_NEW_WORDS):
        return PROJECT_NEW_WEBSITE
    return None


def _normalize_text(message: str | None) -> str:
    """Lowercase, collapse whitespace and strip surrounding punctuation."""
    if not message:
        return ""
    collapsed = " ".join(str(message).split()).strip().lower()
    return collapsed.strip(" .!،؟?")


def _word_set(text: str) -> set[str]:
    return set(re.findall(r"[a-z\u0600-\u06ff]+|\d+", text))


# Words that indicate the customer is describing the project, not answering the
# "new customer / existing customer" question. These prevent answers such as
# "I need a new website" from being misread as "new customer".
_PROJECT_DESCRIPTION_WORDS = frozenset(
    {
        "website",
        "webite",
        "site",
        "web",
        "upgrade",
        "redesign",
        "ecommerce",
        "store",
        "shop",
        "app",
        "application",
        "landing",
        "page",
        # Arabic project-description cues.
        "موقع",
        "متجر",
        "تطبيق",
        "صفحة",
    }
)

# Arabic customer_type cues. Existing/returning is checked before new so answers
# such as "عميل موجود" (existing customer) are not misread as new.
_ARABIC_CUSTOMER_TYPE_EXISTING_WORDS = ("حالي", "موجود", "قديم", "سابق")
_ARABIC_CUSTOMER_TYPE_NEW_WORDS = ("جديد", "جديدة")


def normalize_customer_type(message: str | None) -> str | None:
    """Map a customer answer to ``new_customer`` / ``existing_customer`` or ``None``."""
    text = _normalize_text(message)
    if not text:
        return None

    words = _word_set(text)
    if words == {"1"}:
        return CUSTOMER_TYPE_NEW
    if words == {"2"}:
        return CUSTOMER_TYPE_EXISTING

    # A project description is not an answer to the customer-type question.
    if words & _PROJECT_DESCRIPTION_WORDS:
        return None

    # Existing/returning cues take precedence so "not a new customer" is handled.
    if "existing" in text or "already" in text or "returning" in text or "current" in text:
        return CUSTOMER_TYPE_EXISTING
    if "new" in words or "first time" in text or "first-time" in text or "brand new" in text:
        return CUSTOMER_TYPE_NEW

    if any(word in text for word in _ARABIC_CUSTOMER_TYPE_EXISTING_WORDS):
        return CUSTOMER_TYPE_EXISTING
    if any(word in text for word in _ARABIC_CUSTOMER_TYPE_NEW_WORDS):
        return CUSTOMER_TYPE_NEW
    return None


def resolve_twilio_referral_source_button_id(value: str | None) -> str | None:
    """Map a Twilio list-picker item ID to the stored referral_source value."""
    if not value:
        return None
    return TWILIO_REFERRAL_SOURCE_BUTTON_IDS.get(value.strip().lower())


def _match_arabic_referral_source(text: str) -> str | None:
    """Map an Arabic referral answer to its canonical value."""
    for canonical, labels in _ARABIC_REFERRAL_MATCHERS:
        if any(label in text for label in labels):
            return canonical
    return None


def normalize_referral_source(
    message: str | None,
    *,
    button_payload: str | None = None,
) -> str | None:
    """Map a referral answer to a canonical source, or ``None`` when unrecognized."""
    from_button = resolve_twilio_referral_source_button_id(button_payload)
    if from_button is not None:
        return from_button
    from_message_id = resolve_twilio_referral_source_button_id(message)
    if from_message_id is not None:
        return from_message_id

    text = _normalize_text(message)
    if not text:
        return None

    words = _word_set(text)
    numbered = {
        "1": REFERRAL_GOOGLE,
        "2": REFERRAL_INSTAGRAM,
        "3": REFERRAL_FACEBOOK,
        "4": REFERRAL_FRIEND,
        "5": REFERRAL_OTHER,
    }
    if len(words) == 1:
        only = next(iter(words))
        if only in numbered:
            return numbered[only]

    if "google" in text:
        return REFERRAL_GOOGLE
    if "insta" in text:
        return REFERRAL_INSTAGRAM
    if "facebook" in text or "fb" in words:
        return REFERRAL_FACEBOOK
    if (
        "friend" in text
        or "referral" in text
        or "referred" in text
        or "recommend" in text
        or "word of mouth" in text
    ):
        return REFERRAL_FRIEND
    if "other" in text:
        return REFERRAL_OTHER

    arabic_match = _match_arabic_referral_source(text)
    if arabic_match is not None:
        return arabic_match
    return None


def resolve_twilio_project_type_button_id(value: str | None) -> str | None:
    """Map a Twilio quick-reply button ID to the stored project_type value."""
    if not value:
        return None
    return TWILIO_PROJECT_TYPE_BUTTON_IDS.get(value.strip().lower())


def normalize_project_type(
    message: str | None,
    *,
    button_payload: str | None = None,
) -> str | None:
    """Map a project answer to ``new_website`` / ``website_upgrade`` / ``new_and_upgrade``."""
    from_button = resolve_twilio_project_type_button_id(button_payload)
    if from_button is not None:
        return from_button
    from_message_id = resolve_twilio_project_type_button_id(message)
    if from_message_id is not None:
        return from_message_id

    text = _normalize_text(message)
    if not text:
        return None

    words = _word_set(text)
    if len(words) == 1:
        only = next(iter(words))
        if only == "1":
            return PROJECT_NEW_WEBSITE
        if only == "2":
            return PROJECT_WEBSITE_UPGRADE
        if only == "3":
            return PROJECT_BOTH

    if "both" in words:
        return PROJECT_BOTH

    arabic_match = _match_arabic_project_type(text)
    if arabic_match is not None:
        return arabic_match

    inferred = infer_project_type_from_answer(message or "")
    if inferred:
        return inferred

    wants_upgrade = (
        "upgrade" in text
        or "redesign" in text
        or "improve" in text
        or "existing" in text
    )
    wants_new = "new" in words or "build" in words or "create" in words
    if wants_upgrade and wants_new:
        return PROJECT_BOTH
    if wants_upgrade:
        return PROJECT_WEBSITE_UPGRADE
    if wants_new:
        return PROJECT_NEW_WEBSITE

    from_services = infer_project_type_from_services(tuple(_extract_service_tokens(text)))
    return from_services
