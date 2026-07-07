"""DRF permissions for qualification internal APIs."""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from apps.qualification.internal_auth import is_internal_qualification_authorized
from apps.qualification.voice_event_auth import is_voice_event_authorized


class InternalWebhookSecretPermission(BasePermission):
    """
    Requires the existing X-Internal-Webhook-Secret validation.

    This permission will be used later by internal JSON API endpoints.
    """

    message = "Forbidden."

    def has_permission(self, request, view) -> bool:
        return is_internal_qualification_authorized(request)


class VoiceEventSecretPermission(BasePermission):
    """Requires X-WebLead-Secret validation for LiveKit voice-call completion."""

    message = "Forbidden."

    def has_permission(self, request, view) -> bool:
        return is_voice_event_authorized(request)
