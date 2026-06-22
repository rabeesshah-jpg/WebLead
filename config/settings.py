"""WebLead Django settings."""

from pathlib import Path

import environ

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
N8N_WHATSAPP_WEBHOOK_URL = env("N8N_WHATSAPP_WEBHOOK_URL", default="")
N8N_WEBHOOK_SECRET = env("N8N_WEBHOOK_SECRET", default="")
N8N_FORWARD_TIMEOUT_SECONDS = env.int("N8N_FORWARD_TIMEOUT_SECONDS", default=5)

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
    },
}
