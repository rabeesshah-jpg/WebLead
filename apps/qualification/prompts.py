"""Prompts for lead-qualification structured extraction."""

from __future__ import annotations

import json
from typing import Any

from apps.qualification.domain.language_selection import LANGUAGE_ARABIC, normalize_conversation_language
from apps.qualification.domain.persona import NOURA_PERSONA_SYSTEM_CONTEXT

EXTRACTION_SYSTEM_PROMPT = f"""
{NOURA_PERSONA_SYSTEM_CONTEXT}

You are the structured extraction layer for this assistant.
Extract only from the user JSON (current_message, recent_history, collected_fields). Never invent data.
Never generate booking links, pricing, timelines, or availability.
Return one minified JSON object only (no markdown) with keys:
project_type (new_website|website_upgrade|new_and_upgrade|null), requirements, referral_source, whatsapp_confirmed,
preferred_phone, human_handoff_requested (boolean, never null), confidence.
confidence must contain only: project_type, requirements, referral_source, whatsapp_confirmed, preferred_phone (0.0-1.0).
Use null for missing values except human_handoff_requested (use false).
Never ask the customer to confirm their phone number or provide an alternative number; always return whatsapp_confirmed=null and preferred_phone=null (contact comes from the inbound WhatsApp number).
""".strip()

ARABIC_CONVERSATION_INSTRUCTIONS = """
The customer selected Arabic as their conversation language.

Rules:
- Respond to the customer only in Arabic.
- Use clear Modern Standard Arabic suitable for WhatsApp.
- Keep names, company names, phone numbers, email addresses, URLs, and codes unchanged.
- Keep structured output keys in the existing canonical English JSON schema.
- Ask only the next missing qualification question.
- Do not re-ask for information already validated and stored.
- Keep replies concise.
""".strip()


def build_extraction_system_prompt(*, conversation_language: str = "en") -> str:
    """Build the OpenRouter system prompt for the persisted conversation language."""
    prompt = EXTRACTION_SYSTEM_PROMPT.strip()
    if normalize_conversation_language(conversation_language) == LANGUAGE_ARABIC:
        prompt = f"{prompt}\n\n{ARABIC_CONVERSATION_INSTRUCTIONS}"
    return prompt

ConversationTurn = dict[str, str]


def build_extraction_user_message(
    *,
    customer_message: str,
    known_whatsapp_number: str,
    phone_confirmation_question_asked: bool = False,
    collected_fields: dict[str, Any] | None = None,
    recent_history: list[ConversationTurn] | None = None,
) -> str:
    """Build the compact user turn passed to the extraction model."""
    normalized_message = " ".join(customer_message.split())
    history = list(recent_history or [])
    payload = {
        "collected_fields": dict(collected_fields or {}),
        "recent_history": history,
        "current_message": normalized_message,
        "phone_confirmation_question_asked": phone_confirmation_question_asked,
        "known_whatsapp_number": known_whatsapp_number,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
