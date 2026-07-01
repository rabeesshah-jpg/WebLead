# Language Change Commands Report

## Commands Supported

| Command | Action |
|---|---|
| `/language` | Re-open Twilio English / العربية picker |
| `/language set en` | Set English directly |
| `/language set english` | Set English directly (case-insensitive) |
| `/language set ar` | Set Arabic directly |
| `/language set arabic` | Set Arabic directly (case-insensitive) |
| `/language set العربية` | Set Arabic directly |

Legacy plain-text commands (`LANGUAGE`, `language`, `لغة`, etc.) are **not** supported. Only exact slash commands match.

## Processing Order

Within `ExtractService.run_turn()`:

1. Validate inbound request (`ExtractRequestSerializer`)
2. MessageSid idempotency (`begin_idempotent_turn`)
3. Load/create `WhatsAppConversationSession` (`LanguageGateService`)
4. **Parse explicit `/language` command** (`parse_language_command`)
5. Process Twilio `ButtonPayload` selection
6. Initial language-selector gate when `language IS NULL`
7. Media download / Deepgram / OpenRouter / qualification logic

Commands run before Deepgram, OpenRouter, and field extraction.

## Data Preservation

**Unchanged on language change:**

- `project_type`, `requirements`, `referral_source`, `whatsapp_confirmed`, `preferred_phone`
- Redis/in-memory qualification state and conversation history
- Qualification status and current step (`next_field` derived from existing progress)
- Lead identity (no duplicate lead creation)

**Updated only:**

- `WhatsAppConversationSession.language`
- `WhatsAppConversationSession.language_selected_at`
- `awaiting_language_reselection` (set `true` after `/language` until button selection)

## API Responses

### `/language` (picker)

```json
{
  "status": "awaiting_language_selection",
  "message": "Language selector sent.",
  "language_command_action": "picker_sent"
}
```

Saved conversation language is unchanged until the customer taps a Quick Reply button.

### `/language set en` or `/language set ar` (direct)

Normal qualification response with additive field:

```json
{
  "accepted_fields": { "...": "..." },
  "rejected_fields": {},
  "human_handoff_requested": false,
  "next_field": "referral_source",
  "reply_text": "...",
  "qualification_status": "in_progress",
  "conversation_language": "en",
  "reply_mode": "text",
  "send_booking_link": false,
  "booking_link": null,
  "language_command_action": "language_changed"
}
```

Uses `build_language_change_continuation_response()` — next missing question in the selected language, no OpenRouter call.

## n8n Behavior

- `/language` → Django returns `awaiting_language_selection` → **Language Selector Already Sent?** IF node stops workflow (no lead update, no reply, no render-audio).
- `/language set ...` → normal qualification JSON → n8n continues reply handling.

`language_command_action` is optional and backward-compatible; n8n should continue to branch on `status` for picker flows.

## Tests Run

```bash
.venv/bin/python manage.py makemigrations --check --dry-run
# No changes detected

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
DJANGO_SETTINGS_MODULE=config.settings_test \
.venv/bin/python -m pytest -p pytest_django -q
# 576 passed
```

Focused:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
DJANGO_SETTINGS_MODULE=config.settings_test \
.venv/bin/python -m pytest -p pytest_django -q \
  apps/qualification/tests/test_language_commands_parser.py \
  apps/qualification/tests/test_language_change_command.py \
  apps/qualification/tests/test_language_gate_routing.py
```

## Files Changed

| File | Purpose |
|---|---|
| `apps/qualification/domain/language_commands.py` | `LanguageCommand`, `parse_language_command()` |
| `apps/qualification/domain/language_selection.py` | Removed legacy plain-text change commands |
| `apps/qualification/services/language_gate_service.py` | Command handling before button/gate; continuation responses |
| `apps/qualification/api/serializers.py` | Optional `language_command_action` on extract response |
| `apps/qualification/tests/test_language_commands_parser.py` | Parser unit tests |
| `apps/qualification/tests/test_language_change_command.py` | End-to-end slash-command flow tests |
| `apps/qualification/tests/test_language_selection_resolver.py` | Removed legacy command tests |

## Manual n8n Changes

No new n8n branch required. Existing **Language Selector Already Sent?** on `status === awaiting_language_selection` covers `/language`. Direct set commands use the normal reply path.

Ensure n8n forwards full Twilio fields (`ButtonPayload`, etc.) per `docs/integrations/n8n/LLM-5-django-qualification-endpoint.md`.
