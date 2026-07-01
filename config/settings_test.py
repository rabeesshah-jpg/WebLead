"""Test settings."""

from .settings import *  # noqa: F403

DEBUG = False
ALLOWED_HOSTS = ["testserver", "api.example.com", "localhost", "127.0.0.1"]

TWILIO_AUTH_TOKEN = "test-twilio-auth-token"
TWILIO_ACCOUNT_SID = "ACtesttwilioaccountsidthirtyfour"
DEEPGRAM_API_KEY = "test-deepgram-api-key"
DEEPGRAM_MODEL = "nova-2"
DEEPGRAM_LANGUAGE = "en"
DEEPGRAM_ENGLISH_MODEL = ""
DEEPGRAM_ENGLISH_LANGUAGE = ""
DEEPGRAM_ARABIC_MODEL = "nova-3"
DEEPGRAM_ARABIC_LANGUAGE = "ar"
N8N_WHATSAPP_WEBHOOK_URL = "https://n8n.example/webhook/whatsapp-inbound"
N8N_WEBHOOK_SECRET = "test-n8n-webhook-secret"
N8N_FORWARD_TIMEOUT_SECONDS = 5
N8N_QUALIFICATION_API_SECRET = "test-n8n-qualification-api-secret"
BOOKING_LINK = "https://booking.example.com/test-schedule"
BASE_WEBHOOK_URL = "https://tunnel.example.com"
PUBLIC_MEDIA_BASE_URL = "https://tunnel.example.com"
QUALIFICATION_REDIS_URL = ""
SUPERTONIC_BASE_URL = "http://127.0.0.1:7788"
SUPERTONIC_ENGLISH_VOICE = "F1"
SUPERTONIC_ARABIC_ENABLED = False
SUPERTONIC_ARABIC_VOICE = ""
TWILIO_LANGUAGE_PICKER_CONTENT_SID = ""

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
