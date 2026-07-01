"""Verify Arabic Supertonic voice rendering for manual quality approval."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.qualification.supertonic_client import (
    SupertonicConfigurationError,
    SupertonicRequestError,
    SupertonicResponseError,
    synthesize_wav,
)
from apps.qualification.whatsapp_audio import convert_wav_to_ogg

ARABIC_SAMPLE_PHRASE = "مرحبًا، شكرًا لتواصلك معنا. كيف يمكننا مساعدتك؟"
VERIFICATION_SUBDIR = Path("arabic_supertonic_verification")


class Command(BaseCommand):
    help = (
        "Render an Arabic Supertonic sample for manual listening. "
        "Does not enable Arabic TTS in production."
    )

    def handle(self, *args: object, **options: object) -> None:
        voice = (settings.SUPERTONIC_ARABIC_VOICE or "").strip()
        if not voice:
            raise CommandError(
                "SUPERTONIC_ARABIC_VOICE is not configured. "
                "Set it in .env before running verification.",
            )

        output_dir = Path(settings.MEDIA_ROOT) / VERIFICATION_SUBDIR
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
        wav_path = output_dir / f"arabic_supertonic_{voice}_{timestamp}.wav"
        ogg_path = output_dir / f"arabic_supertonic_{voice}_{timestamp}.ogg"

        self.stdout.write(f"Configured Arabic voice ID: {voice}")
        self.stdout.write(f"Sample phrase: {ARABIC_SAMPLE_PHRASE}")

        try:
            wav_bytes = synthesize_wav(text=ARABIC_SAMPLE_PHRASE, voice=voice, lang="ar")
            wav_path.write_bytes(wav_bytes)
            convert_wav_to_ogg(wav_path=wav_path, ogg_path=ogg_path)
        except SupertonicConfigurationError as exc:
            raise CommandError(f"Supertonic configuration error: {exc}") from exc
        except (SupertonicRequestError, SupertonicResponseError) as exc:
            raise CommandError(f"Supertonic request failed: {exc}") from exc
        except Exception as exc:
            raise CommandError(f"Arabic verification render failed: {type(exc).__name__}") from exc

        wav_size = wav_path.stat().st_size
        ogg_size = ogg_path.stat().st_size if ogg_path.exists() else 0

        self.stdout.write("Request status: success")
        self.stdout.write(f"Generated WAV path: {wav_path}")
        self.stdout.write(f"Generated OGG path: {ogg_path}")
        self.stdout.write("Audio MIME type (WAV): audio/wav")
        self.stdout.write("Audio MIME type (OGG): audio/ogg")
        self.stdout.write(f"WAV size bytes: {wav_size}")
        self.stdout.write(f"OGG size bytes: {ogg_size}")
        self.stdout.write(
            "Manual listening required: review the generated audio and only then set "
            "SUPERTONIC_ARABIC_ENABLED=true in production.",
        )
