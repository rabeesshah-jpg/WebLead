"""Test settings."""

from .settings import *  # noqa: F403

DEBUG = False
ALLOWED_HOSTS = ["testserver", "api.example.com", "localhost", "127.0.0.1"]

TWILIO_AUTH_TOKEN = "test-twilio-auth-token"
N8N_WHATSAPP_WEBHOOK_URL = "https://n8n.example/webhook/whatsapp-inbound"
N8N_WEBHOOK_SECRET = "test-n8n-webhook-secret"
N8N_FORWARD_TIMEOUT_SECONDS = 5
