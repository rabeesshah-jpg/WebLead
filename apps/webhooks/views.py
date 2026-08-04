"""WhatsApp inbound webhook views."""

from __future__ import annotations

import json

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
    """
    Receive incoming WhatsApp messages from Twilio.
    """

    is_valid, reason = validate_twilio_signature(request)

    if not is_valid:
        log_signature_validation_failed(request, reason=reason)
        return HttpResponse(status=403)

    params = twilio_post_params(request)

    try:
        forward_to_n8n(params)

    except N8nForwardError as exc:
        log_n8n_forward_failed(request, error=str(exc))
        return HttpResponse(status=502)

    return HttpResponse(status=200)


@csrf_exempt
@require_POST
def ultramsg_whatsapp_inbound(request: HttpRequest) -> HttpResponse:
    """
    Receive incoming WhatsApp messages from UltraMsg
    and convert them into Twilio-compatible payload.
    """

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponse(status=400)

    data = payload.get("data", {})

    from_value = data.get("from", "")
    to_value = data.get("to", "")
    body = data.get("body", "")

    media = data.get("media")

    if isinstance(media, dict):
        media_url = media.get("url")
        media_content_type = media.get("mimetype")
    else:
        media_url = media or ""
        media_content_type = None


    params = {
        "body": {
            "MessageSid": data.get("id", ""),

            "From": f"whatsapp:+{from_value.replace('@c.us','')}",

            "To": f"whatsapp:+{to_value.replace('@c.us','')}",

            "Body": body,

            "NumMedia": "1" if media_url else "0",

            "MediaUrl0": media_url,

            "MediaContentType0": media_content_type or "",
        }
    }


    print("========== ULTRAMSG ORIGINAL ==========")
    print(json.dumps(payload, indent=2))

    print("========== SENT TO N8N ==========")
    print(json.dumps(params, indent=2))


    try:
        forward_to_n8n(params)

    except N8nForwardError as exc:
        log_n8n_forward_failed(request, error=str(exc))
        return HttpResponse(status=502)

    return HttpResponse(status=200)