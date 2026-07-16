"""Forward validated Twilio payloads to n8n."""

from __future__ import annotations

import logging
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlparse

from django.conf import settings

logger = logging.getLogger("apps.webhooks")


class N8nForwardError(Exception):
    """Raised when forwarding to n8n fails."""


def _safe_webhook_target(url: str) -> str:
    """Return hostname + path only (no query/secrets) for logs."""
    parsed = urlparse(url)
    host = parsed.netloc or ""
    path = parsed.path or "/"
    return f"{host}{path}"


def forward_to_n8n(
    params: dict[str, str],
    *,
    webhook_url: str | None = None,
    webhook_secret: str | None = None,
    timeout_seconds: int | None = None,
) -> None:
    """POST original form fields to the n8n production webhook."""
    url = (webhook_url if webhook_url is not None else settings.N8N_WEBHOOK_URL) or ""
    url = url.strip()
    secret = webhook_secret if webhook_secret is not None else settings.N8N_WEBHOOK_SECRET
    timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else settings.N8N_FORWARD_TIMEOUT_SECONDS
    )

    # Temporary safe diagnostics for Vercel env verification (no secrets).
    logger.info(
        "n8n_forward_config webhook_configured=%s webhook_target=%s timeout_seconds=%s "
        "secret_configured=%s",
        bool(url),
        _safe_webhook_target(url) if url else "",
        timeout,
        bool(secret),
    )

    if not url:
        raise N8nForwardError(
            "n8n webhook URL is not configured "
            "(set N8N_WEBHOOK_URL on Vercel / .env)",
        )

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
                body_preview = ""
                try:
                    body_preview = (response.read(500) or b"").decode("utf-8", errors="replace")
                except Exception:  # noqa: BLE001
                    body_preview = ""
                raise N8nForwardError(
                    f"n8n returned HTTP {response.status} "
                    f"target={_safe_webhook_target(url)} "
                    f"body={body_preview[:200]!r}",
                )
    except urllib.error.HTTPError as exc:
        body_preview = ""
        try:
            body_preview = (exc.read(500) or b"").decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            body_preview = ""
        raise N8nForwardError(
            f"n8n returned HTTP {exc.code} "
            f"target={_safe_webhook_target(url)} "
            f"body={body_preview[:200]!r}",
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise N8nForwardError(
            f"n8n request failed target={_safe_webhook_target(url)} reason={reason!r}",
        ) from exc
