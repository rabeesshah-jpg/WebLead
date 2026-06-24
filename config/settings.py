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

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {}

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

BOOKING_LINK = env("BOOKING_LINK", default="https://booking.example.com/schedule")

DEEPGRAM_API_KEY = env("DEEPGRAM_API_KEY", default="")
DEEPGRAM_MODEL = env("DEEPGRAM_MODEL", default="nova-2")
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
PUBLIC_MEDIA_BASE_URL = env("PUBLIC_MEDIA_BASE_URL", default="").rstrip("/")

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
