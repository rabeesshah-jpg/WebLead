"""Tests for the shared option_template delivery contract and n8n request helper."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import override_settings

from apps.qualification.domain.option_template_delivery import (
    build_option_template_delivery_contract,
    resolve_option_template,
)
from apps.qualification.integrations.n8n_option_template_delivery import (
    N8nOptionTemplateDeliveryError,
    request_n8n_option_template_delivery,
)


def test_resolve_option_template_only_for_referral_source():
    assert (
        resolve_option_template(
            next_field="referral_source",
            input_channel="whatsapp_text",
            qualification_status="in_progress",
        )
        == "referral_source"
    )
    assert (
        resolve_option_template(
            next_field="business_type",
            input_channel="whatsapp_text",
            qualification_status="in_progress",
        )
        is None
    )
    assert (
        resolve_option_template(
            next_field="project_type",
            input_channel="whatsapp_text",
            qualification_status="in_progress",
        )
        is None
    )
    assert (
        resolve_option_template(
            next_field="referral_source",
            input_channel="whatsapp_voice_note",
            qualification_status="in_progress",
        )
        is None
    )


def test_referral_source_contract_matches_n8n_extract_fields():
    contract = build_option_template_delivery_contract(
        whatsapp_number="+923001234567",
        language="en",
        accepted_fields={"customer_type": "new_customer"},
        next_field="referral_source",
        source="new_customer_extract",
        delivery_idempotency_key="key-1",
        suppress_plain_text_body=False,
    )
    assert contract["option_template"] == "referral_source"
    assert contract["next_field"] == "referral_source"
    assert contract["conversation_state"] == "WAITING_FOR_REFERRAL_SOURCE"
    assert contract["qualification_status"] == "in_progress"
    assert contract["source"] == "new_customer_extract"
    assert contract["delivery_idempotency_key"] == "key-1"


@override_settings(
    N8N_OPTION_TEMPLATE_WEBHOOK_URL="https://n8n.example/webhook/option-template",
    N8N_WEBHOOK_SECRET="test-secret",
    N8N_FORWARD_TIMEOUT_SECONDS=5,
)
@patch("apps.qualification.integrations.n8n_option_template_delivery.urllib.request.urlopen")
def test_request_n8n_option_template_posts_json_contract(mock_urlopen):
    captured: dict[str, object] = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _capture_open(request, timeout=0):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["headers"] = dict(request.header_items())
        captured["body"] = request.data.decode("utf-8")
        captured["timeout"] = timeout
        return FakeResponse()

    mock_urlopen.side_effect = _capture_open

    contract = build_option_template_delivery_contract(
        whatsapp_number="+923001234567",
        language="en",
        accepted_fields={"customer_type": "new_customer"},
        next_field="referral_source",
    )
    request_n8n_option_template_delivery(contract)

    assert captured["url"] == "https://n8n.example/webhook/option-template"
    assert captured["method"] == "POST"
    assert captured["headers"]["Content-type"] == "application/json"
    assert captured["headers"]["X-internal-webhook-secret"] == "test-secret"
    body = str(captured["body"])
    assert '"option_template":"referral_source"' in body
    assert '"next_field":"referral_source"' in body


@override_settings(
    N8N_OPTION_TEMPLATE_WEBHOOK_URL="",
    N8N_WHATSAPP_WEBHOOK_URL="",
)
def test_request_n8n_option_template_requires_webhook_url():
    contract = build_option_template_delivery_contract(
        whatsapp_number="+923001234567",
        language="en",
        accepted_fields={"customer_type": "new_customer"},
        next_field="referral_source",
    )
    with pytest.raises(N8nOptionTemplateDeliveryError, match="not configured"):
        request_n8n_option_template_delivery(contract)
