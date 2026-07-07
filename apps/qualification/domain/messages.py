"""Bilingual customer-facing qualification messages."""

from __future__ import annotations

import logging

from apps.qualification.domain.language_selection import (
    LANGUAGE_ARABIC,
    LANGUAGE_ENGLISH,
    normalize_conversation_language,
)

logger = logging.getLogger("apps.qualification")

QUALIFICATION_QUESTION_KEYS: tuple[str, ...] = (
    "project_type",
    "requirements",
    "referral_source",
    "whatsapp_confirmed",
    "preferred_phone",
)

REQUIRED_MESSAGE_KEYS: tuple[str, ...] = (
    *QUALIFICATION_QUESTION_KEYS,
    "whatsapp_confirmation_unclear",
    "invalid_phone",
    "completion",
    "completion_with_booking_link",
    "completion_pending_booking_link",
    "human_handoff",
    "generic_retry",
    "generic_error",
    "whatsapp_menu",
    "restart_intro",
)

QUALIFICATION_MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "project_type": (
            "Are you looking for a new website or an upgrade to your existing website?"
        ),
        "requirements": "What are you specifically looking for?",
        "referral_source": "Thank you. How did you hear about us?",
        "whatsapp_confirmed": (
            "Thank you. Is this WhatsApp number the best number to reach you?"
        ),
        "preferred_phone": "Please share the best phone number to reach you.",
        "whatsapp_confirmation_unclear": (
            "Please reply Yes if this is the best number to reach you, or No if you "
            "would prefer us to use another number."
        ),
        "invalid_phone": "Please share a valid phone number, including country code.",
        "completion": "Thank you. I will send you a booking link now.",
        "completion_with_booking_link": (
            "Thank you. Please book a time here: {booking_link}"
        ),
        "completion_pending_booking_link": (
            "Thank you. I will send you a booking link shortly."
        ),
        "language_changed_to_english": (
            "Language changed to English. We'll continue from where we left off."
        ),
        "human_handoff": "Thank you. A team member will follow up with you shortly.",
        "whatsapp_menu": (
            "Please choose an option:\n"
            "1. Continue current conversation\n"
            "2. Restart qualification\n"
            "3. Change language\n"
            "4. Talk to human"
        ),
        "restart_intro": (
            "Sure, let's start again. Are you looking for a new website or to "
            "upgrade your existing website?"
        ),
        "generic_retry": "Could you please provide a little more detail?",
        "generic_error": "Sorry, I could not process that. Please try again.",
    },
    "ar": {
        "project_type": "ما نوع الموقع الإلكتروني الذي تحتاجه؟",
        "requirements": "ما الذي تبحث عنه تحديدًا؟",
        "referral_source": "شكرًا لك. كيف سمعت عنا؟",
        "whatsapp_confirmed": "شكرًا لك. هل رقم واتساب هذا هو أفضل رقم للتواصل معك؟",
        "preferred_phone": "يرجى مشاركة أفضل رقم هاتف يمكننا التواصل معك من خلاله.",
        "whatsapp_confirmation_unclear": (
            "يرجى الرد بنعم إذا كان هذا هو أفضل رقم للتواصل معك، "
            "أو بلا إذا كنت تفضل رقمًا آخر."
        ),
        "invalid_phone": "يرجى إرسال رقم هاتف صحيح مع رمز الدولة.",
        "completion": "شكرًا لك. سأرسل لك رابط الحجز الآن.",
        "completion_with_booking_link": (
            "شكرًا لك. يرجى حجز موعد من هنا: {booking_link}"
        ),
        "completion_pending_booking_link": (
            "شكرًا لك. سأرسل لك رابط الحجز قريبًا."
        ),
        "language_changed_to_arabic": (
            "تم تغيير اللغة إلى العربية. سنكمل من حيث توقفنا."
        ),
        "human_handoff": "شكرًا لك. سيتواصل معك أحد أعضاء فريقنا قريبًا.",
        "whatsapp_menu": (
            "يرجى اختيار أحد الخيارات:\n"
            "1. متابعة المحادثة الحالية\n"
            "2. إعادة بدء التأهيل\n"
            "3. تغيير اللغة\n"
            "4. التحدث مع موظف"
        ),
        "restart_intro": (
            "أكيد، خلينا نبدأ من جديد. هل تبحث عن موقع جديد أم ترقية موقعك الحالي؟"
        ),
        "generic_retry": "هل يمكنك تزويدنا بمزيد من التفاصيل؟",
        "generic_error": "عذرًا، لم أتمكن من معالجة رسالتك. يرجى المحاولة مرة أخرى.",
    },
}


class UnknownMessageKeyError(KeyError):
    """Raised when a message catalog key is missing."""


def get_customer_message(
    *,
    language: str,
    key: str,
    **kwargs: object,
) -> str:
    """Return a customer-facing message for the supported conversation language."""
    normalized_language = normalize_conversation_language(language)
    catalog = QUALIFICATION_MESSAGES.get(normalized_language, QUALIFICATION_MESSAGES[LANGUAGE_ENGLISH])
    try:
        message = catalog[key]
    except KeyError:
        logger.error(
            "unknown_qualification_message_key",
            extra={"message_key": key, "language": normalized_language},
        )
        raise UnknownMessageKeyError(key) from None

    if kwargs:
        return message.format(**kwargs)
    return message


def get_qualification_question(*, language: str, field: str) -> str:
    """Return the qualification question text for a field and language."""
    return get_customer_message(language=language, key=field)


def get_language_changed_confirmation_message(*, language: str) -> str:
    """Return the customer-facing confirmation after an in-flight language change."""
    normalized_language = normalize_conversation_language(language)
    if normalized_language == LANGUAGE_ARABIC:
        return get_customer_message(language=LANGUAGE_ARABIC, key="language_changed_to_arabic")
    return get_customer_message(language=LANGUAGE_ENGLISH, key="language_changed_to_english")


# Backward-compatible English question mapping used by existing imports/tests.
QUESTIONS: dict[str, str] = {
    field: QUALIFICATION_MESSAGES[LANGUAGE_ENGLISH][field] for field in QUALIFICATION_QUESTION_KEYS
}
