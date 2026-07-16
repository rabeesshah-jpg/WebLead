"""Twilio WhatsApp inbound webhook views."""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.webhooks.n8n_forward import N8nForwardError, forward_to_n8n
from apps.webhooks.twilio_validation import (
    log_n8n_forward_failed,
    log_signature_validation_failed,
    twilio_post_params,
    validate_twilio_signature,
)


@csrf_exempt
@require_POST
def twilio_whatsapp_inbound(request: HttpRequest) -> HttpResponse:
    is_valid, reason = validate_twilio_signature(request)
    if not is_valid:
        log_signature_validation_failed(request, reason=reason)
        return HttpResponse(status=403)

    params = twilio_post_params(request)
    try:
        forward_to_n8n(params)
    except N8nForwardError:
        log_n8n_forward_failed(request)
        return HttpResponse(status=502)

    return HttpResponse(status=200)
