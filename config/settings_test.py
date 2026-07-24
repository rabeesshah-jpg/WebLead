"""Test settings."""

from .settings import *  # noqa: F403

DEBUG = False
ALLOWED_HOSTS = ["testserver", "api.example.com", "localhost", "127.0.0.1"]

WAHA_BASE_URL = "https://waha.example.com"
WAHA_SESSION = "default"
WAHA_API_KEY = "test-waha-api-key"
WAHA_WEBHOOK_SECRET = "test-waha-webhook-secret"
WAHA_MEDIA_DOWNLOAD_TIMEOUT_SECONDS = 30
WAHA_MEDIA_MAX_BYTES = 10485760
DEEPGRAM_API_KEY = "test-deepgram-api-key"
DEEPGRAM_MODEL = "nova-2"
DEEPGRAM_LANGUAGE = "en"
DEEPGRAM_ENGLISH_MODEL = ""
DEEPGRAM_ENGLISH_LANGUAGE = ""
DEEPGRAM_ARABIC_MODEL = "nova-3"
DEEPGRAM_ARABIC_LANGUAGE = "ar"
N8N_WEBHOOK_URL = "https://n8n.example/webhook/whatsapp-inbound"
N8N_WEBHOOK_SECRET = "test-n8n-webhook-secret"
N8N_FORWARD_TIMEOUT_SECONDS = 5
N8N_QUALIFICATION_API_SECRET = "test-n8n-qualification-api-secret"
WEBLEAD_VOICE_EVENT_SECRET = "test-weblead-voice-event-secret"
BOOKING_LINK = "https://booking.example.com/test-schedule"
BASE_WEBHOOK_URL = "https://tunnel.example.com"
PUBLIC_MEDIA_BASE_URL = "https://tunnel.example.com"
QUALIFICATION_REDIS_URL = ""
# Keep Supertonic timeouts short so accidental unmocked HTTP fails fast in tests.
SUPERTONIC_TTS_TIMEOUT_SECONDS = 2
SUPERTONIC_BASE_URL = "http://127.0.0.1:7788"
SUPERTONIC_ENGLISH_VOICE = "F1"
SUPERTONIC_ARABIC_ENABLED = False
SUPERTONIC_ARABIC_VOICE = ""
LEAD_QUALIFICATION_ENABLED = True
WHATSAPP_MENU_INACTIVITY_SECONDS = 600
WHATSAPP_MENU_PENDING_SECONDS = 600
SESSION_IDLE_RESET_SECONDS = 300
EXISTING_CUSTOMER_FOLLOWUP_DELAY_SECONDS = 10
N8N_OPTION_TEMPLATE_WEBHOOK_URL = "https://n8n.example/webhook/option-template-delivery"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
