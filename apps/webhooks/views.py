"""WAHA WhatsApp inbound webhook views."""

from __future__ import annotations

import json
import logging

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.webhooks.n8n_forward import N8nForwardError, forward_to_n8n
from apps.whatsapp.config import get_waha_webhook_secret
from apps.whatsapp.webhook_handler import (
    WahaWebhookParseError,
    parse_waha_inbound_to_extract_payload,
)

logger = logging.getLogger("apps.webhooks")


def _extract_request_api_key(request: HttpRequest) -> str:
    header = request.headers.get("X-Api-Key") or request.META.get("HTTP_X_API_KEY") or ""
    if header:
        return header.strip()
    # Some reverse proxies lower-case custom headers inconsistently.
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _validate_waha_webhook_auth(request: HttpRequest) -> tuple[bool, str]:
    expected = get_waha_webhook_secret()
    if not expected:
        return False, "WAHA webhook secret is not configured"
    provided = _extract_request_api_key(request)
    if not provided or provided != expected:
        return False, "invalid_api_key"
    return True, ""


@csrf_exempt
@require_POST
def waha_whatsapp_inbound(request: HttpRequest) -> HttpResponse:
    is_valid, reason = _validate_waha_webhook_auth(request)
    if not is_valid:
        logger.warning(
            "waha_webhook_auth_failed reason=%s",
            reason,
        )
        return HttpResponse(status=403)

    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("waha_webhook_invalid_json")
        return HttpResponse(status=400)

    if not isinstance(body, dict):
        return HttpResponse(status=400)

    try:
        extract_payload = parse_waha_inbound_to_extract_payload(body)
    except WahaWebhookParseError as exc:
        logger.warning("waha_webhook_parse_failed error=%s", str(exc)[:200])
        return HttpResponse(status=400)

    if extract_payload is None:
        # Ignored events (fromMe, groups, non-message) still ack 200.
        return HttpResponse(status=200)

    try:
        forward_to_n8n(extract_payload, as_json=True)
    except N8nForwardError as exc:
        logger.error("waha_n8n_forward_failed error=%s", str(exc)[:300])
        return HttpResponse(status=502)

    return HttpResponse(status=200)
