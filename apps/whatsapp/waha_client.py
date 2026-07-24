"""Thin HTTP client for the WAHA REST API."""

from __future__ import annotations

import json
import logging
import socket
import urllib.error
import urllib.request
from typing import Any

from apps.whatsapp.config import (
    WahaConfigurationError,
    get_waha_api_key,
    get_waha_base_url,
    get_waha_session,
    phone_to_chat_id,
    validate_waha_send_configuration,
)

logger = logging.getLogger("apps.whatsapp")


class WahaApiError(Exception):
    """Raised when a WAHA API call fails."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Api-Key": get_waha_api_key(),
    }


def _post(path: str, body: dict[str, Any], *, timeout_seconds: float = 30.0) -> dict[str, Any]:
    validate_waha_send_configuration()
    url = f"{get_waha_base_url()}{path}"
    encoded = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=encoded,
        method="POST",
        headers=_headers(),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read() or b"{}"
            if not raw:
                return {}
            parsed = json.loads(raw.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else {"data": parsed}
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = (exc.read(500) or b"").decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            detail = ""
        raise WahaApiError(
            f"WAHA {path} failed HTTP {exc.code}: {detail[:200]}",
            status_code=exc.code,
        ) from exc
    except urllib.error.URLError as exc:
        raise WahaApiError(f"WAHA {path} request failed: {exc.reason!r}") from exc
    except json.JSONDecodeError as exc:
        raise WahaApiError(f"WAHA {path} returned invalid JSON") from exc


def _message_id(response: dict[str, Any]) -> str:
    for key in ("id", "messageId", "key"):
        value = response.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = value.get("id") or value.get("_serialized")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return ""


def send_text(*, phone_number: str, text: str, session: str | None = None) -> str:
    """POST /api/sendText. Returns WAHA message id when present."""
    body = {
        "session": session or get_waha_session(),
        "chatId": phone_to_chat_id(phone_number),
        "text": text,
    }
    response = _post("/api/sendText", body)
    return _message_id(response)


def send_buttons(
    *,
    phone_number: str,
    body: str,
    buttons: list[dict[str, Any]],
    header: str | None = None,
    footer: str | None = None,
    session: str | None = None,
) -> str:
    """POST /api/sendButtons."""
    payload: dict[str, Any] = {
        "session": session or get_waha_session(),
        "chatId": phone_to_chat_id(phone_number),
        "body": body,
        "buttons": buttons,
    }
    if header:
        payload["header"] = header
    if footer:
        payload["footer"] = footer
    response = _post("/api/sendButtons", payload)
    return _message_id(response)


def send_list(
    *,
    phone_number: str,
    title: str,
    description: str,
    button_label: str,
    sections: list[dict[str, Any]],
    footer: str | None = None,
    session: str | None = None,
) -> str:
    """POST /api/sendList."""
    message: dict[str, Any] = {
        "title": title,
        "description": description,
        "button": button_label,
        "sections": sections,
    }
    if footer:
        message["footer"] = footer
    payload = {
        "session": session or get_waha_session(),
        "chatId": phone_to_chat_id(phone_number),
        "message": message,
    }
    response = _post("/api/sendList", payload)
    return _message_id(response)


def download_media_bytes(
    media_url: str,
    *,
    timeout_seconds: float | None = None,
    max_bytes: int | None = None,
) -> tuple[bytes, str]:
    """
    Download a WAHA media file with X-Api-Key auth.

    Returns ``(bytes, content_type)``.
    """
    from django.conf import settings

    if not get_waha_api_key():
        raise WahaConfigurationError("WAHA_API_KEY is not configured")

    timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else float(getattr(settings, "WAHA_MEDIA_DOWNLOAD_TIMEOUT_SECONDS", 30) or 30)
    )
    limit = (
        max_bytes
        if max_bytes is not None
        else int(getattr(settings, "WAHA_MEDIA_MAX_BYTES", 10485760) or 10485760)
    )

    request = urllib.request.Request(media_url, method="GET")
    request.add_header("X-Api-Key", get_waha_api_key())
    request.add_header("Accept", "*/*")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise WahaApiError("WAHA media download exceeded size limit")
                chunks.append(chunk)
            headers = getattr(response, "headers", None)
            content_type = "application/octet-stream"
            if headers is not None:
                raw_ct = headers.get("Content-Type") or headers.get("Content-type")
                if raw_ct:
                    content_type = raw_ct.split(";", 1)[0].strip().lower() or content_type
            return b"".join(chunks), content_type
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise WahaApiError(
                "WAHA media download unauthorized",
                status_code=exc.code,
            ) from exc
        raise WahaApiError(
            "WAHA media download failed",
            status_code=exc.code,
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise WahaApiError("WAHA media download timed out") from exc
        raise WahaApiError(f"WAHA media download failed: {reason!r}") from exc
