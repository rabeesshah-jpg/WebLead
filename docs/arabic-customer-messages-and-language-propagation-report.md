# Arabic Customer Messages and Language Propagation Report

## Scope Completed
- Customer-facing English/Arabic message catalog
- Language-aware local qualification start
- Language propagation through qualification responses
- Language-aware OpenRouter prompt instructions
- Arabic validation, fallback, completion, and handoff messages

## Architecture Used
- **Conversation model and language source:** `WhatsAppConversationSession.language` is the single source of truth, read via `get_conversation_language()` in `apps/qualification/domain/language.py`.
- **Qualification service:** `ExtractService` and `handle_qualification_turn()` load persisted language and pass it into turn building and OpenRouter extraction.
- **OpenRouter prompt layer:** `build_extraction_system_prompt(conversation_language=...)` in `apps/qualification/prompts.py` appends Arabic instructions when the session language is `ar`.
- **Response formatter:** `build_turn_response()`, `try_handle_whatsapp_confirmation_turn()`, `build_completed_retry_response()`, and `build_qualification_start_response()` use `get_customer_message()` / `get_qualification_question()` from the message catalog. `finalize_turn_response()` in `channels.py` attaches `conversation_language` and language-aware completion text.
- **Existing API endpoint:** `POST /api/internal/qualification/extract/` unchanged in path and auth; responses now include `conversation_language`.

## Files Changed
| File | Purpose |
| --- | --- |
| `apps/qualification/domain/messages.py` | Central bilingual `QUALIFICATION_MESSAGES` catalog and `get_customer_message()` helper |
| `apps/qualification/domain/language_selection.py` | `normalize_conversation_language()` helper (import-safe, no model dependency) |
| `apps/qualification/domain/language.py` | `get_conversation_language()` reads persisted session language |
| `apps/qualification/conversation_flow.py` | Language-aware turn responses, invalid-phone and generic-retry handling |
| `apps/qualification/channels.py` | `finalize_turn_response()` adds `conversation_language` and localized completion text |
| `apps/qualification/services/language_gate_service.py` | Language-aware qualification start after `lang_en` / `lang_ar` |
| `apps/qualification/services/extract_service.py` | Loads session language and passes it through finalization |
| `apps/qualification/qualification_turn.py` | Passes `conversation_language` to OpenRouter and turn builder |
| `apps/qualification/prompts.py` | `build_extraction_system_prompt()` with Arabic conversation instructions |
| `apps/qualification/integrations/openrouter.py` | Forwards `conversation_language` into request payload construction |
| `apps/qualification/openrouter_client.py` | Forwards `conversation_language` to transport layer |
| `apps/qualification/api/serializers.py` | Documents `conversation_language` on `ExtractResponseSerializer` |
| `apps/qualification/tests/test_qualification_messages.py` | Message catalog unit tests |
| `apps/qualification/tests/test_arabic_language_propagation.py` | Arabic flow, OpenRouter prompt, validation, and propagation tests |
| `apps/qualification/tests/test_language_gate_routing.py` | Updated for Arabic first question and `conversation_language` |
| `apps/qualification/tests/test_conversation_flow.py` | Updated OpenRouter call assertions |
| `apps/qualification/tests/test_extract_service.py` | Updated expected payloads |
| `apps/qualification/tests/test_extract_serializers.py` | Updated response contract fixtures |
| `apps/qualification/tests/test_extract_api_view.py` | Updated expected API body |
| `apps/qualification/tests/test_internal_extract_endpoint.py` | Updated OpenRouter mock assertions |
| `apps/qualification/tests/internal_api_test_helpers.py` | Added `conversation_language` to success field set |
| `conftest.py` | Test harness compatibility (Django setup, migrations, language mocks for non-gate tests) |

## Customer Message Coverage
| Category | English key | Arabic provided |
| --- | --- | --- |
| Qualification questions | `project_type`, `requirements`, `referral_source`, `whatsapp_confirmed`, `preferred_phone` | Yes |
| WhatsApp confirmation unclear | `whatsapp_confirmation_unclear` | Yes |
| Phone validation | `invalid_phone` | Yes |
| Completion | `completion` | Yes |
| Human handoff | `human_handoff` | Yes |
| Generic retry / fallback | `generic_retry`, `generic_error` | Yes |

English question text is unchanged from the pre-existing flow. Arabic `project_type` uses the required opener: **ما نوع الموقع الإلكتروني الذي تحتاجه؟**

## Language Propagation
1. `WhatsAppConversationSession.language` is set by `LanguageGateService` on `lang_en` / `lang_ar` (or typed fallback when unset).
2. `get_conversation_language(whatsapp_number)` reads the session on each qualification turn.
3. `handle_qualification_turn()` passes `conversation_language` into `extract_qualification_from_openrouter()` and `build_turn_response()`.
4. `build_extraction_system_prompt()` adds Arabic LLM instructions when language is `ar`; structured JSON keys remain English.
5. `finalize_turn_response()` ensures every normal extract response includes `conversation_language`.
6. Cached idempotent responses include `conversation_language` because the full finalized payload is cached.

### Response payload examples

**English after `lang_en`:**
```json
{
  "conversation_language": "en",
  "reply_text": "Are you looking for a new website or an upgrade to your existing website?",
  "qualification_status": "in_progress",
  "next_field": "project_type"
}
```

**Arabic after `lang_ar`:**
```json
{
  "conversation_language": "ar",
  "reply_text": "ما نوع الموقع الإلكتروني الذي تحتاجه؟",
  "qualification_status": "in_progress",
  "next_field": "project_type"
}
```

**Arabic mid-flow:**
```json
{
  "accepted_fields": {"project_type": "new_website"},
  "next_field": "requirements",
  "reply_text": "ما الذي تبحث عنه تحديدًا؟",
  "conversation_language": "ar",
  "qualification_status": "in_progress"
}
```

## Backward Compatibility
- English customer wording preserved (same English strings as before, now sourced from the catalog).
- All existing n8n response fields retained (`accepted_fields`, `reply_mode`, `transcript`, `send_booking_link`, etc.).
- `conversation_language` added only as a new optional-compatible field for downstream n8n use.
- `MessageSid` idempotency, Redis state, accepted-field storage, and language-gate behavior unchanged.
- Non-gate tests continue on the English path via conftest language-gate bypass and `conversation_language="en"` mocking.

## Tests and Results

Commands run:
```bash
python manage.py makemigrations --check --dry-run
python manage.py test
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 DJANGO_SETTINGS_MODULE=config.settings_test .venv/bin/python -m pytest -p pytest_django -q
```

Results:
- `makemigrations --check --dry-run`: **No changes detected**
- `python manage.py test`: **0 tests** (project uses pytest as the primary runner; no Django `TestCase` modules)
- Full pytest suite: **516 passed**, 5 warnings (pytest-django mark/config warnings in this environment)

Focused suites exercised:
- `test_qualification_messages.py`
- `test_arabic_language_propagation.py`
- `test_language_gate_routing.py`
- `test_conversation_flow.py`
- `test_extract_service.py`
- Full regression including idempotency, OpenRouter, serializers, and internal extract endpoint tests

## Intentionally Deferred
- Arabic Deepgram model selection and voice-note transcription routing
- Arabic Supertonic TTS / `lang: "ar"` render-audio behavior
- n8n workflow IF nodes or template changes
- Language-change commands after initial selection
- Automatic language detection from message body text
