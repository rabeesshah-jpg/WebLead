"""Request n8n to send a Twilio option_template Content message."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from django.conf import settings

from apps.qualification.api.logging import log_qualification_event

logger = logging.getLogger("apps.qualification")


class N8nOptionTemplateDeliveryError(Exception):
    """Raised when n8n option_template delivery cannot be requested."""


def _resolve_webhook_url() -> str:
    dedicated = (getattr(settings, "N8N_OPTION_TEMPLATE_WEBHOOK_URL", "") or "").strip()
    if dedicated:
        return dedicated
    # Reuse the production WhatsApp webhook when a dedicated outbound URL is unset;
    # n8n must branch on event=option_template_delivery / option_template.
    inbound = (getattr(settings, "N8N_WHATSAPP_WEBHOOK_URL", "") or "").strip()
    if inbound:
        return inbound
    raise N8nOptionTemplateDeliveryError(
        "N8N_OPTION_TEMPLATE_WEBHOOK_URL (or N8N_WHATSAPP_WEBHOOK_URL) is not configured",
    )


def request_n8n_option_template_delivery(
    contract: dict[str, Any],
    *,
    webhook_url: str | None = None,
    webhook_secret: str | None = None,
    timeout_seconds: float | None = None,
) -> None:
    """
    POST the shared option_template delivery contract to n8n as JSON.

    n8n must use the same Switch/IF on ``option_template`` that handles extract
    responses for new customers (ContentSid / ContentVariables live in n8n only).
    """
    url = (webhook_url or "").strip() or _resolve_webhook_url()
    secret = (
        webhook_secret
        if webhook_secret is not None
        else getattr(settings, "N8N_WEBHOOK_SECRET", "") or ""
    )
    timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else float(getattr(settings, "N8N_FORWARD_TIMEOUT_SECONDS", 5) or 5)
    )

    option_template = contract.get("option_template")
    whatsapp_number = str(contract.get("whatsapp_number") or "")
    body = json.dumps(contract, separators=(",", ":")).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if secret:
        headers["X-Internal-Webhook-Secret"] = secret

    request = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status >= 400:
                raise N8nOptionTemplateDeliveryError(
                    f"n8n returned HTTP {response.status}",
                )
            log_qualification_event(
                "n8n_option_template_delivery_requested",
                whatsapp_number_prefix=whatsapp_number[:6] if whatsapp_number else None,
                option_template=option_template,
                next_field=contract.get("next_field"),
                conversation_state=contract.get("conversation_state"),
                http_status=response.status,
                source=contract.get("source"),
                delivery_idempotency_key=contract.get("delivery_idempotency_key"),
                template_send_result="requested",
            )
    except urllib.error.HTTPError as exc:
        log_qualification_event(
            "n8n_option_template_delivery_failed",
            whatsapp_number_prefix=whatsapp_number[:6] if whatsapp_number else None,
            option_template=option_template,
            error_type="HTTPError",
            error_message=str(exc)[:300],
            http_status=exc.code,
            source=contract.get("source"),
            delivery_idempotency_key=contract.get("delivery_idempotency_key"),
            template_send_result="failed",
        )
        raise N8nOptionTemplateDeliveryError(
            f"n8n returned HTTP {exc.code}",
        ) from exc
    except urllib.error.URLError as exc:
        log_qualification_event(
            "n8n_option_template_delivery_failed",
            whatsapp_number_prefix=whatsapp_number[:6] if whatsapp_number else None,
            option_template=option_template,
            error_type=type(exc).__name__,
            error_message=str(exc)[:300],
            source=contract.get("source"),
            delivery_idempotency_key=contract.get("delivery_idempotency_key"),
            template_send_result="failed",
        )
        raise N8nOptionTemplateDeliveryError("n8n option_template request failed") from exc
    except N8nOptionTemplateDeliveryError:
        raise
    except Exception as exc:
        log_qualification_event(
            "n8n_option_template_delivery_failed",
            whatsapp_number_prefix=whatsapp_number[:6] if whatsapp_number else None,
            option_template=option_template,
            error_type=type(exc).__name__,
            error_message=str(exc)[:300],
            source=contract.get("source"),
            delivery_idempotency_key=contract.get("delivery_idempotency_key"),
            template_send_result="failed",
        )
        logger.exception("n8n_option_template_delivery_failed")
        raise N8nOptionTemplateDeliveryError(
            "n8n option_template request failed",
        ) from exc
