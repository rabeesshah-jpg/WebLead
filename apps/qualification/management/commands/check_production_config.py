"""Report production-critical qualification configuration."""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Check stable public URLs and persistent qualification storage configuration."

    def handle(self, *args: object, **options: object) -> None:
        issues: list[str] = []
        warnings: list[str] = []

        base_webhook_url = getattr(settings, "BASE_WEBHOOK_URL", "")
        public_media_base_url = getattr(settings, "PUBLIC_MEDIA_BASE_URL", "")
        effective_media_base = public_media_base_url or base_webhook_url

        self.stdout.write(f"BASE_WEBHOOK_URL: {base_webhook_url or 'NOT SET'}")
        self.stdout.write(f"PUBLIC_MEDIA_BASE_URL: {public_media_base_url or 'NOT SET'}")
        self.stdout.write(f"Effective media base URL: {effective_media_base or 'NOT SET'}")
        self.stdout.write(
            f"QUALIFICATION_REDIS_URL: {'SET' if settings.QUALIFICATION_REDIS_URL else 'NOT SET'}"
        )

        if not base_webhook_url:
            issues.append("BASE_WEBHOOK_URL is required for stable n8n callback URLs.")
        if not effective_media_base:
            issues.append(
                "PUBLIC_MEDIA_BASE_URL or BASE_WEBHOOK_URL is required for voice reply media URLs.",
            )
        if not settings.QUALIFICATION_REDIS_URL:
            warnings.append(
                "QUALIFICATION_REDIS_URL is unset; using process-local in-memory "
                "persistence (OK for single-worker; set Redis for multi-worker).",
            )

        for warning in warnings:
            self.stdout.write(self.style.WARNING(warning))

        if issues:
            for issue in issues:
                self.stderr.write(self.style.ERROR(issue))
            raise SystemExit(1)

        self.stdout.write(self.style.SUCCESS("Production qualification configuration: READY"))
