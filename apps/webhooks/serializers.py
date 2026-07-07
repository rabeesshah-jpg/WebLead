"""DRF serializers for Twilio WhatsApp inbound webhook payloads."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from rest_framework import serializers

from apps.qualification.domain.constants import TWILIO_INBOUND_MESSAGE_SID_PATTERN
from apps.qualification.domain.validators import is_valid_e164_phone_number


def _normalize_optional_twilio_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise serializers.ValidationError("Invalid optional string value.")
    stripped = value.strip()
    return stripped if stripped else None


def _normalize_whatsapp_from(value: str) -> str:
    normalized = value.strip()
    if normalized.lower().startswith("whatsapp:"):
        normalized = normalized.split(":", 1)[1]
    normalized = "".join(normalized.split())
    if not is_valid_e164_phone_number(normalized):
        raise serializers.ValidationError("Invalid From value.")
    return normalized


class TwilioInboundSerializer(serializers.Serializer):
    """
    Validate Twilio form-urlencoded WhatsApp inbound parameters.

    Preserves Twilio field names for request compatibility. Optional Quick Reply
    and media fields remain optional for standard text and voice-note messages.
    """

    Body = serializers.CharField(required=False, allow_blank=True, default="")
    From = serializers.CharField(required=True, trim_whitespace=False)
    MessageSid = serializers.CharField(required=True, trim_whitespace=False)
    ButtonPayload = serializers.CharField(required=False, allow_blank=True, default="")
    ButtonText = serializers.CharField(required=False, allow_blank=True, default="")
    ButtonType = serializers.CharField(required=False, allow_blank=True, default="")
    InteractiveData = serializers.CharField(required=False, allow_blank=True, default="")
    ChannelMetadata = serializers.CharField(required=False, allow_blank=True, default="")
    MediaUrl0 = serializers.CharField(required=False, allow_blank=True, default="")
    NumMedia = serializers.CharField(required=False, allow_blank=True, default="0")

    def validate_MessageSid(self, value: str) -> str:
        if not TWILIO_INBOUND_MESSAGE_SID_PATTERN.fullmatch(value):
            raise serializers.ValidationError("Invalid MessageSid.")
        return value

    def validate_From(self, value: str) -> str:
        return _normalize_whatsapp_from(value)

    def validate_NumMedia(self, value: str) -> str:
        if value == "":
            return "0"
        if not value.isdigit():
            raise serializers.ValidationError("Invalid NumMedia.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        payload = self.initial_data
        if not isinstance(payload, dict):
            raise serializers.ValidationError("Twilio payload must be an object.")

        media_url = _normalize_optional_twilio_string(payload.get("MediaUrl0"))
        if media_url is not None:
            parsed = urlparse(media_url)
            if parsed.scheme != "https":
                raise serializers.ValidationError("Invalid MediaUrl0.")

        return attrs

    @property
    def button_payload(self) -> str | None:
        return _normalize_optional_twilio_string(self.validated_data.get("ButtonPayload"))

    def to_extract_request_payload(self) -> dict[str, Any]:
        """Map validated Twilio fields to the internal qualification extract payload."""
        data = self.validated_data
        body = data.get("Body", "")
        media_url = _normalize_optional_twilio_string(data.get("MediaUrl0"))
        num_media = int(data.get("NumMedia") or "0")

        payload: dict[str, Any] = {
            "whatsapp_number": data["From"],
            "message": body.strip() or None,
            "message_sid": data["MessageSid"],
            "button_payload": self.button_payload,
            "button_text": _normalize_optional_twilio_string(data.get("ButtonText")),
            "button_type": _normalize_optional_twilio_string(data.get("ButtonType")),
            "interactive_data": _normalize_optional_twilio_string(data.get("InteractiveData")),
            "channel_metadata": _normalize_optional_twilio_string(data.get("ChannelMetadata")),
        }

        if media_url and num_media > 0:
            payload["input_channel"] = "whatsapp_voice_note"
            payload["media_url"] = media_url
            payload["media_content_type"] = "audio/ogg"
        else:
            payload["input_channel"] = "whatsapp_text"
            payload["media_url"] = None
            payload["media_content_type"] = None

        return payload
