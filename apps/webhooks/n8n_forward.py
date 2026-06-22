"""Forward validated Twilio payloads to n8n."""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from django.conf import settings


class N8nForwardError(Exception):
    """Raised when forwarding to n8n fails."""


def forward_to_n8n(
    params: dict[str, str],
    *,
    webhook_url: str | None = None,
    webhook_secret: str | None = None,
    timeout_seconds: int | None = None,
) -> None:
    """POST original form fields to the n8n production webhook."""
    url = webhook_url if webhook_url is not None else settings.N8N_WHATSAPP_WEBHOOK_URL
    secret = webhook_secret if webhook_secret is not None else settings.N8N_WEBHOOK_SECRET
    timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else settings.N8N_FORWARD_TIMEOUT_SECONDS
    )

    if not url:
        raise N8nForwardError("n8n webhook URL is not configured")

    encoded_body = urllib.parse.urlencode(params).encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if secret:
        headers["X-Internal-Webhook-Secret"] = secret

    request = urllib.request.Request(url, data=encoded_body, method="POST", headers=headers)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status >= 400:
                raise N8nForwardError(f"n8n returned HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        raise N8nForwardError(f"n8n returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise N8nForwardError("n8n request failed") from exc
