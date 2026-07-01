# Language Picker Safe Body Fallback Report

## Problem
- Live Twilio webhook provides visible Body values but does not provide ButtonPayload.

## Safe Behavior Implemented
- Pending picker expiry state (`language_picker_pending_until`, 15 minutes)
- Exact Body matching only (`English`, `العربية` after whitespace normalization)
- No substring matching
- Explicit `/language` and `/language set …` commands work with or without pending state
- ButtonPayload (`lang_en`, `lang_ar`) remains highest priority over Body
- Pending state cleared on valid language selection or explicit `/language set`
- Pending state not set when Twilio picker send fails
- Expired pending state ignored safely

## Customer Examples
| Customer input | Picker pending? | Expected language result |
|---|---:|---|
| `/language` | N/A | Picker sent; pending until expires |
| `English` | Yes | Set English |
| `العربية` | Yes | Set Arabic |
| `I need an English website` | Yes/No | No language change |
| `/language set en` | Yes/No | Set English |
| `/language set ar` | Yes/No | Set Arabic |

## Data Preservation
- **Fields preserved:** `project_type`, `requirements`, `referral_source`, `whatsapp_confirmed`, `preferred_phone`, `qualification_status`, lead ID, lead table record, current qualification step, accepted fields, Redis/in-memory qualification state
- **Fields changed on selection:** `language`, `language_selected_at`, `language_picker_pending_until` (cleared)
- **Fields changed on `/language` only:** `language_picker_pending_until` (saved language unchanged)

## Files Changed
| File | Purpose |
|---|---|
| `apps/qualification/models.py` | Added `language_picker_pending_until` field |
| `apps/qualification/migrations/0004_whatsappconversationsession_language_picker_pending_until.py` | Database migration |
| `apps/qualification/domain/language_picker_pending.py` | Pending state helpers and exact body resolver |
| `apps/qualification/domain/language_selection.py` | ButtonPayload-only resolution in `resolve_selected_language()` |
| `apps/qualification/services/conversation_session_service.py` | `mark_session_language_picker_pending()`, clear pending on `persist_selected_language()` |
| `apps/qualification/services/language_gate_service.py` | Processing priority: commands → ButtonPayload → pending body → null gate |
| `config/settings.py` | `LANGUAGE_PICKER_PENDING_TIMEOUT_SECONDS` (default 900) |
| `apps/qualification/tests/test_language_picker_safe_body_fallback.py` | 25 focused tests for pending picker and safe fallback |
| `apps/qualification/tests/test_language_gate_routing.py` | Updated two-step new-customer body selection test |
| `apps/qualification/tests/test_language_change_command.py` | Assertions use `language_picker_pending_until` |
| `apps/qualification/tests/test_language_selection_resolver.py` | Body no longer resolved without ButtonPayload |

## Migration
- **Migration filename:** `0004_whatsappconversationsession_language_picker_pending_until.py`
- **New field:** `language_picker_pending_until` (`DateTimeField`, nullable, indexed)

## Tests Run
| Command | Result |
|---|---|
| `.venv/bin/python manage.py makemigrations --check --dry-run` | No changes detected |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 DJANGO_SETTINGS_MODULE=config.settings_test .venv/bin/python -m pytest -p pytest_django -q` | 593 passed |

## n8n Impact
- No new n8n logic required.
- n8n must forward Body, From, and MessageSid unchanged.
- Existing `awaiting_language_selection` stop branch remains required.
