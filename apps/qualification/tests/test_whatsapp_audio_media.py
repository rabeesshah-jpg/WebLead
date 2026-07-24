"""Focused contract tests for the public WhatsApp voice reply media endpoint."""

from __future__ import annotations

import uuid

import pytest
from django.test import Client

from apps.qualification.media_views import whatsapp_voice_reply_media
from apps.webhooks import views as webhook_views

MEDIA_PATH_TEMPLATE = "/media/whatsapp_voice_replies/{audio_id}/"


@pytest.fixture
def client() -> Client:
    return Client()


def test_media_endpoint_is_plain_django_function_view():
    assert callable(whatsapp_voice_reply_media)
    assert whatsapp_voice_reply_media.__name__ == "whatsapp_voice_reply_media"
    assert not hasattr(whatsapp_voice_reply_media, "cls")


def test_waha_webhook_is_plain_django_function_view():
    assert callable(webhook_views.waha_whatsapp_inbound)
    assert webhook_views.waha_whatsapp_inbound.__name__ == "waha_whatsapp_inbound"
    assert not hasattr(webhook_views.waha_whatsapp_inbound, "cls")


def test_invalid_audio_id_returns_not_found(client):
    response = client.get(MEDIA_PATH_TEMPLATE.format(audio_id="not-a-valid-uuid"))

    assert response.status_code == 404


def test_missing_audio_file_returns_not_found(client):
    audio_id = str(uuid.uuid4())
    response = client.get(MEDIA_PATH_TEMPLATE.format(audio_id=audio_id))

    assert response.status_code == 404


def test_post_method_returns_method_not_allowed(client):
    audio_id = str(uuid.uuid4())
    response = client.post(MEDIA_PATH_TEMPLATE.format(audio_id=audio_id))

    assert response.status_code == 405
