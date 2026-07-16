"""Twilio webhook signature validation helpers."""

from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone
from twilio.request_validator import RequestValidator

logger = logging.getLogger("apps.webhooks.twilio")

TWILIO_SIGNATURE_HEADER = "HTTP_X_TWILIO_SIGNATURE"
MESSAGE_SID_FIELD = "MessageSid"
MAX_MESSAGE_SID_PREFIX_LEN = 8


def twilio_post_params(request: HttpRequest) -> dict[str, str]:
    """Return all form-urlencoded POST parameters for Twilio validation."""
    params: dict[str, str] = {}
    for key in request.POST:
        values = request.POST.getlist(key)
        params[key] = values[0] if len(values) == 1 else ",".join(values)
    return params


def twilio_validation_url(request: HttpRequest) -> str:
    """
    Build the externally visible URL Twilio signed.

    Uses Django's absolute URI builder, which respects reverse-proxy headers
    configured via SECURE_PROXY_SSL_HEADER and USE_X_FORWARDED_HOST.
    """
    return request.build_absolute_uri()


def validate_twilio_signature(
    request: HttpRequest,
    *,
    auth_token: str | None = None,
) -> tuple[bool, str]:
    """
    Validate X-Twilio-Signature using Twilio's official RequestValidator.

    Returns (is_valid, reason) where reason is empty when valid, otherwise
    'missing_signature' or 'signature_mismatch'.
    """
    signature = request.META.get(TWILIO_SIGNATURE_HEADER, "").strip()
    if not signature:
        return False, "missing_signature"

    token = auth_token if auth_token is not None else settings.TWILIO_AUTH_TOKEN
    if not token:
        return False, "signature_mismatch"

    validator = RequestValidator(token)
    url = twilio_validation_url(request)
    params = twilio_post_params(request)

    if validator.validate(url, params, signature):
        return True, ""

    return False, "signature_mismatch"


def message_sid_prefix(params: dict[str, str]) -> str | None:
    sid = params.get(MESSAGE_SID_FIELD, "").strip()
    if not sid:
        return None
    return sid[:MAX_MESSAGE_SID_PREFIX_LEN]


def log_signature_validation_failed(
    request: HttpRequest,
    *,
    reason: str,
    params: dict[str, str] | None = None,
) -> None:
    post_params = params if params is not None else twilio_post_params(request)
    payload = {
        "event": "twilio_signature_validation_failed",
        "timestamp": timezone.now().isoformat(),
        "request_path": request.path,
        "message_sid_prefix": message_sid_prefix(post_params),
        "reason": reason,
    }
    logger.warning(json.dumps(payload, separators=(",", ":")))


def log_n8n_forward_failed(request: HttpRequest) -> None:
    params = twilio_post_params(request)
    payload = {
        "event": "n8n_forward_failed",
        "timestamp": timezone.now().isoformat(),
        "request_path": request.path,
        "message_sid_prefix": message_sid_prefix(params),
    }
    logger.error(json.dumps(payload, separators=(",", ":")))
