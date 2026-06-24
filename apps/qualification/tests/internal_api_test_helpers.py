"""Shared helpers for internal qualification API endpoint tests."""

from __future__ import annotations

from apps.qualification.internal_auth import QUALIFICATION_SECRET_HEADER_NAME

API_SECRET = "test-n8n-qualification-api-secret"
INTERNAL_API_SECRET_META_KEY = "HTTP_" + QUALIFICATION_SECRET_HEADER_NAME.upper().replace("-", "_")


def internal_api_auth_headers(*, secret: str | None = API_SECRET) -> dict[str, str]:
    headers: dict[str, str] = {}
    if secret is not None:
        headers[INTERNAL_API_SECRET_META_KEY] = secret
    return headers
