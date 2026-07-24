"""Report whether WhatsApp voice-note dependencies are configured."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.qualification.voice_note_config import get_voice_note_config_report


class Command(BaseCommand):
    help = "Check WAHA media download and Deepgram configuration for voice notes."

    def handle(self, *args: object, **options: object) -> None:
        report = get_voice_note_config_report()
        self.stdout.write(
            f"WAHA media download credentials: {report.waha_media_credentials}"
        )
        self.stdout.write(f"Deepgram API key: {report.deepgram_api_key}")
        self.stdout.write(f"Deepgram model: {report.deepgram_model}")
        self.stdout.write(f"Deepgram base URL: {report.deepgram_base_url}")
        readiness = "READY" if report.ready else "NOT READY"
        self.stdout.write(f"Voice-note configuration: {readiness}")

        if not report.ready:
            raise SystemExit(1)
