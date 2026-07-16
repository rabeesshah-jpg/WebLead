"""Shared internal API authentication for qualification endpoints."""

from __future__ import annotations

import secrets

from django.conf import settings
from django.http import HttpRequest

QUALIFICATION_SECRET_HEADER_NAME = "X-Internal-Webhook-Secret"


def is_internal_qualification_authorized(request: HttpRequest) -> bool:
    """Return whether the request includes the configured internal secret."""
    configured_secret = settings.N8N_QUALIFICATION_API_SECRET
    if not configured_secret:
        return False

    provided_secret = request.headers.get(QUALIFICATION_SECRET_HEADER_NAME, "")
    if not provided_secret:
        return False

    return secrets.compare_digest(provided_secret, configured_secret)
