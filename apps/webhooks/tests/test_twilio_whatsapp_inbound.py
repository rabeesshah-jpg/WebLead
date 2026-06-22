"""Tests for Twilio WhatsApp inbound webhook signature validation and forwarding."""

from __future__ import annotations

import json
from unittest.mock import patch
from urllib.parse import urlencode

import pytest
from django.conf import settings
from django.test import Client
from twilio.request_validator import RequestValidator

WEBHOOK_PATH = "/api/webhooks/twilio/whatsapp-inbound/"

SAMPLE_PARAMS = {
    "MessageSid": "SM1234567890abcdef1234567890abcd",
    "AccountSid": "AC1234567890abcdef1234567890abcd",
    "From": "whatsapp:+15551234567",
    "To": "whatsapp:+15557654321",
    "Body": "Hello from customer",
    "ProfileName": "Test User",
    "WaId": "15551234567",
    "NumMedia": "0",
}

AUTH_TOKEN = "test-twilio-auth-token"
FULL_SIGNATURE = "Np1nax6uFoY6qpfT5l9jWwJeit0="


@pytest.fixture
def client() -> Client:
    return Client()


def _validation_url(host: str = "testserver", *, https: bool = False) -> str:
    scheme = "https" if https else "http"
    return f"{scheme}://{host}{WEBHOOK_PATH}"


def _sign_params(
    params: dict[str, str],
    *,
    host: str = "testserver",
    https: bool = False,
    auth_token: str = AUTH_TOKEN,
) -> str:
    validator = RequestValidator(auth_token)
    return validator.compute_signature(_validation_url(host, https=https), params)


def _post_webhook(
    client: Client,
    params: dict[str, str],
    *,
    signature: str | None = "_COMPUTE_",
    host: str = "testserver",
    https: bool = False,
):
    headers: dict[str, str] = {"HTTP_HOST": host}
    if https:
        headers["HTTP_X_FORWARDED_PROTO"] = "https"
    if signature == "_COMPUTE_":
        signature = _sign_params(params, host=host, https=https)
    if signature is not None:
        headers["HTTP_X_TWILIO_SIGNATURE"] = signature
    return client.post(
        WEBHOOK_PATH,
        data=urlencode(params),
        content_type="application/x-www-form-urlencoded",
        **headers,
    )


    response = _post_webhook(client, SAMPLE_PARAMS)

    assert response.status_code == 200
    mock_forward.assert_called_once_with(SAMPLE_PARAMS)


@patch("apps.webhooks.views.forward_to_n8n")
def test_invalid_signature_returns_403_and_does_not_forward(mock_forward, client):
    response = _post_webhook(client, SAMPLE_PARAMS, signature="invalid-signature-value")

    assert response.status_code == 403
    mock_forward.assert_not_called()


@patch("apps.webhooks.views.forward_to_n8n")
def test_missing_signature_returns_403_and_does_not_forward(mock_forward, client):
    response = _post_webhook(client, SAMPLE_PARAMS, signature=None)

    assert response.status_code == 403
    mock_forward.assert_not_called()


@patch("apps.webhooks.views.forward_to_n8n")
def test_valid_request_forwards_original_form_fields(mock_forward, client):
    _post_webhook(client, SAMPLE_PARAMS)

    forwarded_params = mock_forward.call_args.args[0]
    assert forwarded_params == SAMPLE_PARAMS
    assert forwarded_params["Body"] == "Hello from customer"
    assert forwarded_params["From"] == "whatsapp:+15551234567"


@patch("apps.webhooks.views.forward_to_n8n", side_effect=Exception("should not run"))
def test_invalid_request_is_not_forwarded(mock_forward, client):
    _post_webhook(client, SAMPLE_PARAMS, signature="bad-signature")

    mock_forward.assert_not_called()


@patch("apps.webhooks.n8n_forward.urllib.request.urlopen")
def test_n8n_failure_returns_502(mock_urlopen, client):
    import urllib.error

    mock_urlopen.side_effect = urllib.error.URLError("timed out")

    response = _post_webhook(client, SAMPLE_PARAMS)

    assert response.status_code == 502
    assert "upstream" not in response.content.decode()


@patch("apps.webhooks.views.forward_to_n8n")
def test_reverse_proxy_https_url_used_for_validation(mock_forward, client):
    response = _post_webhook(
        client,
        SAMPLE_PARAMS,
        host="api.example.com",
        https=True,
    )

    assert response.status_code == 200
    mock_forward.assert_called_once()


@patch("apps.webhooks.views.forward_to_n8n")
def test_signature_validation_failed_log_is_sanitized(mock_forward, client, caplog):
    caplog.set_level("WARNING", logger="apps.webhooks.twilio")

    _post_webhook(client, SAMPLE_PARAMS, signature=None)

    twilio_records = [r for r in caplog.records if r.name == "apps.webhooks.twilio"]
    assert len(twilio_records) == 1
    payload = json.loads(twilio_records[0].message)
    assert payload == {
        "event": "twilio_signature_validation_failed",
        "timestamp": payload["timestamp"],
        "request_path": WEBHOOK_PATH,
        "message_sid_prefix": SAMPLE_PARAMS["MessageSid"][:8],
        "reason": "missing_signature",
    }

    log_blob = caplog.text
    assert AUTH_TOKEN not in log_blob
    assert FULL_SIGNATURE not in log_blob
    assert SAMPLE_PARAMS["Body"] not in log_blob
    assert SAMPLE_PARAMS["From"] not in log_blob
    assert SAMPLE_PARAMS["AccountSid"] not in log_blob
    assert SAMPLE_PARAMS["MessageSid"] not in log_blob


@patch("apps.webhooks.views.forward_to_n8n")
def test_invalid_signature_log_reason_and_sanitization(mock_forward, client, caplog):
    caplog.set_level("WARNING", logger="apps.webhooks.twilio")

    _post_webhook(client, SAMPLE_PARAMS, signature="totally-invalid-signature")

    twilio_records = [r for r in caplog.records if r.name == "apps.webhooks.twilio"]
    payload = json.loads(twilio_records[0].message)
    assert payload["reason"] == "signature_mismatch"
    assert payload["message_sid_prefix"] == SAMPLE_PARAMS["MessageSid"][:8]

    log_blob = caplog.text
    assert "totally-invalid-signature" not in log_blob
    assert SAMPLE_PARAMS["Body"] not in log_blob
    assert SAMPLE_PARAMS["From"] not in log_blob


@patch("apps.webhooks.n8n_forward.urllib.request.urlopen")
def test_forward_to_n8n_sends_secret_header(mock_urlopen, client):
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b""

    captured: dict[str, object] = {}

    def _capture_open(request, timeout=0):
        captured["headers"] = dict(request.header_items())
        captured["body"] = request.data.decode("utf-8")
        captured["timeout"] = timeout
        return FakeResponse()

    mock_urlopen.side_effect = _capture_open

    response = _post_webhook(client, SAMPLE_PARAMS)

    assert response.status_code == 200
    assert captured["headers"]["X-internal-webhook-secret"] == settings.N8N_WEBHOOK_SECRET
    assert "MessageSid=SM1234567890abcdef1234567890abcd" in captured["body"]
    assert captured["timeout"] == settings.N8N_FORWARD_TIMEOUT_SECONDS
