"""Public URL helpers for stable webhook and media endpoints."""

from __future__ import annotations

from django.conf import settings


def get_base_webhook_url() -> str:
    """Return the configured public base URL for n8n-facing HTTP callbacks."""
    return settings.BASE_WEBHOOK_URL.rstrip("/")


def get_public_media_base_url() -> str:
    """
    Return the public base URL used to build WhatsApp voice reply media links.

    Falls back to BASE_WEBHOOK_URL when PUBLIC_MEDIA_BASE_URL is not set.
    """
    media_base = settings.PUBLIC_MEDIA_BASE_URL.rstrip("/")
    if media_base:
        return media_base
    return get_base_webhook_url()
