# WhatsApp menu and restart flow — implementation report

**Date:** 2026-06-30

## Summary

Added a WhatsApp menu and restart flow so customers can reset an in-flight qualification conversation without losing their language preference. The flow runs through the existing `POST /api/internal/qualification/extract/` endpoint for both text and voice-note messages.

## Commands supported

| Input | Behavior |
|-------|----------|
| `menu`, `/menu`, `start`, `/start` | Show numbered menu (sets 15-minute menu-pending window) |
| `restart`, `/restart` | Restart immediately (skip menu) |
| `1` (while menu pending) | Continue current conversation |
| `2` (while menu pending) | Restart qualification |
| `3` (while menu pending) | Send Twilio language picker |
| `4` (while menu pending) | Human handoff (`human_handoff_requested=true`) |

Numeric replies are only interpreted while `menu_pending_until` is active on the WhatsApp session row.

## Reset behavior

`restart_qualification_conversation()` clears per-customer state only:

- `accepted_fields` (Redis/in-memory)
- Conversation turn history
- `menu_pending_until` and `language_picker_pending_until` on the session

**Preserved:**

- `WhatsAppConversationSession` row
- Selected `language` on the session
- Prior `MessageSid` idempotency cache entries (safe replay of old inbound messages unchanged)

**Not stored separately** (no extra clear needed):

- `rejected_fields` — computed per turn from OpenRouter, not persisted
- Clarification attempts — no separate store; restart clears history used for prompt context

After restart:

- `qualification_status` → `in_progress`
- `next_field` → `project_type`
- `accepted_fields` → `{}`
- Reply uses localized `restart_intro` message (EN/AR)

## Routing order (extract turn)

1. MessageSid idempotency
2. Language gate (`/language`, picker, pending body fallback)
3. Resolve message (transcribe voice notes when needed)
4. **WhatsApp menu gate** (commands + pending numeric options)
5. Completed-conversation shortcut or normal qualification turn

Voice notes transcribe **before** the completed shortcut so a spoken “restart” still resets a finished conversation.

## Changed files

| File | Change |
|------|--------|
| `apps/qualification/domain/whatsapp_menu_commands.py` | **New** — command/option parsing |
| `apps/qualification/domain/menu_picker_pending.py` | **New** — menu pending state |
| `apps/qualification/domain/messages.py` | `whatsapp_menu`, `restart_intro` (EN/AR) |
| `apps/qualification/models.py` | `menu_pending_until` field |
| `apps/qualification/migrations/0005_..._menu_pending_until.py` | **New** migration |
| `apps/qualification/conversation_state.py` | `clear_conversation_for_customer()` |
| `apps/qualification/persistence/backends.py` | Per-customer clear (memory + Redis) |
| `apps/qualification/services/conversation_restart_service.py` | **New** — restart orchestration |
| `apps/qualification/services/whatsapp_menu_service.py` | **New** — menu/restart/handoff routing |
| `apps/qualification/services/extract_service.py` | Menu gate + voice transcription order |
| `apps/qualification/tests/test_whatsapp_menu_restart_flow.py` | **New** — 8 integration tests |

## Tests run

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
DJANGO_SETTINGS_MODULE=config.settings_test \
.venv/bin/python -m pytest -p pytest_django.plugin -q
```

**Result:** `636 passed` (8 new menu/restart tests).

Coverage includes:

- Menu command returns menu
- `/restart` and menu option `2` clear state
- Language preserved after restart
- `next_field` becomes `project_type`
- Voice-note transcript `"restart"` triggers restart
- Menu option `3` sends language picker
- Menu option `4` triggers human handoff
- Normal qualification still works

## Remaining risks

1. **Numeric `1`–`4` outside menu** — Only honored while menu is pending; a bare `1` during qualification is not treated as menu input.
2. **Completed + non-restart message** — After qualification completes, non-menu messages still get the completion retry reply (unchanged).
3. **Migration required** — Deploy must run `0005_whatsappconversationsession_menu_pending_until`.
4. **Menu pending timeout** — Reuses `LANGUAGE_PICKER_PENDING_TIMEOUT_SECONDS` (default 900s); stale menus expire silently.
5. **Human handoff via menu** — Sets handoff flags in the API response only; no outbound CRM integration in this change.
