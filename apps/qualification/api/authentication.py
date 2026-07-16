"""DRF authentication for qualification internal APIs."""

from __future__ import annotations

from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request


class QualificationInternalAuthentication(BaseAuthentication):
    """
    Explicit anonymous authentication for internal JSON endpoints.

    These endpoints do not use ``django.contrib.auth``; authorization is handled
    by ``InternalWebhookSecretPermission`` via ``X-Internal-Webhook-Secret``.
    """

    def authenticate(self, request: Request) -> tuple[None, None]:
        return (None, None)
