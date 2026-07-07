"""Shared authentication for LiveKit voice-call completion events."""

from __future__ import annotations

import secrets

from django.conf import settings
from django.http import HttpRequest

VOICE_EVENT_SECRET_HEADER_NAME = "X-WebLead-Secret"


def is_voice_event_authorized(request: HttpRequest) -> bool:
    """Return whether the request includes the configured voice-event secret."""
    configured_secret = settings.WEBLEAD_VOICE_EVENT_SECRET
    if not configured_secret:
        return False

    provided_secret = request.headers.get(VOICE_EVENT_SECRET_HEADER_NAME, "")
    if not provided_secret:
        return False

    return secrets.compare_digest(provided_secret, configured_secret)
