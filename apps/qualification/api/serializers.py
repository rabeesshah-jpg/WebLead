"""DRF serializers for qualification internal APIs."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from rest_framework import serializers

from apps.qualification.channels import VALID_INPUT_CHANNELS, InputChannel
from apps.qualification.domain.constants import TWILIO_INBOUND_MESSAGE_SID_PATTERN
from apps.qualification.domain.validators import is_valid_e164_phone_number
from apps.qualification.whatsapp_audio import (
    DEFAULT_LANG,
    DEFAULT_VOICE,
    InvalidRenderAudioRequestError,
    sanitize_request_id,
)

ALLOWED_REQUEST_FIELDS = frozenset(
    {
        "message",
        "whatsapp_number",
        "input_channel",
        "message_sid",
        "media_url",
        "media_content_type",
        "button_payload",
        "button_text",
        "button_type",
        "interactive_data",
        "channel_metadata",
        "call_sid",
        "utterance_id",
        "is_final",
        # Explicit background/timer source only; never set for normal WhatsApp inbound.
        "event_source",
    },
)
VOICE_CALL_COMPLETED_EVENT = "voice_call.completed"
VALID_PROJECT_TYPES = frozenset({"new_website", "website_upgrade", "new_and_upgrade"})
ALLOWED_VOICE_CALL_COMPLETED_FIELDS = frozenset(
    {
        "event",
        "event_id",
        "call_id",
        "customer_phone",
        "whatsapp_number",
        "project_type",
        "requirements",
        "referral_source",
        "whatsapp_confirmed",
        "preferred_phone",
        "send_booking_link",
    },
)
ALLOWED_RENDER_AUDIO_FIELDS = frozenset(
    {
        "text",
        "voice",
        "lang",
        "request_id",
        "whatsapp_number",
        "conversation_language",
    },
)


def _normalize_optional_string(value: Any) -> str | None:
    """Normalize optional string fields; JSON null becomes None."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise serializers.ValidationError("Invalid optional string value.")
    stripped = value.strip()
    return stripped if stripped else None


class ExtractRequestSerializer(serializers.Serializer):
    """
    Contract-preserving HTTP request validation for the extract endpoint.

    This serializer mirrors ``_parse_extract_request()`` in ``views.py``.
    Domain and provider validation remain outside this serializer.
    """

    whatsapp_number = serializers.CharField(required=False, trim_whitespace=False)
    input_channel = serializers.CharField(
        required=False,
        default="whatsapp_text",
        trim_whitespace=False,
    )
    message = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        trim_whitespace=False,
    )
    message_sid = serializers.CharField(
        required=False,
        allow_null=True,
        trim_whitespace=False,
    )
    media_url = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        trim_whitespace=False,
    )
    media_content_type = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        trim_whitespace=False,
    )
    button_payload = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        trim_whitespace=False,
    )
    button_text = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        trim_whitespace=False,
    )
    button_type = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        trim_whitespace=False,
    )

    def validate_whatsapp_number(self, value: str) -> str:
        normalized_phone = "".join(value.split())
        if not is_valid_e164_phone_number(normalized_phone):
            raise serializers.ValidationError("Invalid whatsapp_number.")
        return normalized_phone

    @staticmethod
    def _has_voice_media_url(payload: dict[str, Any]) -> bool:
        media_url = _normalize_optional_string(payload.get("media_url"))
        return media_url is not None

    @staticmethod
    def _parse_input_channel(payload: dict[str, Any]) -> InputChannel:
        if "input_channel" in payload:
            raw_channel = payload["input_channel"]
            if not isinstance(raw_channel, str) or raw_channel not in VALID_INPUT_CHANNELS:
                raise serializers.ValidationError("Invalid input_channel.")
            return raw_channel  # type: ignore[return-value]

        if ExtractRequestSerializer._has_voice_media_url(payload):
            normalized_message = ExtractRequestSerializer._parse_optional_message(payload)
            if not normalized_message:
                return "whatsapp_voice_note"
        return "whatsapp_text"

    @staticmethod
    def _parse_message_sid(payload: dict[str, Any]) -> str | None:
        if "message_sid" not in payload:
            return None

        message_sid = payload["message_sid"]
        if message_sid is None:
            return None
        if not isinstance(message_sid, str) or not TWILIO_INBOUND_MESSAGE_SID_PATTERN.fullmatch(
            message_sid,
        ):
            raise serializers.ValidationError("Invalid message_sid.")
        return message_sid

    @staticmethod
    def _parse_media_url(payload: dict[str, Any], *, required: bool) -> str | None:
        if "media_url" not in payload:
            if required:
                raise serializers.ValidationError("Invalid media_url.")
            return None

        media_url = _normalize_optional_string(payload["media_url"])
        if media_url is None:
            if required:
                raise serializers.ValidationError("Invalid media_url.")
            return None

        parsed = urlparse(media_url)
        if parsed.scheme != "https":
            raise serializers.ValidationError("Invalid media_url.")
        return media_url

    @staticmethod
    def _parse_media_content_type(payload: dict[str, Any], *, required: bool) -> str | None:
        if "media_content_type" not in payload:
            if required:
                raise serializers.ValidationError("Invalid media_content_type.")
            return None

        media_content_type = _normalize_optional_string(payload["media_content_type"])
        if media_content_type is None:
            if required:
                raise serializers.ValidationError("Invalid media_content_type.")
            return None

        if not media_content_type.startswith("audio/"):
            raise serializers.ValidationError("Invalid media_content_type.")
        return media_content_type

    @staticmethod
    def _parse_optional_message(payload: dict[str, Any]) -> str | None:
        if "message" not in payload:
            return None

        message = payload["message"]
        if message is None:
            return None
        if not isinstance(message, str):
            raise serializers.ValidationError("Invalid message.")
        return message.strip() or None

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        payload = self.initial_data
        if not isinstance(payload, dict):
            raise serializers.ValidationError("Request payload must be a JSON object.")

        extra_keys = set(payload) - ALLOWED_REQUEST_FIELDS
        if extra_keys:
            raise serializers.ValidationError("Unexpected request fields.")

        if "whatsapp_number" not in payload:
            raise serializers.ValidationError("whatsapp_number is required.")

        whatsapp_number = payload["whatsapp_number"]
        if not isinstance(whatsapp_number, str):
            raise serializers.ValidationError("Invalid whatsapp_number.")

        normalized_phone = "".join(whatsapp_number.split())
        if not is_valid_e164_phone_number(normalized_phone):
            raise serializers.ValidationError("Invalid whatsapp_number.")

        normalized_message = self._parse_optional_message(payload)
        has_media_url = self._has_voice_media_url(payload)
        input_channel = self._parse_input_channel(payload)
        message_sid = self._parse_message_sid(payload)
        button_payload = _normalize_optional_string(payload.get("button_payload"))
        button_text = _normalize_optional_string(payload.get("button_text"))
        button_type = _normalize_optional_string(payload.get("button_type"))
        interactive_data = payload.get("interactive_data")
        if interactive_data is not None and not isinstance(interactive_data, (str, dict)):
            raise serializers.ValidationError("Invalid interactive_data.")
        channel_metadata = payload.get("channel_metadata")
        if channel_metadata is not None and not isinstance(channel_metadata, (str, dict)):
            raise serializers.ValidationError("Invalid channel_metadata.")

        common_fields = {
            "button_payload": button_payload,
            "button_text": button_text,
            "button_type": button_type,
            "interactive_data": interactive_data,
            "channel_metadata": channel_metadata,
            "call_sid": _normalize_optional_string(payload.get("call_sid")),
            "utterance_id": _normalize_optional_string(payload.get("utterance_id")),
            "event_source": _normalize_optional_string(payload.get("event_source")),
            "is_final": True,
        }

        if "is_final" in payload:
            if not isinstance(payload["is_final"], bool):
                raise serializers.ValidationError("Invalid is_final.")
            common_fields["is_final"] = payload["is_final"]

        if input_channel == "whatsapp_text":
            if not normalized_message:
                if has_media_url:
                    raise serializers.ValidationError(
                        "input_channel must be whatsapp_voice_note when media_url is provided.",
                    )
                raise serializers.ValidationError("message is required for whatsapp_text.")
            return {
                "whatsapp_number": normalized_phone,
                "message": normalized_message,
                "input_channel": input_channel,
                "message_sid": message_sid,
                "media_url": None,
                "media_content_type": None,
                **common_fields,
            }

        media_url = self._parse_media_url(payload, required=True)
        if media_url is None:
            if not normalized_message:
                raise serializers.ValidationError(
                    "message or media_url is required for whatsapp_voice_note.",
                )
            raise serializers.ValidationError("Invalid media_url.")
        if message_sid is None:
            raise serializers.ValidationError("message_sid is required when media_url is provided.")

        media_content_type = self._parse_media_content_type(payload, required=False) or "audio/ogg"

        return {
            "whatsapp_number": normalized_phone,
            "message": normalized_message,
            "input_channel": input_channel,
            "message_sid": message_sid,
            "media_url": media_url,
            "media_content_type": media_content_type,
            **common_fields,
        }


class ExtractResponseSerializer(serializers.Serializer):
    """
    Documents the existing extract endpoint success response contract.

    This serializer must not add keys, defaults, or reshaping beyond the live
    endpoint response produced by ``finalize_turn_response()``.
    """

    accepted_fields = serializers.DictField()
    rejected_fields = serializers.DictField()
    human_handoff_requested = serializers.BooleanField()
    next_field = serializers.CharField(allow_null=True)
    reply_text = serializers.CharField()
    qualification_status = serializers.CharField()
    conversation_language = serializers.CharField()
    preferred_phone = serializers.CharField(allow_null=True, required=False)
    reply_mode = serializers.CharField()
    spoken_text = serializers.CharField(required=False)
    whatsapp_text = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    actions = serializers.ListField(required=False, child=serializers.DictField())
    send_booking_link = serializers.BooleanField()
    booking_link_sent = serializers.BooleanField()
    booking_link = serializers.CharField(allow_null=True)
    should_send_text = serializers.BooleanField(required=False)
    should_send_audio = serializers.BooleanField(required=False)
    contains_booking_link = serializers.BooleanField(required=False)
    text_fallback_reply = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    transcript = serializers.CharField(required=False, allow_null=True)
    language_command_action = serializers.CharField(required=False, allow_null=True)
    followup_delay_seconds = serializers.IntegerField(required=False, allow_null=True)
    existing_customer_followup_scheduled = serializers.BooleanField(required=False)
    existing_customer_followup_sent = serializers.BooleanField(required=False)
    business_type_content_sid = serializers.CharField(required=False, allow_null=True)
    business_type_picker_sent = serializers.BooleanField(required=False)
    tts_enqueued = serializers.BooleanField(required=False)
    duplicate_detected = serializers.BooleanField(required=False)
    llm_parse_failed = serializers.BooleanField(required=False)
    idle_reset_triggered = serializers.BooleanField(required=False)
    inactivity_gap_seconds = serializers.IntegerField(required=False, allow_null=True)
    complete = serializers.BooleanField(required=False)
    classification = serializers.ListField(
        required=False,
        child=serializers.CharField(),
    )
    saved_services = serializers.ListField(
        required=False,
        child=serializers.CharField(),
    )
    saved_requirements = serializers.ListField(
        required=False,
        child=serializers.CharField(),
    )
    next_required_field = serializers.CharField(required=False, allow_null=True)
    duplicate_or_locked = serializers.BooleanField(required=False)
    lock_timeout = serializers.BooleanField(required=False)
    conversation_state = serializers.CharField(required=False, allow_null=True)
    option_template = serializers.CharField(required=False, allow_null=True)
    qualification_step = serializers.CharField(required=False, allow_null=True)
    language = serializers.CharField(required=False)
    qualification_complete = serializers.BooleanField(required=False)
    should_send_qualification_question = serializers.BooleanField(required=False)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if "transcript" not in instance:
            data.pop("transcript", None)
        if "language_command_action" not in instance:
            data.pop("language_command_action", None)
        for optional_key in (
            "spoken_text",
            "whatsapp_text",
            "actions",
            "should_send_text",
            "should_send_audio",
            "contains_booking_link",
            "text_fallback_reply",
            "tts_enqueued",
            "duplicate_detected",
            "llm_parse_failed",
            "idle_reset_triggered",
            "inactivity_gap_seconds",
            "complete",
            "classification",
            "saved_services",
            "saved_requirements",
            "next_required_field",
            "duplicate_or_locked",
            "lock_timeout",
            "conversation_state",
            "option_template",
            "followup_delay_seconds",
            "existing_customer_followup_scheduled",
            "existing_customer_followup_sent",
            "business_type_content_sid",
            "business_type_picker_sent",
            "qualification_step",
            "language",
            "qualification_complete",
            "should_send_qualification_question",
        ):
            if optional_key not in instance:
                data.pop(optional_key, None)
        return data


class VoiceCallCompletedRequestSerializer(serializers.Serializer):
    """Request validation for LiveKit post-call completion events."""

    event = serializers.CharField(trim_whitespace=False)
    event_id = serializers.CharField(trim_whitespace=False)
    call_id = serializers.CharField(trim_whitespace=False)
    customer_phone = serializers.CharField(trim_whitespace=False)
    whatsapp_number = serializers.CharField(trim_whitespace=False)
    project_type = serializers.CharField(trim_whitespace=False)
    requirements = serializers.CharField(trim_whitespace=False)
    referral_source = serializers.CharField(trim_whitespace=False)
    whatsapp_confirmed = serializers.BooleanField()
    preferred_phone = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        trim_whitespace=False,
    )
    send_booking_link = serializers.BooleanField()

    def _normalize_e164(self, value: str, *, field_name: str) -> str:
        normalized_phone = "".join(value.split())
        if not is_valid_e164_phone_number(normalized_phone):
            raise serializers.ValidationError(f"Invalid {field_name}.")
        return normalized_phone

    def validate_event(self, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise serializers.ValidationError("event is required.")
        if normalized != VOICE_CALL_COMPLETED_EVENT:
            raise serializers.ValidationError("Unsupported event.")
        return normalized

    def validate_event_id(self, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise serializers.ValidationError("event_id is required.")
        return normalized

    def validate_call_id(self, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise serializers.ValidationError("call_id is required.")
        return normalized

    def validate_customer_phone(self, value: str) -> str:
        return self._normalize_e164(value, field_name="customer_phone")

    def validate_whatsapp_number(self, value: str) -> str:
        return self._normalize_e164(value, field_name="whatsapp_number")

    def validate_project_type(self, value: str) -> str:
        normalized = value.strip()
        if normalized not in VALID_PROJECT_TYPES:
            raise serializers.ValidationError("Invalid project_type.")
        return normalized

    def validate_requirements(self, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise serializers.ValidationError("requirements is required.")
        return normalized

    def validate_referral_source(self, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise serializers.ValidationError("referral_source is required.")
        return normalized

    def validate_preferred_phone(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return self._normalize_e164(normalized, field_name="preferred_phone")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        payload = self.initial_data
        if not isinstance(payload, dict):
            raise serializers.ValidationError("Request payload must be a JSON object.")

        extra_keys = set(payload) - ALLOWED_VOICE_CALL_COMPLETED_FIELDS
        if extra_keys:
            raise serializers.ValidationError("Unexpected request fields.")

        missing_keys = ALLOWED_VOICE_CALL_COMPLETED_FIELDS - set(payload)
        if missing_keys:
            raise serializers.ValidationError("Missing required request fields.")

        return attrs


class VoiceCallCompletedResponseSerializer(serializers.Serializer):
    """Response contract for voice-call completion events."""

    status = serializers.CharField()
    event_id = serializers.CharField()
    call_id = serializers.CharField()
    accepted_fields = serializers.DictField(child=serializers.JSONField())
    qualification_status = serializers.CharField()
    spoken_text = serializers.CharField(required=False, allow_null=True)
    whatsapp_text = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    actions = serializers.ListField(required=False, child=serializers.DictField())
    send_booking_link = serializers.BooleanField()
    booking_link_sent = serializers.BooleanField()
    booking_link = serializers.CharField(allow_null=True)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        for optional_key in ("spoken_text", "whatsapp_text", "actions"):
            if optional_key not in instance:
                data.pop(optional_key, None)
        return data


class RenderAudioRequestSerializer(serializers.Serializer):
    """
    Contract-preserving HTTP request validation for the render-audio endpoint.

    This serializer mirrors ``_parse_render_audio_request()`` in
    ``render_audio_views.py``. TTS text-length validation and audio processing
    remain outside this serializer.
    """

    text = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    voice = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        trim_whitespace=False,
    )
    lang = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        trim_whitespace=False,
    )
    request_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        trim_whitespace=False,
    )
    whatsapp_number = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        trim_whitespace=False,
    )
    conversation_language = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        trim_whitespace=False,
    )

    def validate_whatsapp_number(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized_phone = "".join(value.split())
        if not is_valid_e164_phone_number(normalized_phone):
            raise serializers.ValidationError("Invalid whatsapp_number.")
        return normalized_phone

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        payload = self.initial_data
        if not isinstance(payload, dict):
            raise serializers.ValidationError("Request payload must be a JSON object.")

        extra_keys = set(payload) - ALLOWED_RENDER_AUDIO_FIELDS
        if extra_keys:
            raise serializers.ValidationError("Unexpected request fields.")

        if "text" not in payload:
            raise serializers.ValidationError("text is required.")

        text = payload["text"]
        if not isinstance(text, str):
            raise serializers.ValidationError("Invalid text.")

        voice = payload.get("voice", DEFAULT_VOICE)
        lang = payload.get("lang", DEFAULT_LANG)
        if not isinstance(voice, str) or not voice.strip():
            raise serializers.ValidationError("Invalid voice.")
        if not isinstance(lang, str) or not lang.strip():
            raise serializers.ValidationError("Invalid lang.")

        try:
            request_id = sanitize_request_id(payload.get("request_id"))
        except InvalidRenderAudioRequestError as exc:
            raise serializers.ValidationError("Invalid request_id.") from exc

        whatsapp_number = payload.get("whatsapp_number")
        if whatsapp_number is not None:
            if not isinstance(whatsapp_number, str):
                raise serializers.ValidationError("Invalid whatsapp_number.")
            normalized_phone = "".join(whatsapp_number.split())
            if not is_valid_e164_phone_number(normalized_phone):
                raise serializers.ValidationError("Invalid whatsapp_number.")
            whatsapp_number = normalized_phone
        else:
            whatsapp_number = None

        conversation_language = payload.get("conversation_language")
        if conversation_language is not None:
            if not isinstance(conversation_language, str) or not conversation_language.strip():
                raise serializers.ValidationError("Invalid conversation_language.")
            conversation_language = conversation_language.strip()
        else:
            conversation_language = None

        return {
            "text": text,
            "voice": voice.strip(),
            "lang": lang.strip(),
            "request_id": request_id,
            "whatsapp_number": whatsapp_number,
            "conversation_language": conversation_language,
        }


class RenderAudioResponseSerializer(serializers.Serializer):
    """
    Documents the render-audio endpoint success and text-fallback response contract.

    Legacy fields ``media_url`` and ``content_type`` are preserved for backward
    compatibility. New fields support n8n branching on ``fallback_to_text``.
    """

    status = serializers.CharField()
    fallback_to_text = serializers.BooleanField()
    conversation_language = serializers.CharField()
    media_url = serializers.CharField(required=False, allow_null=True)
    content_type = serializers.CharField(required=False, allow_null=True)
    audio_url = serializers.CharField(required=False, allow_null=True)
    audio_content_type = serializers.CharField(required=False, allow_null=True)
    fallback_reason = serializers.CharField(required=False, allow_null=True)
    request_id = serializers.CharField(required=False, allow_null=True)

    def to_representation(self, instance: dict[str, Any]) -> dict[str, Any]:
        data = super().to_representation(instance)
        if data.get("fallback_reason") is None:
            data.pop("fallback_reason", None)
        return data
