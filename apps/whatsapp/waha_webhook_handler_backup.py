"""Parse WAHA webhook events into the internal extract payload shape."""

from __future__ import annotations

from typing import Any

from apps.whatsapp.waha_config_backup import chat_id_to_e164

_AUDIO_MIME_PREFIXES = ("audio/", "application/ogg")


class WahaWebhookParseError(Exception):
    """Raised when a WAHA webhook body cannot be mapped."""


def _dig(data: Any, *keys: str) -> Any:
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _extract_button_payload(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    """
    Return ``(button_payload, button_text)`` from interactive replies.

    Supports common WAHA / engine shapes for list and button responses.
    """
    # Top-level convenience fields (some engines).
    for key in ("selectedButtonId", "selectedButtonID", "buttonOrUrlId"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            text = payload.get("body") if isinstance(payload.get("body"), str) else None
            return value.strip(), (text.strip() if text else None)

    list_reply = payload.get("listResponse") or payload.get("list_response")
    if isinstance(list_reply, dict):
        single = list_reply.get("singleSelectReply") or list_reply.get("single_select_reply") or {}
        if isinstance(single, dict):
            row_id = single.get("selectedRowId") or single.get("selectedRowID")
            title = list_reply.get("title") or payload.get("body")
            if isinstance(row_id, str) and row_id.strip():
                return row_id.strip(), (str(title).strip() if title else None)

    button_reply = payload.get("buttonResponse") or payload.get("buttonsResponse")
    if isinstance(button_reply, dict):
        btn_id = (
            button_reply.get("selectedButtonId")
            or button_reply.get("selectedButtonID")
            or button_reply.get("selectedId")
        )
        title = button_reply.get("selectedDisplayText") or payload.get("body")
        if isinstance(btn_id, str) and btn_id.strip():
            return btn_id.strip(), (str(title).strip() if title else None)

    # Engine-specific nested `_data`.
    data = payload.get("_data")
    if isinstance(data, dict):
        message = data.get("Message") or data.get("message") or {}
        if isinstance(message, dict):
            list_msg = message.get("listResponseMessage") or {}
            if isinstance(list_msg, dict):
                single = list_msg.get("singleSelectReply") or {}
                if isinstance(single, dict):
                    row_id = single.get("selectedRowID") or single.get("selectedRowId")
                    title = list_msg.get("title") or payload.get("body")
                    if isinstance(row_id, str) and row_id.strip():
                        return row_id.strip(), (str(title).strip() if title else None)
            buttons_msg = (
                message.get("buttonsResponseMessage")
                or message.get("templateButtonReplyMessage")
                or {}
            )
            if isinstance(buttons_msg, dict):
                btn_id = (
                    buttons_msg.get("selectedButtonID")
                    or buttons_msg.get("selectedButtonId")
                    or buttons_msg.get("selectedId")
                )
                title = (
                    buttons_msg.get("selectedDisplayText")
                    or buttons_msg.get("selectedDisplayText")
                    or payload.get("body")
                )
                if isinstance(btn_id, str) and btn_id.strip():
                    return btn_id.strip(), (str(title).strip() if title else None)

        # GOWS-style Info.MediaType == list_response
        info = data.get("Info") or {}
        if isinstance(info, dict) and str(info.get("MediaType") or "").lower() == "list_response":
            nested = _dig(data, "Message", "listResponseMessage", "singleSelectReply", "selectedRowID")
            if isinstance(nested, str) and nested.strip():
                title = _dig(data, "Message", "listResponseMessage", "title") or payload.get("body")
                return nested.strip(), (str(title).strip() if title else None)

    return None, None


def _is_audio_media(payload: dict[str, Any]) -> bool:
    if not payload.get("hasMedia"):
        return False
    media = payload.get("media")
    if not isinstance(media, dict):
        return False
    mimetype = str(media.get("mimetype") or media.get("mimetype") or "").lower()
    if any(mimetype.startswith(prefix) for prefix in _AUDIO_MIME_PREFIXES):
        return True
    # Voice notes sometimes arrive as ogg without a clear audio/ prefix.
    url = str(media.get("url") or "")
    return url.endswith(".ogg") or url.endswith(".opus") or "audio" in mimetype


def should_ignore_waha_event(event_body: dict[str, Any]) -> bool:
    """Return True for events that must not enter the qualification pipeline."""
    event = str(event_body.get("event") or "")
    if event and event not in {"message", "message.any"}:
        return True
    payload = event_body.get("payload")
    if not isinstance(payload, dict):
        return True
    if payload.get("fromMe") is True:
        return True
    from_value = str(payload.get("from") or "")
    if from_value.endswith("@g.us") or from_value.endswith("@newsletter"):
        return True
    if from_value == "status@broadcast":
        return True
    return False


def parse_waha_inbound_to_extract_payload(event_body: dict[str, Any]) -> dict[str, Any] | None:
    """
    Map a WAHA webhook JSON body to the internal extract request payload.

    Returns ``None`` when the event should be acknowledged but not forwarded.
    """
    if should_ignore_waha_event(event_body):
        return None

    payload = event_body.get("payload")
    if not isinstance(payload, dict):
        raise WahaWebhookParseError("WAHA payload must be an object")

    from_value = payload.get("from")
    if not isinstance(from_value, str) or not from_value.strip():
        raise WahaWebhookParseError("WAHA payload.from is required")

    try:
        whatsapp_number = chat_id_to_e164(from_value)
    except ValueError as exc:
        raise WahaWebhookParseError("Invalid WAHA payload.from") from exc

    message_id = payload.get("id")
    if not isinstance(message_id, str) or not message_id.strip():
        raise WahaWebhookParseError("WAHA payload.id is required")

    body = payload.get("body")
    body_text = body.strip() if isinstance(body, str) else ""
    button_payload, button_text = _extract_button_payload(payload)

    result: dict[str, Any] = {
        "whatsapp_number": whatsapp_number,
        "message": body_text or None,
        "message_sid": message_id.strip(),
        "button_payload": button_payload,
        "button_text": button_text,
        "button_type": None,
        "interactive_data": None,
        "channel_metadata": None,
        "input_channel": "whatsapp_text",
        "media_url": None,
        "media_content_type": None,
    }

    if _is_audio_media(payload):
        media = payload.get("media") if isinstance(payload.get("media"), dict) else {}
        media_url = media.get("url") if isinstance(media, dict) else None
        if isinstance(media_url, str) and media_url.strip():
            mimetype = str(media.get("mimetype") or "audio/ogg")
            result["input_channel"] = "whatsapp_voice_note"
            result["media_url"] = media_url.strip()
            result["media_content_type"] = mimetype.split(";", 1)[0].strip() or "audio/ogg"
            # Voice notes often have empty body; keep caption if present.
            if not result["message"]:
                result["message"] = None

    return result
