"""Tests for Noura UX: concise replies, onboarding gating, and persona interactions."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import Client, override_settings

from apps.qualification.conversation_state import clear_conversations, save_accepted_fields
from apps.qualification.domain.inbound_message_classification import (
    classify_inbound_message,
    infer_project_type_from_answer,
    is_direct_project_type_answer,
)
from apps.qualification.domain.messages import get_customer_message
from apps.qualification.domain.persona import AGENT_NAME, COMPANY_NAME
from apps.qualification.message_idempotency import clear_message_sid_cache
from apps.qualification.models import QualificationFieldFilterResult
from apps.qualification.tests.internal_api_test_helpers import API_SECRET, internal_api_auth_headers

pytestmark = pytest.mark.django_db

ENDPOINT_PATH = "/api/internal/qualification/extract/"
WHATSAPP_NUMBER = "+923001234567"


@pytest.fixture
def client() -> Client:
    clear_conversations()
    return Client()


@pytest.fixture(autouse=True)
def _reset_state():
    clear_conversations()
    clear_message_sid_cache()
    yield
    clear_conversations()
    clear_message_sid_cache()


def _post_text(client: Client, message: str) -> object:
    return client.post(
        ENDPOINT_PATH,
        data={
            "message": message,
            "whatsapp_number": WHATSAPP_NUMBER,
            "input_channel": "whatsapp_text",
        },
        content_type="application/json",
        **internal_api_auth_headers(),
    )


def _assert_no_excessive_bold(text: str) -> None:
    assert "*" not in text


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_hello_how_are_you_does_not_return_full_onboarding(mock_extract, client):
    response = _post_text(client, "Hello how are you")

    body = response.json()
    assert response.status_code == 200
    assert "doing well" in body["reply_text"]
    assert "new website" in body["reply_text"]
    assert "How to use this chat" not in body["reply_text"]
    assert "Send M to open the menu" not in body["reply_text"]
    _assert_no_excessive_bold(body["reply_text"])
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_how_are_you_returns_short_reply_and_current_question(mock_extract, client):
    response = _post_text(client, "How are you?")

    body = response.json()
    assert response.status_code == 200
    assert body["reply_text"].startswith("I'm doing well, thanks for asking.")
    assert "new website" in body["reply_text"]
    assert "To get started" not in body["reply_text"]
    _assert_no_excessive_bold(body["reply_text"])
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_whats_your_name_returns_noura_identity_and_current_question(mock_extract, client):
    response = _post_text(client, "What's your name?")

    body = response.json()
    assert response.status_code == 200
    assert f"I'm {AGENT_NAME} from {COMPANY_NAME}" in body["reply_text"]
    assert "new website" in body["reply_text"]
    assert "identity_question" in body["classification"]
    _assert_no_excessive_bold(body["reply_text"])
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_tell_me_about_your_role_returns_role_answer_and_current_question(mock_extract, client):
    response = _post_text(client, "Tell me about your role")

    body = response.json()
    assert response.status_code == 200
    assert "understand your website needs" in body["reply_text"]
    assert "new website" in body["reply_text"]
    assert "role_question" in body["classification"]
    _assert_no_excessive_bold(body["reply_text"])
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_what_do_you_do_returns_role_alt_answer(mock_extract, client):
    response = _post_text(client, "What do you do?")

    body = response.json()
    assert response.status_code == 200
    assert "website requirements" in body["reply_text"]
    assert "role_question" in body["classification"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_help_request_returns_full_onboarding_instructions(mock_extract, client):
    response = _post_text(client, "help")

    body = response.json()
    assert response.status_code == 200
    assert "How to use this chat" in body["reply_text"]
    assert "Send M to open the menu" in body["reply_text"]
    assert "help_request" in body["classification"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_completed_fields_are_not_repeated_after_small_talk(mock_extract, client):
    save_accepted_fields(
        WHATSAPP_NUMBER,
        {"project_type": "new_website"},
    )

    response = _post_text(client, "How are you?")

    body = response.json()
    assert response.status_code == 200
    assert "May I know what type of website help you need?" in body["reply_text"]
    assert body["next_field"] == "requirements"
    assert "new website or an upgrade" not in body["reply_text"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_pricing_question_does_not_use_to_get_started(mock_extract, client):
    response = _post_text(client, "What is the price?")

    body = response.json()
    assert response.status_code == 200
    assert "website specialist" in body["reply_text"]
    assert "To get started" not in body["reply_text"]
    _assert_no_excessive_bold(body["reply_text"])
    mock_extract.assert_not_called()


def test_combined_greeting_and_wellbeing_classification():
    classification = classify_inbound_message("Hello how are you")
    assert classification.small_talk_greeting is True
    assert classification.small_talk_wellbeing is True


def test_assalam_alaikum_how_are_you_is_small_talk():
    classification = classify_inbound_message("Assalam o Alaikum, how are you?")
    assert classification.small_talk_greeting is True
    assert classification.small_talk_wellbeing is True


def test_role_question_is_not_classified_as_services_faq():
    classification = classify_inbound_message("What do you do?")
    assert classification.role_question is True
    assert classification.user_question_services is False


def test_onboarding_intro_mentions_noura_without_excessive_bold():
    intro = get_customer_message(language="en", key="onboarding_intro")
    assert f"Noura from {COMPANY_NAME}" in intro
    assert "To get started" in intro
    assert "*" not in intro


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_thanks_and_how_are_you_returns_wellbeing_and_current_question(mock_extract, client):
    response = _post_text(client, "Oh nice thanks and how are you")

    body = response.json()
    assert response.status_code == 200
    assert "doing well" in body["reply_text"]
    assert "Please choose one" in body["reply_text"]
    assert "I've noted that" not in body["reply_text"]
    assert "How to use this chat" not in body["reply_text"]
    assert body["accepted_fields"] == {}
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_nice_how_are_you_brother_does_not_store_lead_data(mock_extract, client):
    response = _post_text(client, "So nice how are you brother")

    body = response.json()
    assert response.status_code == 200
    assert "doing well" in body["reply_text"]
    assert "Please choose one" in body["reply_text"]
    assert "I've noted that" not in body["reply_text"]
    assert "May I ask one more quick question" not in body["reply_text"]
    assert body["accepted_fields"] == {}
    assert body.get("saved_requirements") in (None, [])
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_what_your_role_returns_role_answer_not_unsupported_fallback(mock_extract, client):
    response = _post_text(client, "And what your role??")

    body = response.json()
    assert response.status_code == 200
    assert "understand your website needs" in body["reply_text"]
    assert "new website" in body["reply_text"]
    assert "website specialist can guide you" not in body["reply_text"]
    assert "role_question" in body["classification"]
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_tell_me_about_yourself_during_qualification_skips_full_onboarding(
    mock_extract,
    client,
):
    save_accepted_fields(WHATSAPP_NUMBER, {"project_type": "new_website"})

    response = _post_text(
        client,
        "I'll tell you after some time but first tell me about your self",
    )

    body = response.json()
    assert response.status_code == 200
    assert "I'm Noura from Good Websites" in body["reply_text"]
    assert "website inquiries" in body["reply_text"]
    assert "May I know what type of website help you need?" in body["reply_text"]
    assert "How to use this chat" not in body["reply_text"]
    assert "Send M to open the menu" not in body["reply_text"]
    assert "about_yourself_question" in body["classification"]
    assert body["accepted_fields"] == {"project_type": "new_website"}
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_small_talk_during_active_qualification_skips_full_onboarding(mock_extract, client):
    save_accepted_fields(WHATSAPP_NUMBER, {"project_type": "new_website"})

    response = _post_text(client, "how are you bro")

    body = response.json()
    assert response.status_code == 200
    assert "doing well" in body["reply_text"]
    assert "How to use this chat" not in body["reply_text"]
    assert body["accepted_fields"] == {"project_type": "new_website"}
    mock_extract.assert_not_called()


def test_wellbeing_variants_are_classified_as_small_talk():
    for message in (
        "how are you",
        "how are you bro",
        "how are you brother",
        "and how are you",
        "thanks and how are you",
        "nice, how are you",
        "how r u",
        "how are u",
        "Oh nice thanks and how are you",
    ):
        classification = classify_inbound_message(message)
        assert classification.small_talk_wellbeing is True, message


def test_role_question_variants_are_not_unsupported():
    for message in (
        "what is your role",
        "what's your role",
        "what your role",
        "what do you do",
        "what is your job",
        "how can you help me",
        "who are you",
        "tell me your role",
        "And what your role??",
    ):
        classification = classify_inbound_message(message)
        assert classification.role_question or classification.identity_question, message
        assert classification.unsupported_or_unclear_question is False, message


def test_about_yourself_variants_are_classified():
    for message in (
        "tell me about yourself",
        "tell me about your self",
        "introduce yourself",
        "first tell me about yourself",
        "about you",
        "who are you",
    ):
        classification = classify_inbound_message(message)
        assert (
            classification.about_yourself_question or classification.identity_question
        ), message


def _seed_onboarded_qualification(**fields: object) -> None:
    save_accepted_fields(WHATSAPP_NUMBER, dict(fields))


def _assert_no_onboarding(body: dict) -> None:
    assert "How to use this chat" not in body["reply_text"]
    assert "Send M to open the menu" not in body["reply_text"]
    assert "To get started" not in body["reply_text"]


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_both_answer_skips_onboarding_and_asks_requirements(mock_extract, client):
    response = _post_text(client, "Both")

    body = response.json()
    assert response.status_code == 200
    assert body["accepted_fields"]["project_type"] == "new_and_upgrade"
    assert body["next_field"] == "requirements"
    assert body["reply_text"] == (
        "Great, thanks. May I know what type of website help you need?"
    )
    _assert_no_onboarding(body)
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_new_website_answer_skips_onboarding_and_asks_requirements(mock_extract, client):
    response = _post_text(client, "new website")

    body = response.json()
    assert response.status_code == 200
    assert body["accepted_fields"]["project_type"] == "new_website"
    assert body["next_field"] == "requirements"
    assert "Great, thanks." in body["reply_text"]
    assert "May I know what type of website help you need?" in body["reply_text"]
    _assert_no_onboarding(body)
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_upgrade_existing_website_skips_onboarding_and_asks_requirements(mock_extract, client):
    response = _post_text(client, "upgrade existing website")

    body = response.json()
    assert response.status_code == 200
    assert body["accepted_fields"]["project_type"] == "website_upgrade"
    assert body["next_field"] == "requirements"
    assert "Great, thanks." in body["reply_text"]
    _assert_no_onboarding(body)
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_nice_good_while_waiting_for_requirements_does_not_store_requirements(
    mock_extract,
    client,
):
    _seed_onboarded_qualification(project_type="new_and_upgrade")

    response = _post_text(client, "Nice good")

    body = response.json()
    assert response.status_code == 200
    assert body["accepted_fields"] == {"project_type": "new_and_upgrade"}
    assert body["next_field"] == "requirements"
    assert body["reply_text"] == "May I know what type of website help you need?"
    assert "I've noted that" not in body["reply_text"]
    _assert_no_onboarding(body)
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_ecommerce_requirement_stores_and_asks_referral_source(mock_extract, client):
    _seed_onboarded_qualification(project_type="new_and_upgrade")

    response = _post_text(client, "E-commerce website")

    body = response.json()
    assert response.status_code == 200
    assert body["accepted_fields"]["project_type"] == "new_and_upgrade"
    assert "E-commerce website" in body["accepted_fields"]["requirements"]
    assert body["next_field"] == "referral_source"
    assert body["reply_text"] == (
        "Thank you. How did you hear about Good Websites?"
    )
    _assert_no_onboarding(body)
    mock_extract.assert_not_called()


@override_settings(N8N_QUALIFICATION_API_SECRET=API_SECRET)
@patch("apps.qualification.qualification_turn.extract_qualification_from_openrouter")
def test_valid_llm_capture_never_replays_onboarding(mock_extract, client):
    _seed_onboarded_qualification(project_type="new_website", requirements="shop site")
    mock_extract.return_value = QualificationFieldFilterResult(
        accepted_fields={"referral_source": "Instagram"},
        rejected_fields=(),
        human_handoff_requested=False,
    )

    response = _post_text(client, "Instagram")

    body = response.json()
    assert response.status_code == 200
    assert body["accepted_fields"]["referral_source"] == "Instagram"
    assert body["next_field"] == "whatsapp_confirmed"
    assert body["reply_text"] == (
        "Thanks. Is this the best contact number for our team to reach you?"
    )
    _assert_no_onboarding(body)
    mock_extract.assert_called_once()


def test_infer_project_type_from_answer_variants():
    assert infer_project_type_from_answer("Both") == "new_and_upgrade"
    assert infer_project_type_from_answer("new website") == "new_website"
    assert infer_project_type_from_answer("upgrade existing website") == "website_upgrade"


def test_requirement_statement_is_not_direct_project_type_answer():
    assert is_direct_project_type_answer("Both") is True
    assert is_direct_project_type_answer("new website") is True
    assert is_direct_project_type_answer("I need a new website") is False
    assert is_direct_project_type_answer("I need a new website for my restaurant.") is False
