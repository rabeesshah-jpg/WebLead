"""Startup validation for production-critical configuration."""

from __future__ import annotations

import logging
import re

from django.conf import settings

logger = logging.getLogger("apps.qualification")

_EPHEMERAL_TUNNEL_PATTERN = re.compile(r"trycloudflare\.com|ngrok-free\.app|ngrok\.io", re.IGNORECASE)


def log_voice_agent_config() -> None:
    """Emit safe voice-agent configuration values without secrets."""
    logger.info(
        json_event(
            "voice_agent_config",
            step="voice_agent_config",
            deepgram_model=settings.DEEPGRAM_MODEL,
            deepgram_timeout_seconds=settings.DEEPGRAM_TIMEOUT_SECONDS,
            deepgram_api_key="configured" if settings.DEEPGRAM_API_KEY else "missing",
            twilio_media_download_timeout_seconds=settings.TWILIO_MEDIA_DOWNLOAD_TIMEOUT_SECONDS,
            twilio_media_credentials=(
                "configured"
                if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN
                else "missing"
            ),
            openrouter_model=settings.OPENROUTER_MODEL or "missing",
            openrouter_timeout_seconds=settings.OPENROUTER_TIMEOUT_SECONDS,
            openrouter_api_key="configured" if settings.OPENROUTER_API_KEY else "missing",
        ),
    )


def validate_qualification_startup_config() -> None:
    """Log warnings for missing or risky production configuration."""
    log_voice_agent_config()

    if settings.DEBUG:
        return

    if not getattr(settings, "QUALIFICATION_REDIS_URL", ""):
        logger.warning(
            json_event(
                "qualification_startup_inmemory_persistence",
                message=(
                    "QUALIFICATION_REDIS_URL is not configured; conversation state and "
                    "MessageSid idempotency are process-local only."
                ),
            ),
        )

    base_webhook_url = getattr(settings, "BASE_WEBHOOK_URL", "")
    public_media_base_url = getattr(settings, "PUBLIC_MEDIA_BASE_URL", "")
    effective_media_base = public_media_base_url or base_webhook_url

    if not base_webhook_url:
        logger.warning(
            json_event(
                "qualification_startup_missing_base_webhook_url",
                message="BASE_WEBHOOK_URL is not configured.",
            ),
        )

    if not effective_media_base:
        logger.warning(
            json_event(
                "qualification_startup_missing_public_media_base_url",
                message=(
                    "Neither PUBLIC_MEDIA_BASE_URL nor BASE_WEBHOOK_URL is configured; "
                    "render-audio media URLs cannot be generated."
                ),
            ),
        )

    for label, url in (
        ("BASE_WEBHOOK_URL", base_webhook_url),
        ("PUBLIC_MEDIA_BASE_URL", public_media_base_url),
    ):
        if url and _EPHEMERAL_TUNNEL_PATTERN.search(url):
            logger.warning(
                json_event(
                    "qualification_startup_ephemeral_public_url",
                    setting=label,
                    message="Configured public URL appears to use an ephemeral tunnel domain.",
                ),
            )


def json_event(event: str, **context: object) -> str:
    import json

    payload = {"event": event, **context}
    return json.dumps(payload, separators=(",", ":"))
