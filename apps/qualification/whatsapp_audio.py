"""WhatsApp voice reply storage, conversion, and cleanup."""

from __future__ import annotations

import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.utils import timezone as django_timezone

from apps.qualification.supertonic_client import (
    SupertonicConfigurationError,
    SupertonicRequestError,
    SupertonicResponseError,
    synthesize_wav,
)

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
UUID_AUDIO_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
DEFAULT_VOICE = "F1"
DEFAULT_LANG = "en"


class InvalidRenderAudioRequestError(ValueError):
    """Raised when render-audio request input is invalid."""


class FfmpegConversionError(Exception):
    """Raised when ffmpeg fails to convert WAV to OGG."""


class RenderAudioServiceUnavailableError(Exception):
    """Raised when render-audio dependencies are unavailable."""


class RenderAudioProcessingError(Exception):
    """Raised when render-audio processing fails."""


def sanitize_request_id(raw_request_id: object) -> str | None:
    """Validate and sanitize an optional request_id for logging/echo only."""
    if raw_request_id is None:
        return None
    if not isinstance(raw_request_id, str):
        raise InvalidRenderAudioRequestError
    sanitized = raw_request_id.strip()
    if not sanitized or not REQUEST_ID_PATTERN.fullmatch(sanitized):
        raise InvalidRenderAudioRequestError
    return sanitized


def validate_text_length(text: str) -> None:
    if not text.strip():
        raise InvalidRenderAudioRequestError
    if len(text) > settings.MAX_TTS_TEXT_LENGTH:
        raise InvalidRenderAudioRequestError


def whatsapp_voice_replies_root() -> Path:
    return Path(settings.MEDIA_ROOT) / "whatsapp_voice_replies"


def _dated_output_dir(now: datetime | None = None) -> Path:
    current = now or django_timezone.now()
    output_dir = (
        whatsapp_voice_replies_root()
        / f"{current:%Y}"
        / f"{current:%m}"
        / f"{current:%d}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def is_valid_audio_id(audio_id: str) -> bool:
    return bool(UUID_AUDIO_ID_PATTERN.fullmatch(audio_id))


def find_audio_file(audio_id: str) -> Path | None:
    if not is_valid_audio_id(audio_id):
        return None

    matches = list(whatsapp_voice_replies_root().glob(f"**/{audio_id}.ogg"))
    if not matches:
        return None
    return matches[0]


def _file_is_expired(path: Path, *, now: datetime | None = None) -> bool:
    current = now or django_timezone.now()
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    age_seconds = (current - modified_at).total_seconds()
    return age_seconds > settings.WHATSAPP_AUDIO_TTL_SECONDS


def cleanup_expired_audio_files(*, now: datetime | None = None) -> int:
    """Remove expired WhatsApp voice reply files. Returns files removed."""
    root = whatsapp_voice_replies_root()
    if not root.exists():
        return 0

    removed = 0
    for path in root.glob("**/*.ogg"):
        if not path.is_file():
            continue
        if _file_is_expired(path, now=now):
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def convert_wav_to_ogg(*, wav_path: Path, ogg_path: Path) -> None:
    """Convert WAV to WhatsApp-compatible OGG Opus using ffmpeg."""
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(wav_path),
            "-ar",
            "48000",
            "-ac",
            "1",
            "-c:a",
            "libopus",
            "-b:a",
            "32k",
            "-vbr",
            "on",
            "-application",
            "voip",
            str(ogg_path),
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not ogg_path.exists() or ogg_path.stat().st_size == 0:
        raise FfmpegConversionError("ffmpeg conversion failed")


def build_public_media_url(audio_id: str) -> str:
    base_url = settings.PUBLIC_MEDIA_BASE_URL.rstrip("/")
    if not base_url:
        raise RenderAudioServiceUnavailableError("Public media base URL is not configured")
    return f"{base_url}/media/whatsapp_voice_replies/{audio_id}/"


def render_whatsapp_voice_reply(
    *,
    text: str,
    voice: str = DEFAULT_VOICE,
    lang: str = DEFAULT_LANG,
) -> tuple[str, Path]:
    """Render text to OGG, store it, and return (audio_id, stored_path)."""
    cleanup_expired_audio_files()
    validate_text_length(text)

    wav_bytes = synthesize_wav(text=text, voice=voice, lang=lang)
    audio_id = str(uuid.uuid4())
    output_dir = _dated_output_dir()
    final_ogg_path = output_dir / f"{audio_id}.ogg"

    with tempfile.TemporaryDirectory() as temp_dir:
        wav_path = Path(temp_dir) / "input.wav"
        temp_ogg_path = Path(temp_dir) / "output.ogg"
        wav_path.write_bytes(wav_bytes)
        convert_wav_to_ogg(wav_path=wav_path, ogg_path=temp_ogg_path)
        temp_ogg_path.replace(final_ogg_path)

    return audio_id, final_ogg_path


def render_whatsapp_voice_reply_safe(
    *,
    text: str,
    voice: str = DEFAULT_VOICE,
    lang: str = DEFAULT_LANG,
) -> str:
    """Render text and return the public media URL for the stored OGG file."""
    try:
        audio_id, _stored_path = render_whatsapp_voice_reply(text=text, voice=voice, lang=lang)
    except SupertonicConfigurationError as exc:
        raise RenderAudioServiceUnavailableError from exc
    except (SupertonicRequestError, SupertonicResponseError) as exc:
        raise RenderAudioServiceUnavailableError from exc
    except FfmpegConversionError as exc:
        raise RenderAudioProcessingError from exc

    return build_public_media_url(audio_id)
