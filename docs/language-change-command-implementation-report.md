# Language-Change Command Implementation Report

## Summary

Customers with an active qualification conversation can resend the English/Arabic
language picker using explicit change commands. After they select a new language,
only `WhatsAppConversationSession.language` and `language_selected_at` are
updated. Redis qualification progress (`accepted_fields`, conversation history)
is preserved and the flow continues from the current step.

## Files changed

| File | Change |
|---|---|
| `apps/qualification/domain/language_selection.py` | Added `LANGUAGE_CHANGE_COMMANDS`, `is_language_change_command()` |
| `apps/qualification/models.py` | Added `awaiting_language_reselection` boolean |
| `apps/qualification/migrations/0003_whatsappconversationsession_awaiting_language_reselection.py` | Schema migration |
| `apps/qualification/services/conversation_session_service.py` | `set_awaiting_language_reselection()`; clear flag on `persist_selected_language()` |
| `apps/qualification/services/language_gate_service.py` | Change-command routing; `build_language_change_continuation_response()` |
| `apps/qualification/tests/test_language_change_command.py` | End-to-end language-change tests |
| `apps/qualification/tests/test_language_selection_resolver.py` | Unit tests for change-command detection |
| `docs/integrations/n8n/LLM-5-django-qualification-endpoint.md` | Twilio field mapping + `awaiting_language_selection` IF branch |
| `docs/language-selection-routing-implementation-report.md` | Cross-reference to this report |

## Behavior

### Change commands recognized

```text
LANGUAGE
language
لغة
اللغة
تغيير اللغة
```

### Flow

```text
Customer sends change command (language already set)
        ↓
Django sends Twilio language picker
        ↓
Returns { "status": "awaiting_language_selection" }
        ↓
Customer taps lang_en / lang_ar (or typed English/Arabic while awaiting)
        ↓
Update session.language + language_selected_at only
        ↓
Return next qualification question in new language for current step
        ↓
Subsequent turns use normal OpenRouter / Deepgram routing
```

## Tests added

| Test | Coverage |
|---|---|
| `test_language_change_command_resends_selector_without_openrouter` | Command triggers picker; lead data unchanged |
| `test_english_to_arabic_change_preserves_lead_data_and_continues_current_step` | en → ar; `next_field` stays `referral_source` |
| `test_arabic_to_english_change_preserves_lead_data_and_continues_current_step` | ar → en; progress preserved |
| `test_after_language_change_normal_qualification_resumes_with_openrouter` | Next turn calls OpenRouter; prior fields kept |
| `test_typed_arabic_selection_after_change_command_without_button` | Typed `العربية` after change command |
| `test_language_change_commands_are_detected` | Resolver unit tests |

## Commands to run tests

```bash
# Focused
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
DJANGO_SETTINGS_MODULE=config.settings_test \
.venv/bin/python -m pytest -p pytest_django -q \
  apps/qualification/tests/test_language_change_command.py \
  apps/qualification/tests/test_language_selection_resolver.py \
  apps/qualification/tests/test_language_gate_routing.py

# Full suite
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
DJANGO_SETTINGS_MODULE=config.settings_test \
.venv/bin/python -m pytest -p pytest_django -q

# Apply migration (production/staging)
.venv/bin/python manage.py migrate
```

**Latest run:** 562 passed (full suite).

## n8n / Twilio audit

### Repository evidence

| Item | Status |
|---|---|
| Django webhook forwards raw Twilio fields | **Yes** — `apps/webhooks/views.py` → `forward_to_n8n(params)` |
| `TwilioInboundSerializer` maps ButtonPayload/media | **Yes** — `apps/webhooks/serializers.py` |
| Exported `twilio-whatsapp-inbound.json` | **Incomplete** — webhook + inspect only; no Django call or IF branch |
| `LLM-5-django-qualification-endpoint.md` | **Updated** in this change |
| `T3-11-whatsapp-text-voice-reply-routing.md` | Documents render-audio `fallback_to_text` (unchanged) |

### Twilio fields Django/n8n must forward

```text
ButtonPayload → button_payload
ButtonText    → button_text
ButtonType    → button_type
Body          → message
From          → whatsapp_number
MessageSid    → message_sid
MediaUrl0     → media_url
NumMedia      → (with MediaUrl0, sets voice channel)
```

### Required n8n branch (manual in n8n Cloud)

```text
Call Django Qualification API
        ↓
Language Selector Already Sent?
  condition: {{ $json.status === "awaiting_language_selection" }}
  ├── true  → Stop workflow
  └── false → Continue lead/reply workflow
```

When `true`, n8n must **not** update leads, send replies, or render audio.

### Still required manually in n8n Cloud

1. Extend **Normalize Twilio Message** to retain all fields above (not only `Body`/`From`).
2. Update **Call Django Qualification API** body per `LLM-5-django-qualification-endpoint.md`.
3. Add **Language Selector Already Sent?** IF node after the Django call.
4. Wire voice branch per `T3-11-whatsapp-text-voice-reply-routing.md` (`fallback_to_text`).
5. Re-export workflow JSON into the repository after validation (optional but recommended).

Cannot verify live n8n Cloud configuration from this repository alone.
