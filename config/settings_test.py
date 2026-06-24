"""Test settings."""

from .settings import *  # noqa: F403

DEBUG = False
ALLOWED_HOSTS = ["testserver", "api.example.com", "localhost", "127.0.0.1"]

TWILIO_AUTH_TOKEN = "test-twilio-auth-token"
TWILIO_ACCOUNT_SID = "ACtesttwilioaccountsidthirtyfour"
DEEPGRAM_API_KEY = "test-deepgram-api-key"
N8N_WHATSAPP_WEBHOOK_URL = "https://n8n.example/webhook/whatsapp-inbound"
N8N_WEBHOOK_SECRET = "test-n8n-webhook-secret"
N8N_FORWARD_TIMEOUT_SECONDS = 5
N8N_QUALIFICATION_API_SECRET = "test-n8n-qualification-api-secret"
BOOKING_LINK = "https://booking.example.com/test-schedule"
PUBLIC_MEDIA_BASE_URL = "https://tunnel.example.com"
SUPERTONIC_BASE_URL = "http://127.0.0.1:7788"
