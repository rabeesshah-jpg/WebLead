# Language Selection Routing Implementation Report

## Scope Completed

- **Serializer/request changes:** `TwilioInboundSerializer` (Twilio form fields) and optional `button_payload` / `button_text` / `button_type` on `ExtractRequestSerializer` (n8n → Django JSON).
- **Language resolver:** `resolve_selected_language()` with `LANGUAGE_BUTTONS` and `LANGUAGE_TEXT_FALLBACKS` in `domain/language_selection.py`.
- **Routing gate:** `LanguageGateService` integrated into `ExtractService.run_turn()` before transcription, OpenRouter, and qualification extraction.
- **Twilio selector behavior:** Reuses `send_language_picker()`; controlled 503 on missing Content SID; 502 on send failure; idempotent caching via existing `MessageSid` handling.
- **Tests:** Resolver, serializers, gate routing, and full regression suite (497 tests).

### Not implemented (by design at time of language-gate phase)

- Arabic OpenRouter prompts, Arabic reply text, Deepgram Arabic routing, translated qualification questions (since implemented in later phases).
- Twilio inbound webhook view changes (still forwards raw params to n8n; language gate runs on the internal extract API).

### Implemented in a later phase

- Mid-conversation language-change commands (`LANGUAGE`, `language`, `لغة`, `اللغة`, `تغيير اللغة`) — see `docs/language-change-command-implementation-report.md`.

## Actual Architecture Used

| Layer | Component |
|-------|-----------|
| Twilio inbound webhook | `apps/webhooks/views.py` → `twilio_whatsapp_inbound` (signature + n8n forward only) |
| Twilio inbound validation | `apps/webhooks/serializers.py` → `TwilioInboundSerializer` |
| Internal qualification API | `apps/qualification/api/views.py` → `ExtractAPIView` |
| Extract request validation | `apps/qualification/api/serializers.py` → `ExtractRequestSerializer` |
| Conversation/session model | `apps/qualification/models.py` → `WhatsAppConversationSession` |
| Session helpers | `apps/qualification/services/conversation_session_service.py` |
| Language gate | `apps/qualification/services/language_gate_service.py` |
| Turn orchestration | `apps/qualification/services/extract_service.py` |
| Twilio language picker | `apps/qualification/integrations/twilio_language_picker.py` |
| OpenRouter / Deepgram | `qualification_turn.py` / `transcription_service.py` (only after gate passes) |

**Source of truth:** Django ORM session `language` + `language_selected_at`. n8n must forward button fields but does not select language.

## Files Changed

| File | Purpose |
|------|---------|
| `apps/qualification/domain/language_selection.py` | `LANGUAGE_BUTTONS`, `LANGUAGE_TEXT_FALLBACKS`, `resolve_selected_language()` |
| `apps/qualification/domain/language.py` | Re-exports `LANGUAGE_BUTTONS` alias |
| `apps/qualification/services/language_gate_service.py` | Gate routing, awaiting response, local qual start |
| `apps/qualification/services/conversation_session_service.py` | `persist_selected_language()`, Redis lazy English backfill |
| `apps/qualification/services/extract_service.py` | Idempotency → language gate → expensive processing |
| `apps/qualification/api/serializers.py` | Optional button fields on extract payload |
| `apps/qualification/api/views.py` | Gate error handling; direct JSON for awaiting response |
| `apps/webhooks/serializers.py` | `TwilioInboundSerializer` + `to_extract_request_payload()` |
| `apps/qualification/tests/test_language_selection_resolver.py` | Resolver unit tests |
| `apps/qualification/tests/test_language_gate_routing.py` | End-to-end gate tests (`@pytest.mark.language_gate`) |
| `apps/webhooks/tests/test_twilio_inbound_serializers.py` | Twilio serializer tests |
| `apps/qualification/tests/test_extract_serializers.py` | Extract button-field + parity updates |
| `conftest.py` | Disable gate by default in regression tests; `@pytest.mark.language_gate` enables real gate |
| `pytest.ini` | `language_gate` marker registration |
| `config/sqlite_compat.py` | Improved pysqlite3 fallback for broken stdlib sqlite |

## Routing Order Implemented

1. **HTTP auth + serializer validation** (`ExtractAPIView.post`)
2. **`MessageSid` idempotency** (`begin_idempotent_turn`) — return cached response if duplicate
3. **Language gate** (`LanguageGateService.evaluate_turn`)
   - `get_or_create_conversation_session` (lazy `language=en` when Redis has qualification progress)
   - `resolve_selected_language(button_payload, message)`
   - **Explicit button** or **typed fallback** (only when `session.language is None`) → persist + `build_qualification_start_response` (first English question, no OpenRouter)
   - **`session.language is None`** → `send_language_picker` → `{"status": "awaiting_language_selection", "message": "Language selector sent."}`
   - **Else** → gate not handled; continue normal turn
4. **Existing flow:** voice transcription → `handle_qualification_turn` → OpenRouter → finalize → cache

Twilio webhook security/idempotency at the edge is unchanged (n8n still deduplicates `MessageSid` before calling Django).

## Language Resolution Rules

| Priority | Rule |
|----------|------|
| 1 | Exact `button_payload` in `LANGUAGE_BUTTONS` (`lang_en` / `lang_ar`) |
| 2 | Else exact trimmed `body` in `LANGUAGE_TEXT_FALLBACKS` (case-insensitive for ASCII) |
| 3 | Else `None` — not a language selection |

**Typed fallback constraints:** Applied only when `session.language is None`. Active conversations ignore typed `English` / `العربية` and continue normal qualification.

**Button payload:** Always authoritative over conflicting `Body`.

## External Calls Prevented Before Language Selection

When `session.language is None` and no valid selection is resolved:

- OpenRouter (`extract_qualification_from_openrouter`)
- Deepgram / voice transcription (`VoiceNoteTranscriptionService.transcribe`)
- Twilio media download on the transcription path
- Qualification field extraction / LLM prompts

## Idempotency and Failure Handling

| Scenario | Behavior |
|----------|----------|
| Duplicate `MessageSid` | Cached response returned; no second picker send, no double language save |
| Missing `TWILIO_LANGUAGE_PICKER_CONTENT_SID` | 503 `Qualification service is unavailable.`; language stays `NULL` |
| Twilio send failure | 502 `Qualification service request failed.`; language stays `NULL`; logged `language_selector_send_failed` |
| Successful picker send | Response cached under `MessageSid` |

## Tests and Results

```bash
.venv/bin/python manage.py makemigrations --check --dry-run
# No changes detected

DJANGO_SETTINGS_MODULE=config.settings_test PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  .venv/bin/python -m pytest -p django -p pytest_django \
  apps/qualification/tests/test_language_selection_resolver.py \
  apps/qualification/tests/test_language_gate_routing.py \
  apps/webhooks/tests/test_twilio_inbound_serializers.py \
  apps/qualification/tests/test_extract_serializers.py

DJANGO_SETTINGS_MODULE=config.settings_test PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  .venv/bin/python -m pytest -p django -p pytest_django \
  apps/qualification/tests/ apps/webhooks/tests/
```

| Command | Result |
|---------|--------|
| `makemigrations --check` | No changes detected |
| Focused language/serializer tests | Included in full run |
| Full `apps/qualification/tests/` + `apps/webhooks/tests/` | **497 passed** |

**Note:** Use `.venv/bin/python` for tests in this environment; system pyenv Python has a broken stdlib `sqlite3` (mitigated via `pysqlite3-binary` when the venv is used).

Regression tests disable the language gate via `conftest.py` unless `@pytest.mark.language_gate` is set.

## Assumptions and Remaining Work

1. **n8n must forward** `button_payload`, `button_text`, and `button_type` (mapped from Twilio `ButtonPayload`, `ButtonText`, `ButtonType`) in the JSON body to `/api/internal/qualification/extract/`. `TwilioInboundSerializer.to_extract_request_payload()` documents the mapping.
2. **Arabic qualification content** still uses English `QUESTIONS` until a later phase.
3. **Arabic OpenRouter prompt** and **Deepgram Arabic model** routing not started.
4. **Language change command** for mid-conversation switching not added (button payload can still override language when implemented in UX).
5. **Twilio webhook** unchanged; language gate is on the internal extract endpoint n8n calls after deduplication.
