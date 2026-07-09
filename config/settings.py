"""WebLead Django settings."""

from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    N8N_FORWARD_TIMEOUT_SECONDS=(int, 5),
)

env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(str(env_file))

SECRET_KEY = env("DJANGO_SECRET_KEY", default="weblead-dev-secret-change-me")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "apps.webhooks.apps.WebhooksConfig",
    "apps.qualification.apps.QualificationConfig",
]

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
    "EXCEPTION_HANDLER": (
        "apps.qualification.api.exceptions.qualification_exception_handler"
    ),
}

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "data" / "qualification.sqlite3",
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Reverse-proxy HTTPS: Twilio signs the public URL Twilio requested.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

TWILIO_AUTH_TOKEN = env("TWILIO_AUTH_TOKEN", default="")
TWILIO_ACCOUNT_SID = env("TWILIO_ACCOUNT_SID", default="")
# Twilio Content Template SID for the bilingual language Quick Reply (optional until configured).
TWILIO_LANGUAGE_PICKER_CONTENT_SID = env("TWILIO_LANGUAGE_PICKER_CONTENT_SID", default="")
# Twilio Content Template SID for the clickable WhatsApp menu (optional; plain-text fallback when unset).
TWILIO_MENU_CONTENT_SID = env("TWILIO_MENU_CONTENT_SID", default="")
# Twilio list-picker main menu Content Template SID (preferred name; falls back to TWILIO_MENU_CONTENT_SID).
TWILIO_WHATSAPP_MENU_CONTENT_SID = (
    env("TWILIO_WHATSAPP_MENU_CONTENT_SID", default="") or TWILIO_MENU_CONTENT_SID
)
# WhatsApp sender used when sending Content API messages (optional until outbound send is wired).
TWILIO_WHATSAPP_FROM_NUMBER = env("TWILIO_WHATSAPP_FROM_NUMBER", default="")
# Master switch for WhatsApp lead qualification flows (menu, inactivity, extraction).
LEAD_QUALIFICATION_ENABLED = env.bool("LEAD_QUALIFICATION_ENABLED", default=True)

_TWILIO_MEDIA_DOWNLOAD_TIMEOUT_SECONDS_ERROR = (
    "TWILIO_MEDIA_DOWNLOAD_TIMEOUT_SECONDS must be a positive integer."
)


def _load_twilio_media_download_timeout_seconds() -> int:
    raw_value = env("TWILIO_MEDIA_DOWNLOAD_TIMEOUT_SECONDS", default="20") or "20"
    try:
        timeout_seconds = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(_TWILIO_MEDIA_DOWNLOAD_TIMEOUT_SECONDS_ERROR) from exc
    if timeout_seconds <= 0:
        raise ImproperlyConfigured(_TWILIO_MEDIA_DOWNLOAD_TIMEOUT_SECONDS_ERROR)
    return timeout_seconds


TWILIO_MEDIA_DOWNLOAD_TIMEOUT_SECONDS = _load_twilio_media_download_timeout_seconds()

_TWILIO_MEDIA_MAX_BYTES_ERROR = "TWILIO_MEDIA_MAX_BYTES must be a positive integer."


def _load_twilio_media_max_bytes() -> int:
    raw_value = env("TWILIO_MEDIA_MAX_BYTES", default="10485760") or "10485760"
    try:
        max_bytes = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(_TWILIO_MEDIA_MAX_BYTES_ERROR) from exc
    if max_bytes <= 0:
        raise ImproperlyConfigured(_TWILIO_MEDIA_MAX_BYTES_ERROR)
    return max_bytes


TWILIO_MEDIA_MAX_BYTES = _load_twilio_media_max_bytes()
N8N_WHATSAPP_WEBHOOK_URL = env("N8N_WHATSAPP_WEBHOOK_URL", default="")
N8N_WEBHOOK_SECRET = env("N8N_WEBHOOK_SECRET", default="")
N8N_FORWARD_TIMEOUT_SECONDS = env.int("N8N_FORWARD_TIMEOUT_SECONDS", default=5)
N8N_QUALIFICATION_API_SECRET = env("N8N_QUALIFICATION_API_SECRET", default="")
WEBLEAD_VOICE_EVENT_SECRET = env("WEBLEAD_VOICE_EVENT_SECRET", default="")

_QUALIFICATION_CONFIDENCE_THRESHOLD_ERROR = (
    "QUALIFICATION_CONFIDENCE_THRESHOLD must be a float greater than 0 "
    "and less than or equal to 1."
)


def _load_qualification_confidence_threshold() -> float:
    raw_value = env("QUALIFICATION_CONFIDENCE_THRESHOLD", default="0.75")
    try:
        threshold = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(_QUALIFICATION_CONFIDENCE_THRESHOLD_ERROR) from exc
    if not 0 < threshold <= 1:
        raise ImproperlyConfigured(_QUALIFICATION_CONFIDENCE_THRESHOLD_ERROR)
    return threshold


QUALIFICATION_CONFIDENCE_THRESHOLD = _load_qualification_confidence_threshold()

OPENROUTER_API_KEY = env("OPENROUTER_API_KEY", default="")
OPENROUTER_MODEL = env("OPENROUTER_MODEL", default="")

_OPENROUTER_TIMEOUT_SECONDS_ERROR = (
    "OPENROUTER_TIMEOUT_SECONDS must be a positive integer."
)


def _load_openrouter_base_url() -> str:
    base_url = env("OPENROUTER_BASE_URL", default="https://openrouter.ai/api/v1")
    return base_url.rstrip("/")


def _load_openrouter_timeout_seconds() -> int:
    raw_value = env("OPENROUTER_TIMEOUT_SECONDS", default="20") or "20"
    try:
        timeout_seconds = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(_OPENROUTER_TIMEOUT_SECONDS_ERROR) from exc
    if timeout_seconds <= 0:
        raise ImproperlyConfigured(_OPENROUTER_TIMEOUT_SECONDS_ERROR)
    return timeout_seconds


OPENROUTER_BASE_URL = _load_openrouter_base_url()
OPENROUTER_TIMEOUT_SECONDS = _load_openrouter_timeout_seconds()

_OPENROUTER_MAX_TOKENS_ERROR = "OPENROUTER_MAX_TOKENS must be a positive integer."
_OPENROUTER_COMPLETION_MAX_TOKENS_ERROR = (
    "OPENROUTER_COMPLETION_MAX_TOKENS must be a positive integer."
)


def _load_openrouter_max_tokens() -> int:
    raw_value = env("OPENROUTER_MAX_TOKENS", default="768") or "768"
    try:
        max_tokens = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(_OPENROUTER_MAX_TOKENS_ERROR) from exc
    if max_tokens <= 0:
        raise ImproperlyConfigured(_OPENROUTER_MAX_TOKENS_ERROR)
    return max_tokens


OPENROUTER_MAX_TOKENS = _load_openrouter_max_tokens()


def _load_openrouter_completion_max_tokens() -> int:
    raw_value = env("OPENROUTER_COMPLETION_MAX_TOKENS", default="400") or "400"
    try:
        max_tokens = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(_OPENROUTER_COMPLETION_MAX_TOKENS_ERROR) from exc
    if max_tokens <= 0:
        raise ImproperlyConfigured(_OPENROUTER_COMPLETION_MAX_TOKENS_ERROR)
    return max_tokens


OPENROUTER_COMPLETION_MAX_TOKENS = _load_openrouter_completion_max_tokens()

BOOKING_LINK = (env("BOOKING_LINK", default="") or "").strip()

DEEPGRAM_API_KEY = env("DEEPGRAM_API_KEY", default="")
DEEPGRAM_MODEL = env("DEEPGRAM_MODEL", default="") or env("VOICE_AGENT_DEEPGRAM_MODEL", default="nova-2")
DEEPGRAM_LANGUAGE = env("DEEPGRAM_LANGUAGE", default="en")
DEEPGRAM_ENGLISH_MODEL = env("DEEPGRAM_ENGLISH_MODEL", default="")
DEEPGRAM_ENGLISH_LANGUAGE = env("DEEPGRAM_ENGLISH_LANGUAGE", default="")
DEEPGRAM_ARABIC_MODEL = env("DEEPGRAM_ARABIC_MODEL", default="nova-3")
DEEPGRAM_ARABIC_LANGUAGE = env("DEEPGRAM_ARABIC_LANGUAGE", default="ar")
DEEPGRAM_BASE_URL = env("DEEPGRAM_BASE_URL", default="https://api.deepgram.com").rstrip("/")

_DEEPGRAM_TIMEOUT_SECONDS_ERROR = "DEEPGRAM_TIMEOUT_SECONDS must be a positive integer."


def _load_deepgram_timeout_seconds() -> int:
    raw_value = env("DEEPGRAM_TIMEOUT_SECONDS", default="60") or "60"
    try:
        timeout_seconds = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(_DEEPGRAM_TIMEOUT_SECONDS_ERROR) from exc
    if timeout_seconds <= 0:
        raise ImproperlyConfigured(_DEEPGRAM_TIMEOUT_SECONDS_ERROR)
    return timeout_seconds


DEEPGRAM_TIMEOUT_SECONDS = _load_deepgram_timeout_seconds()

MEDIA_ROOT = BASE_DIR / "media"

SUPERTONIC_BASE_URL = env("SUPERTONIC_BASE_URL", default="http://127.0.0.1:7788").rstrip("/")
SUPERTONIC_ENGLISH_VOICE = (env("SUPERTONIC_ENGLISH_VOICE", default="F1") or "F1").strip()
SUPERTONIC_ARABIC_ENABLED = env.bool("SUPERTONIC_ARABIC_ENABLED", default=False)
SUPERTONIC_ARABIC_VOICE = (env("SUPERTONIC_ARABIC_VOICE", default="") or "").strip()
BASE_WEBHOOK_URL = env("BASE_WEBHOOK_URL", default="").rstrip("/")
PUBLIC_MEDIA_BASE_URL = env("PUBLIC_MEDIA_BASE_URL", default="").rstrip("/")

_QUALIFICATION_CONVERSATION_TTL_SECONDS_ERROR = (
    "QUALIFICATION_CONVERSATION_TTL_SECONDS must be a positive integer."
)


def _load_qualification_conversation_ttl_seconds() -> int:
    raw_value = env("QUALIFICATION_CONVERSATION_TTL_SECONDS", default="604800") or "604800"
    try:
        ttl_seconds = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(_QUALIFICATION_CONVERSATION_TTL_SECONDS_ERROR) from exc
    if ttl_seconds <= 0:
        raise ImproperlyConfigured(_QUALIFICATION_CONVERSATION_TTL_SECONDS_ERROR)
    return ttl_seconds


_QUALIFICATION_IDEMPOTENCY_TTL_SECONDS_ERROR = (
    "QUALIFICATION_IDEMPOTENCY_TTL_SECONDS must be a positive integer."
)


def _load_qualification_idempotency_ttl_seconds() -> int:
    raw_value = env("QUALIFICATION_IDEMPOTENCY_TTL_SECONDS", default="86400") or "86400"
    try:
        ttl_seconds = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(_QUALIFICATION_IDEMPOTENCY_TTL_SECONDS_ERROR) from exc
    if ttl_seconds <= 0:
        raise ImproperlyConfigured(_QUALIFICATION_IDEMPOTENCY_TTL_SECONDS_ERROR)
    return ttl_seconds


_QUALIFICATION_IDEMPOTENCY_PROCESSING_TTL_SECONDS_ERROR = (
    "QUALIFICATION_IDEMPOTENCY_PROCESSING_TTL_SECONDS must be a positive integer."
)


def _load_qualification_idempotency_processing_ttl_seconds() -> int:
    raw_value = env("QUALIFICATION_IDEMPOTENCY_PROCESSING_TTL_SECONDS", default="300") or "300"
    try:
        ttl_seconds = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(
            _QUALIFICATION_IDEMPOTENCY_PROCESSING_TTL_SECONDS_ERROR,
        ) from exc
    if ttl_seconds <= 0:
        raise ImproperlyConfigured(_QUALIFICATION_IDEMPOTENCY_PROCESSING_TTL_SECONDS_ERROR)
    return ttl_seconds


QUALIFICATION_REDIS_URL = env("QUALIFICATION_REDIS_URL", default="")
QUALIFICATION_CONVERSATION_TTL_SECONDS = _load_qualification_conversation_ttl_seconds()
QUALIFICATION_IDEMPOTENCY_TTL_SECONDS = _load_qualification_idempotency_ttl_seconds()
QUALIFICATION_IDEMPOTENCY_PROCESSING_TTL_SECONDS = (
    _load_qualification_idempotency_processing_ttl_seconds()
)

_QUALIFICATION_CONVERSATION_LOCK_WAIT_SECONDS_ERROR = (
    "QUALIFICATION_CONVERSATION_LOCK_WAIT_SECONDS must be a positive number."
)
_QUALIFICATION_CONVERSATION_LOCK_TTL_SECONDS_ERROR = (
    "QUALIFICATION_CONVERSATION_LOCK_TTL_SECONDS must be a positive integer."
)


def _load_qualification_conversation_lock_wait_seconds() -> float:
    raw_value = env("QUALIFICATION_CONVERSATION_LOCK_WAIT_SECONDS", default="6") or "6"
    try:
        wait_seconds = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(_QUALIFICATION_CONVERSATION_LOCK_WAIT_SECONDS_ERROR) from exc
    if wait_seconds <= 0:
        raise ImproperlyConfigured(_QUALIFICATION_CONVERSATION_LOCK_WAIT_SECONDS_ERROR)
    return wait_seconds


def _load_qualification_conversation_lock_ttl_seconds() -> int:
    raw_value = env("QUALIFICATION_CONVERSATION_LOCK_TTL_SECONDS", default="60") or "60"
    try:
        ttl_seconds = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(_QUALIFICATION_CONVERSATION_LOCK_TTL_SECONDS_ERROR) from exc
    if ttl_seconds <= 0:
        raise ImproperlyConfigured(_QUALIFICATION_CONVERSATION_LOCK_TTL_SECONDS_ERROR)
    return ttl_seconds


QUALIFICATION_CONVERSATION_LOCK_WAIT_SECONDS = _load_qualification_conversation_lock_wait_seconds()
QUALIFICATION_CONVERSATION_LOCK_TTL_SECONDS = _load_qualification_conversation_lock_ttl_seconds()

_LANGUAGE_PICKER_PENDING_TIMEOUT_SECONDS_ERROR = (
    "LANGUAGE_PICKER_PENDING_TIMEOUT_SECONDS must be a positive integer."
)


def _load_language_picker_pending_timeout_seconds() -> int:
    raw_value = env("LANGUAGE_PICKER_PENDING_TIMEOUT_SECONDS", default="900") or "900"
    try:
        timeout_seconds = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(_LANGUAGE_PICKER_PENDING_TIMEOUT_SECONDS_ERROR) from exc
    if timeout_seconds <= 0:
        raise ImproperlyConfigured(_LANGUAGE_PICKER_PENDING_TIMEOUT_SECONDS_ERROR)
    return timeout_seconds


LANGUAGE_PICKER_PENDING_TIMEOUT_SECONDS = _load_language_picker_pending_timeout_seconds()

_WHATSAPP_MENU_INACTIVITY_SECONDS_ERROR = (
    "WHATSAPP_MENU_INACTIVITY_SECONDS must be a positive integer."
)


def _load_whatsapp_menu_inactivity_seconds() -> int:
    raw_value = env("WHATSAPP_MENU_INACTIVITY_SECONDS", default="600") or "600"
    try:
        timeout_seconds = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(_WHATSAPP_MENU_INACTIVITY_SECONDS_ERROR) from exc
    if timeout_seconds <= 0:
        raise ImproperlyConfigured(_WHATSAPP_MENU_INACTIVITY_SECONDS_ERROR)
    return timeout_seconds


WHATSAPP_MENU_INACTIVITY_SECONDS = _load_whatsapp_menu_inactivity_seconds()

_ONBOARDING_REINTRO_AFTER_SECONDS_ERROR = (
    "ONBOARDING_REINTRO_AFTER_SECONDS must be a positive integer."
)


def _load_onboarding_reintro_after_seconds() -> int:
    raw_value = env("ONBOARDING_REINTRO_AFTER_SECONDS", default="60") or "60"
    try:
        timeout_seconds = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(_ONBOARDING_REINTRO_AFTER_SECONDS_ERROR) from exc
    if timeout_seconds <= 0:
        raise ImproperlyConfigured(_ONBOARDING_REINTRO_AFTER_SECONDS_ERROR)
    return timeout_seconds


# Idle gap after which returning customers restart qualification and see onboarding again.
ONBOARDING_REINTRO_AFTER_SECONDS = _load_onboarding_reintro_after_seconds()
SESSION_IDLE_RESET_SECONDS = ONBOARDING_REINTRO_AFTER_SECONDS

_WHATSAPP_MENU_PENDING_SECONDS_ERROR = (
    "WHATSAPP_MENU_PENDING_SECONDS must be a positive integer."
)


def _load_whatsapp_menu_pending_seconds() -> int:
    raw_value = env("WHATSAPP_MENU_PENDING_SECONDS", default="600") or "600"
    try:
        timeout_seconds = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(_WHATSAPP_MENU_PENDING_SECONDS_ERROR) from exc
    if timeout_seconds <= 0:
        raise ImproperlyConfigured(_WHATSAPP_MENU_PENDING_SECONDS_ERROR)
    return timeout_seconds


WHATSAPP_MENU_PENDING_SECONDS = _load_whatsapp_menu_pending_seconds()

_QUALIFICATION_CACHE_TTL_SECONDS_ERROR = (
    "QUALIFICATION_CACHE_TTL_SECONDS must be a positive integer."
)


def _load_qualification_cache_ttl_seconds() -> int:
    raw_value = env("QUALIFICATION_CACHE_TTL_SECONDS", default="86400") or "86400"
    try:
        ttl_seconds = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(_QUALIFICATION_CACHE_TTL_SECONDS_ERROR) from exc
    if ttl_seconds <= 0:
        raise ImproperlyConfigured(_QUALIFICATION_CACHE_TTL_SECONDS_ERROR)
    return ttl_seconds


QUALIFICATION_CACHE_TTL_SECONDS = _load_qualification_cache_ttl_seconds()

_MAX_TTS_TEXT_LENGTH_ERROR = "MAX_TTS_TEXT_LENGTH must be a positive integer."


def _load_max_tts_text_length() -> int:
    raw_value = env("MAX_TTS_TEXT_LENGTH", default="800") or "800"
    try:
        max_length = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(_MAX_TTS_TEXT_LENGTH_ERROR) from exc
    if max_length <= 0:
        raise ImproperlyConfigured(_MAX_TTS_TEXT_LENGTH_ERROR)
    return max_length


_WHATSAPP_AUDIO_TTL_SECONDS_ERROR = "WHATSAPP_AUDIO_TTL_SECONDS must be a positive integer."


def _load_whatsapp_audio_ttl_seconds() -> int:
    raw_value = env("WHATSAPP_AUDIO_TTL_SECONDS", default="86400") or "86400"
    try:
        ttl_seconds = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(_WHATSAPP_AUDIO_TTL_SECONDS_ERROR) from exc
    if ttl_seconds <= 0:
        raise ImproperlyConfigured(_WHATSAPP_AUDIO_TTL_SECONDS_ERROR)
    return ttl_seconds


_SUPERTONIC_TTS_TIMEOUT_SECONDS_ERROR = (
    "SUPERTONIC_TTS_TIMEOUT_SECONDS must be a positive integer."
)


def _load_supertonic_tts_timeout_seconds() -> int:
    raw_value = env("SUPERTONIC_TTS_TIMEOUT_SECONDS", default="60") or "60"
    try:
        timeout_seconds = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(_SUPERTONIC_TTS_TIMEOUT_SECONDS_ERROR) from exc
    if timeout_seconds <= 0:
        raise ImproperlyConfigured(_SUPERTONIC_TTS_TIMEOUT_SECONDS_ERROR)
    return timeout_seconds


MAX_TTS_TEXT_LENGTH = _load_max_tts_text_length()
WHATSAPP_AUDIO_TTL_SECONDS = _load_whatsapp_audio_ttl_seconds()
SUPERTONIC_TTS_TIMEOUT_SECONDS = _load_supertonic_tts_timeout_seconds()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "format": "%(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
    },
    "loggers": {
        "apps.webhooks": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "apps.qualification": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
