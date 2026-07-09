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
    "whatsapp_confirmation_noted_reask",
    "whatsapp_confirmation_also_reask",
    "preferred_phone_after_whatsapp_decline",
    "faq_services",
    "faq_location",
    "faq_pricing",
    "faq_unsupported",
    "llm_parse_fallback",
    "requirement_acknowledged",
    "irrelevant_redirect",
    "invalid_phone",
    "completion",
    "completion_with_booking_link",
    "completion_spoken",
    "completion_whatsapp_booking_link",
    "completion_pending_booking_link",
    "whatsapp_confirmation_noted_reask_voice",
    "whatsapp_confirmation_also_reask_voice",
    "human_handoff",
    "generic_retry",
    "generic_error",
    "whatsapp_menu",
    "restart_intro",
    "onboarding_intro",
    "onboarding_intro_voice",
    "onboarding_welcome_back",
    "onboarding_welcome_back_voice",
)

QUALIFICATION_MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "project_type": (
            "*To get started:*\n"
            "Are you looking for a *new website*, an *upgrade to your existing website*, "
            "or *both*?"
        ),
        "requirements": "What are you specifically looking for?",
        "referral_source": "Thank you. How did you hear about us?",
        "whatsapp_confirmed": (
            "Thank you. Is this WhatsApp number the best number to reach you?"
        ),
        "preferred_phone": "Please share the best phone number to reach you.",
        "preferred_phone_after_whatsapp_decline": (
            "No problem. Please share the best phone number to reach you."
        ),
        "whatsapp_confirmation_unclear": (
            "Please reply Yes if this is the best number to reach you, or No if you "
            "would prefer us to use another number."
        ),
        "whatsapp_confirmation_noted_reask": (
            "Thank you, I've noted that. Is this WhatsApp number the best number to "
            "reach you? Please reply Yes or No."
        ),
        "whatsapp_confirmation_also_reask": (
            "Also, is this WhatsApp number the best number to reach you? "
            "Please reply Yes or No."
        ),
        "faq_services": (
            "We provide website design, website upgrades, automation, AI chatbot, "
            "SEO, and related digital solutions."
        ),
        "faq_location": "We work remotely and can support clients online.",
        "faq_pricing": (
            "Pricing depends on the scope, features, and timeline. Our team can guide "
            "you properly in the meeting."
        ),
        "faq_unsupported": (
            "That's a good question. I don't want to give you the wrong information "
            "here, but our team will guide you properly in the meeting."
        ),
        "llm_parse_fallback": (
            "Thank you, I've noted that. Our team will guide you properly in the "
            "meeting. May I ask one more quick question?"
        ),
        "requirement_acknowledged": "Thank you, I've noted that.",
        "irrelevant_redirect": (
            "I understand. To make sure our team can help you properly, "
            "I'll just collect a few basic project details."
        ),
        "invalid_phone": "Please share a valid phone number, including country code.",
        "completion": "Perfect, thank you. Please book a time here: {booking_link}",
        "completion_with_booking_link": (
            "Perfect, thank you. Please book a time here: {booking_link}"
        ),
        "completion_spoken": (
            "Perfect, thank you. I'll send the booking link to your WhatsApp now."
        ),
        "completion_whatsapp_booking_link": "Please book a time here: {booking_link}",
        "completion_pending_booking_link": (
            "Thank you. I will send you a booking link shortly."
        ),
        "whatsapp_confirmation_noted_reask_voice": (
            "Thank you, I've noted that. Is this WhatsApp number the best number to "
            "reach you? Please say yes or no."
        ),
        "whatsapp_confirmation_also_reask_voice": (
            "Also, is this WhatsApp number the best number to reach you? "
            "Please say yes or no."
        ),
        "language_changed_to_english": (
            "Language set to English. We can continue from here."
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
        "onboarding_intro": (
            "*Hi, welcome!* 👋\n"
            "\n"
            "I’ll ask a few quick questions so our team can understand your project "
            "and send you the right booking link.\n"
            "\n"
            "*How to use this chat:*\n"
            "• Send *M* to open the menu\n"
            "• To change language, send *M* and choose *Change language*\n"
            "• You can reply by *text* or *voice note*"
        ),
        "onboarding_intro_voice": (
            "Hi, welcome. I've sent the chat instructions in text. Let's continue."
        ),
        "onboarding_welcome_back": (
            "*Welcome back!* 👋\n"
            "\n"
            "I’ll continue from where we left off.\n"
            "\n"
            "*Quick reminders:*\n"
            "• Send *M* to open the menu\n"
            "• To change language, send *M* and choose *Change language*\n"
            "• You can reply by *text* or *voice note*"
        ),
        "onboarding_welcome_back_voice": (
            "Welcome back. I've sent the quick reminders in text. Let's continue."
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
        "preferred_phone_after_whatsapp_decline": (
            "لا بأس. يرجى مشاركة أفضل رقم هاتف يمكننا التواصل معك من خلاله."
        ),
        "whatsapp_confirmation_unclear": (
            "يرجى الرد بنعم إذا كان هذا هو أفضل رقم للتواصل معك، "
            "أو بلا إذا كنت تفضل رقمًا آخر."
        ),
        "whatsapp_confirmation_noted_reask": (
            "شكرًا لك، لقد سجّلت ذلك. هل رقم واتساب هذا هو أفضل رقم للتواصل معك؟ "
            "يرجى الرد بنعم أو لا."
        ),
        "whatsapp_confirmation_also_reask": (
            "أيضًا، هل رقم واتساب هذا هو أفضل رقم للتواصل معك؟ "
            "يرجى الرد بنعم أو لا."
        ),
        "faq_services": (
            "نقدّم تصميم المواقع، ترقية المواقع، الأتمتة، روبوتات الدردشة الذكية، "
            "والحلول الرقمية ذات الصلة."
        ),
        "faq_location": "نعمل عن بُعد ويمكننا دعم العملاء عبر الإنترنت.",
        "faq_pricing": (
            "تعتمد الأسعار على نطاق المشروع والميزات والجدول الزمني. "
            "سيرشدك الفريق بشكل مناسب في الاجتماع."
        ),
        "faq_unsupported": (
            "سؤال جيد. لا أريد إعطاءك معلومات خاطئة هنا، "
            "لكن فريقنا سيرشدك بشكل مناسب في الاجتماع."
        ),
        "llm_parse_fallback": (
            "شكرًا لك، لقد سجّلت ذلك. سيرشدك فريقنا بشكل مناسب في الاجتماع. "
            "هل يمكنني طرح سؤال سريع آخر؟"
        ),
        "requirement_acknowledged": "شكرًا لك، لقد سجّلت ذلك.",
        "irrelevant_redirect": (
            "أفهم ذلك. للتأكد من أن فريقنا يمكنه مساعدتك بشكل مناسب، "
            "سأجمع فقط بعض تفاصيل المشروع الأساسية."
        ),
        "invalid_phone": "يرجى إرسال رقم هاتف صحيح مع رمز الدولة.",
        "completion": "ممتاز، شكرًا لك. يرجى حجز موعد من هنا: {booking_link}",
        "completion_with_booking_link": (
            "ممتاز، شكرًا لك. يرجى حجز موعد من هنا: {booking_link}"
        ),
        "completion_spoken": (
            "ممتاز، شكرًا لك. سأرسل رابط الحجز إلى واتساب الآن."
        ),
        "completion_whatsapp_booking_link": "يرجى حجز موعد من هنا: {booking_link}",
        "completion_pending_booking_link": (
            "شكرًا لك. سأرسل لك رابط الحجز قريبًا."
        ),
        "whatsapp_confirmation_noted_reask_voice": (
            "شكرًا لك، لقد سجّلت ذلك. هل رقم واتساب هذا هو أفضل رقم للتواصل معك؟ "
            "يرجى قول نعم أو لا."
        ),
        "whatsapp_confirmation_also_reask_voice": (
            "أيضًا، هل رقم واتساب هذا هو أفضل رقم للتواصل معك؟ "
            "يرجى قول نعم أو لا."
        ),
        "language_changed_to_arabic": (
            "تم ضبط اللغة إلى العربية. يمكننا المتابعة من هنا."
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
        "onboarding_intro": (
            "*مرحبًا بك!* 👋\n"
            "\n"
            "سأطرح بعض الأسئلة السريعة حتى يفهم فريقنا مشروعك ويرسل لك "
            "رابط الحجز المناسب.\n"
            "\n"
            "*طريقة استخدام هذه المحادثة:*\n"
            "• أرسل *M* لفتح القائمة\n"
            "• لتغيير اللغة، أرسل *M* ثم اختر *تغيير اللغة*\n"
            "• يمكنك الرد بـ *النص* أو *الملاحظة الصوتية*"
        ),
        "onboarding_intro_voice": (
            "مرحبًا بك. أرسلت تعليمات المحادثة في رسالة نصية. لنتابع."
        ),
        "onboarding_welcome_back": (
            "*مرحبًا بعودتك!* 👋\n"
            "\n"
            "سأتابع من حيث توقفنا.\n"
            "\n"
            "*تذكير سريع:*\n"
            "• أرسل *M* لفتح القائمة\n"
            "• لتغيير اللغة، أرسل *M* ثم اختر *تغيير اللغة*\n"
            "• يمكنك الرد بـ *النص* أو *الملاحظة الصوتية*"
        ),
        "onboarding_welcome_back_voice": (
            "مرحبًا بعودتك. أرسلت التذكيرات السريعة في رسالة نصية. لنكمل."
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
