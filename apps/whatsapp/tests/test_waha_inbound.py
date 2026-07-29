"""Tests for WAHA chatId helpers, inbound mapping, and webhook."""

from __future__ import annotations

import json
from unittest.mock import patch

from django.test import Client, override_settings

from apps.whatsapp.config import chat_id_to_e164, phone_to_chat_id
from apps.whatsapp.webhook_handler import parse_waha_inbound_to_extract_payload


def test_phone_to_chat_id_strips_plus_and_whatsapp_prefix():
    assert phone_to_chat_id("+923121363468") == "923121363468@c.us"
    assert phone_to_chat_id("whatsapp:+923121363468") == "923121363468@c.us"
    assert phone_to_chat_id("923121363468@c.us") == "923121363468@c.us"


def test_chat_id_to_e164():
    assert chat_id_to_e164("923121363468@c.us") == "+923121363468"


def test_parse_waha_text_message():
    payload = parse_waha_inbound_to_extract_payload(
        {
            "event": "message",
            "session": "default",
            "payload": {
                "id": "true_923121363468@c.us_ABCDEF1234567890",
                "from": "923246271149@c.us",
                "fromMe": False,
                "body": "Hello",
                "hasMedia": False}}
    )
    assert payload is not None
    assert payload["whatsapp_number"] == "+923246271149"
    assert payload["message"] == "Hello"
    assert payload["message_sid"] == "true_923121363468@c.us_ABCDEF1234567890"
    assert payload["input_channel"] == "whatsapp_text"


def test_parse_waha_list_reply_button_payload():
    payload = parse_waha_inbound_to_extract_payload(
        {
            "event": "message",
            "payload": {
                "id": "true_923246271149@c.us_LISTREPLY001",
                "from": "923246271149@c.us",
                "fromMe": False,
                "body": "Google",
                "hasMedia": False,
                "_data": {
                    "Message": {
                        "listResponseMessage": {
                            "title": "Google",
                            "singleSelectReply": {"selectedRowID": "google"}}
                    }
                }}}
    )
    assert payload is not None
    assert payload["button_payload"] == "google"
    assert payload["button_text"] == "Google"


def test_parse_waha_ignores_from_me():
    assert (
        parse_waha_inbound_to_extract_payload(
            {
                "event": "message",
                "payload": {
                    "id": "true_1@c.us_xxxxx001",
                    "from": "923246271149@c.us",
                    "fromMe": True,
                    "body": "me"}}
        )
        is None
    )


@override_settings(
    WAHA_WEBHOOK_SECRET="test-waha-webhook-secret",
    N8N_WEBHOOK_URL="https://n8n.example/webhook/whatsapp-inbound",
    N8N_WEBHOOK_SECRET="test-n8n-webhook-secret",
)
def test_waha_inbound_webhook_forwards_json():
    client = Client()
    with patch("apps.webhooks.views.forward_to_n8n") as mock_forward:
        response = client.post(
            "/api/webhooks/waha/whatsapp-inbound/",
            data=json.dumps(
                {
                    "event": "message",
                    "payload": {
                        "id": "true_923246271149@c.us_ABCDEF1234567890",
                        "from": "923246271149@c.us",
                        "fromMe": False,
                        "body": "Hi",
                        "hasMedia": False}}
            ),
            content_type="application/json",
            HTTP_X_API_KEY="test-waha-webhook-secret",
        )
    assert response.status_code == 200
    mock_forward.assert_called_once()
    args, kwargs = mock_forward.call_args
    assert args[0]["whatsapp_number"] == "+923246271149"
    assert args[0]["message"] == "Hi"
    assert kwargs.get("as_json") is True


@override_settings(WAHA_WEBHOOK_SECRET="test-waha-webhook-secret")
def test_waha_inbound_webhook_rejects_bad_key():
    client = Client()
    response = client.post(
        "/api/webhooks/waha/whatsapp-inbound/",
        data=json.dumps({"event": "message", "payload": {}}),
        content_type="application/json",
        HTTP_X_API_KEY="wrong",
    )
    assert response.status_code == 403
