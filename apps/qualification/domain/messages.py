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
    "customer_type",
    "referral_source",
    "business_type",
    "website_status",
    "paid_ads",
    "main_goal",
    "launch_timeline",
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
    "faq_timeline",
    "faq_unsupported",
    "small_talk_greeting",
    "small_talk_wellbeing",
    "small_talk_greeting_wellbeing",
    "small_talk_identity",
    "small_talk_about",
    "small_talk_role",
    "small_talk_role_alt",
    "referral_source_voice",
    "referral_source_new_customer_intro",
    "referral_source_new_customer_intro_voice",
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
    "existing_customer_connecting",
    "existing_customer_connecting_voice",
    "existing_customer_welcome_back",
    "existing_customer_welcome_back_voice",
    "existing_customer_noura_followup",
    "existing_customer_noura_followup_voice",
    "existing_customer_please_wait",
    "existing_customer_please_wait_voice",
    "generic_retry",
    "generic_error",
    "whatsapp_menu",
    "restart_intro",
    "onboarding_intro",
    "onboarding_intro_voice",
    "onboarding_welcome_back",
    "onboarding_welcome_back_voice",
    "after_customer_type_captured",
    "after_referral_source_captured",
    "after_numbered_option_captured",
    "post_booking_default",
    "post_booking_greeting",
    "post_booking_wellbeing",
    "post_booking_greeting_wellbeing",
    "post_booking_thanks",
    "post_booking_exit",
    "post_booking_resend_request",
    "voice_transcription_unclear",
    "voice_transcription_unclear_spoken",
)

QUALIFICATION_MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "customer_type": (
            "Are you a new customer or an existing customer?\n"
            "1. New customer\n"
            "2. Existing customer"
        ),
        "referral_source": (
            "How did you hear about us?\n"
            "1. Google\n"
            "2. Instagram\n"
            "3. Facebook\n"
            "4. Friend / Referral\n"
            "5. Other"
        ),
        "referral_source_voice": (
            "How did you hear about us? You can say Google, Instagram, Facebook, "
            "Friend Referral, or Other."
        ),
        "referral_source_new_customer_intro": (
            "Hi, this is Noura from Good Websites. Great to meet you.\n\n"
            "How did you hear about us?\n"
            "1. Google\n"
            "2. Instagram\n"
            "3. Facebook\n"
            "4. Friend / Referral\n"
            "5. Other"
        ),
        "referral_source_new_customer_intro_voice": (
            "Hi, this is Noura from Good Websites. Great to meet you. "
            "How did you hear about us? You can say Google, Instagram, Facebook, "
            "friend referral, or other."
        ),
        "whatsapp_confirmed": (
            "Is this the best contact number for our team to reach you?"
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
            "A website specialist can guide you properly in the meeting."
        ),
        "faq_timeline": (
            "Timeline depends on the project scope. A website specialist can guide you "
            "properly in the meeting."
        ),
        "faq_unsupported": (
            "That's a good question. A website specialist can guide you properly in "
            "the meeting."
        ),
        "small_talk_greeting": "Hi!",
        "small_talk_wellbeing": "I'm doing well, thanks for asking.",
        "small_talk_greeting_wellbeing": "Hi, I'm doing well, thanks for asking.",
        "small_talk_identity": "I'm Noura from Good Websites.",
        "small_talk_about": (
            "I'm Noura from Good Websites. I help with website inquiries and connect "
            "customers with the right specialist."
        ),
        "small_talk_role": (
            "I help Good Websites understand your website needs and connect you with "
            "the right specialist."
        ),
        "small_talk_role_alt": (
            "I help customers share their website requirements and connect with the "
            "Good Websites team."
        ),
        "llm_parse_fallback": (
            "Could you please provide a little more detail?"
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
            "Perfect, thank you. I've sent the booking link above. "
            "You can choose a time whenever you're ready."
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
        "existing_customer_connecting": (
            "Connecting you with a live agent. Please wait a moment."
        ),
        "existing_customer_connecting_voice": (
            "Connecting you with a live agent. Please wait a moment."
        ),
        "existing_customer_welcome_back": (
            "Hi, this is Noura from Good Websites. Welcome back!"
        ),
        "existing_customer_welcome_back_voice": (
            "Hi, this is Noura from Good Websites. Welcome back!"
        ),
        "existing_customer_noura_followup": (
            "Hi this is Noura from Good Websites. How may I help you today?"
        ),
        "existing_customer_noura_followup_voice": (
            "Hi this is Noura from Good Websites. How may I help you today?"
        ),
        "existing_customer_please_wait": (
            "Connecting you with a live agent. Please wait a moment."
        ),
        "existing_customer_please_wait_voice": (
            "Connecting you with a live agent. Please wait a moment."
        ),
        "whatsapp_menu": (
            "Please choose an option:\n"
            "1. Continue current conversation\n"
            "2. Restart qualification\n"
            "3. Change language\n"
            "4. Talk to human"
        ),
        "restart_intro": "Sure, let's start again.",
        "onboarding_intro": (
            "Hi, this is Noura from Good Websites!\n"
            "\n"
            "To get started, I'll ask a few quick questions so our team can understand "
            "your project and guide you toward booking a meeting."
        ),
        "onboarding_intro_voice": (
            "Hi, this is Noura from Good Websites. I've sent the chat instructions "
            "in text. Let's continue."
        ),
        "onboarding_welcome_back": "Welcome back! Let's continue.",
        "onboarding_welcome_back_voice": "Welcome back. Let's continue.",
        "after_customer_type_captured": "Thank you.",
        "after_referral_source_captured": "Thanks.",
        "after_numbered_option_captured": "Thanks.",
        "post_booking_default": (
            "Please use the booking link above whenever you're ready."
        ),
        "post_booking_greeting": (
            "Hi. Please use the booking link above whenever you're ready."
        ),
        "post_booking_wellbeing": (
            "I'm doing well, thanks for asking. Please use the booking link above "
            "whenever you're ready."
        ),
        "post_booking_greeting_wellbeing": (
            "I'm doing well, thanks for asking. Please use the booking link above "
            "whenever you're ready."
        ),
        "post_booking_thanks": (
            "You're welcome. Please use the booking link above whenever you're ready."
        ),
        "post_booking_exit": (
            "No problem. You can use the booking link above whenever you're ready, "
            "or message us again anytime."
        ),
        "post_booking_resend_request": (
            "The booking link is already shared above. Please use that link whenever "
            "you're ready."
        ),
        "voice_transcription_unclear": (
            "Sorry, I couldn't understand the voice note clearly. "
            "Please send it again or reply by text."
        ),
        "voice_transcription_unclear_spoken": (
            "Sorry, I couldn't understand the voice note clearly. Please send it again."
        ),
        "generic_retry": "Could you please provide a little more detail?",
        "generic_error": "Sorry, I could not process that. Please try again.",
    },
    "ar": {
        "customer_type": (
            "هل أنت عميل جديد أم عميل حالي؟\n"
            "1. عميل جديد\n"
            "2. عميل حالي"
        ),
        "referral_source": (
            "كيف سمعت عنا؟\n"
            "1. جوجل\n"
            "2. إنستغرام\n"
            "3. فيسبوك\n"
            "4. صديق / إحالة\n"
            "5. أخرى"
        ),
        "referral_source_voice": (
            "كيف سمعت عنا؟ يمكنك اختيار جوجل، إنستغرام، فيسبوك، صديق أو إحالة، أو أخرى."
        ),
        "referral_source_new_customer_intro": (
            "مرحبًا، معك نورة من Good Websites. سعداء بتواصلك معنا.\n\n"
            "كيف سمعت عنا؟\n"
            "1. جوجل\n"
            "2. إنستغرام\n"
            "3. فيسبوك\n"
            "4. صديق / إحالة\n"
            "5. أخرى"
        ),
        "referral_source_new_customer_intro_voice": (
            "مرحبًا، معك نورة من Good Websites. سعداء بتواصلك معنا. "
            "كيف سمعت عنا؟ يمكنك اختيار جوجل، إنستغرام، فيسبوك، صديق أو إحالة، أو أخرى."
        ),
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
            "يمكن لأخصائي المواقع إرشادك بشكل مناسب في الاجتماع."
        ),
        "faq_timeline": (
            "يعتمد الجدول الزمني على نطاق المشروع. يمكن لأخصائي المواقع إرشادك بشكل "
            "مناسب في الاجتماع."
        ),
        "faq_unsupported": (
            "سؤال جيد. يمكن لأخصائي المواقع إرشادك بشكل مناسب في الاجتماع."
        ),
        "small_talk_greeting": "مرحبًا!",
        "small_talk_wellbeing": "أنا بخير، شكرًا لسؤالك.",
        "small_talk_greeting_wellbeing": "مرحبًا، أنا بخير، شكرًا لسؤالك.",
        "small_talk_identity": "أنا نورة من Good Websites.",
        "small_talk_about": (
            "أنا نورة من Good Websites. أساعد في استفسارات المواقع وربط العملاء بالمختص المناسب."
        ),
        "small_talk_role": (
            "أساعد Good Websites على فهم احتياجات موقعك الإلكتروني وربطك بالمختص المناسب."
        ),
        "small_talk_role_alt": (
            "أساعد العملاء على مشاركة متطلبات مواقعهم والتواصل مع فريق Good Websites."
        ),
        "llm_parse_fallback": (
            "هل يمكنك تزويدنا بمزيد من التفاصيل؟"
        ),
        "requirement_acknowledged": "شكرًا لك، لقد سجّلت ذلك.",
        "irrelevant_redirect": (
            "أفهم ذلك. للتأكد من أن فريقنا يمكنه مساعدتك بشكل مناسب، "
            "سأجمع فقط بعض تفاصيل المشروع الأساسية."
        ),
        "invalid_phone": "يرجى إرسال رقم هاتف صحيح مع رمز الدولة.",
        "completion": "رائع، شكرًا لك. يمكنك حجز موعد من هنا: {booking_link}",
        "completion_with_booking_link": (
            "رائع، شكرًا لك. يمكنك حجز موعد من هنا: {booking_link}"
        ),
        "completion_spoken": (
            "رائع، شكرًا لك. لقد أرسلت رابط الحجز أعلاه. "
            "يمكنك اختيار الوقت المناسب لك."
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
        "existing_customer_connecting": (
            "نقوم بتوصيلك مع وكيل مباشر. يرجى الانتظار لحظة."
        ),
        "existing_customer_connecting_voice": (
            "نقوم بتوصيلك مع وكيل مباشر. يرجى الانتظار لحظة."
        ),
        "existing_customer_welcome_back": (
            "مرحبًا، معك نورة من Good Websites. مرحبًا بعودتك!"
        ),
        "existing_customer_welcome_back_voice": (
            "مرحبًا، معك نورة من Good Websites. مرحبًا بعودتك!"
        ),
        "existing_customer_noura_followup": (
            "مرحبًا، معك نورة من Good Websites. كيف يمكنني مساعدتك اليوم؟"
        ),
        "existing_customer_noura_followup_voice": (
            "مرحبًا، معك نورة من Good Websites. كيف يمكنني مساعدتك اليوم؟"
        ),
        "existing_customer_please_wait": (
            "نقوم بتوصيلك مع وكيل مباشر. يرجى الانتظار لحظة."
        ),
        "existing_customer_please_wait_voice": (
            "نقوم بتوصيلك مع وكيل مباشر. يرجى الانتظار لحظة."
        ),
        "whatsapp_menu": (
            "يرجى اختيار أحد الخيارات:\n"
            "1. متابعة المحادثة الحالية\n"
            "2. إعادة بدء التأهيل\n"
            "3. تغيير اللغة\n"
            "4. التحدث مع موظف"
        ),
        "restart_intro": "أكيد، خلينا نبدأ من جديد.",
        "onboarding_intro": (
            "مرحبًا، معك نورة من Good Websites!\n"
            "\n"
            "لنبدأ، سأطرح بعض الأسئلة السريعة حتى يفهم فريقنا مشروعك ويرشدك نحو حجز اجتماع."
        ),
        "onboarding_intro_voice": (
            "مرحبًا، معك نورة من Good Websites. أرسلت تعليمات المحادثة في رسالة نصية. "
            "لنتابع."
        ),
        "onboarding_welcome_back": "مرحبًا بعودتك! لنكمل.",
        "onboarding_welcome_back_voice": "مرحبًا بعودتك. لنكمل.",
        "after_customer_type_captured": "شكرًا لك.",
        "after_referral_source_captured": "شكرًا.",
        "after_numbered_option_captured": "شكرًا.",
        "post_booking_default": "يرجى استخدام رابط الحجز أعلاه عندما تكون جاهزًا.",
        "post_booking_greeting": (
            "مرحبًا. يرجى استخدام رابط الحجز أعلاه عندما تكون جاهزًا."
        ),
        "post_booking_wellbeing": (
            "أنا بخير، شكرًا لسؤالك. يرجى استخدام رابط الحجز أعلاه عندما تكون جاهزًا."
        ),
        "post_booking_greeting_wellbeing": (
            "أنا بخير، شكرًا لسؤالك. يرجى استخدام رابط الحجز أعلاه عندما تكون جاهزًا."
        ),
        "post_booking_thanks": (
            "على الرحب والسعة. يرجى استخدام رابط الحجز أعلاه عندما تكون جاهزًا."
        ),
        "post_booking_exit": (
            "لا مشكلة. يمكنك استخدام رابط الحجز أعلاه متى ما كنت مستعدًا، "
            "أو مراسلتنا مرة أخرى في أي وقت."
        ),
        "post_booking_resend_request": (
            "رابط الحجز موجود أعلاه بالفعل. يرجى استخدامه متى ما كنت مستعدًا."
        ),
        "voice_transcription_unclear": (
            "عذرًا، لم أتمكن من فهم الملاحظة الصوتية بوضوح. "
            "يرجى إرسالها مرة أخرى أو الرد بالنص."
        ),
        "voice_transcription_unclear_spoken": (
            "عذرًا، لم أتمكن من فهم الملاحظة الصوتية بوضوح. يرجى إرسالها مرة أخرى."
        ),
        "generic_retry": "هل يمكنك تزويدنا بمزيد من التفاصيل؟",
        "generic_error": "عذرًا، لم أتمكن من معالجة رسالتك. يرجى المحاولة مرة أخرى.",
    },
}


def _seed_numbered_qualification_messages() -> None:
    """Populate bilingual numbered-question prompts from the option catalog."""
    from apps.qualification.domain.numbered_qualification import (
        NUMBERED_QUALIFICATION_FIELDS,
        format_numbered_question,
    )

    for language in (LANGUAGE_ENGLISH, LANGUAGE_ARABIC):
        for field in NUMBERED_QUALIFICATION_FIELDS:
            QUALIFICATION_MESSAGES[language][field] = format_numbered_question(
                field=field,
                language=language,
            )


_seed_numbered_qualification_messages()


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
