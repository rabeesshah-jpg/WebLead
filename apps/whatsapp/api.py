"""Internal API for n8n to send WhatsApp text via WAHA (without holding WAHA_API_KEY)."""

from __future__ import annotations

from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.qualification.api.permissions import InternalWebhookSecretPermission
from apps.qualification.domain.validators import is_valid_e164_phone_number
from apps.whatsapp.message_service import WhatsAppSendError, send_whatsapp_message


class SendWhatsAppMessageSerializer(serializers.Serializer):
    phone_number = serializers.CharField(required=True, trim_whitespace=False)
    message = serializers.CharField(required=True, allow_blank=False, trim_whitespace=False)

    def validate_phone_number(self, value: str) -> str:
        normalized = "".join(value.split())
        if normalized.lower().startswith("whatsapp:"):
            normalized = normalized.split(":", 1)[1]
        if not is_valid_e164_phone_number(normalized):
            raise serializers.ValidationError("Invalid phone_number.")
        return normalized


class SendWhatsAppMessageAPIView(APIView):
    authentication_classes: list = []
    permission_classes = [InternalWebhookSecretPermission]

    def post(self, request: Request) -> Response:
        serializer = SendWhatsAppMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            message_id = send_whatsapp_message(data["phone_number"], data["message"])
        except WhatsAppSendError as exc:
            return Response(
                {"error": "whatsapp_send_failed", "detail": str(exc)[:300]},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(
            {"ok": True, "message_id": message_id or None},
            status=status.HTTP_200_OK,
        )
