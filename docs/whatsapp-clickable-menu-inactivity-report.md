# WhatsApp clickable menu and inactivity trigger — implementation report

**Date:** 2026-07-02

## Summary

Extended the WhatsApp menu/restart flow so customers who have been idle for more than 10 minutes automatically receive a menu instead of continuing an old qualification turn. The menu supports plain-text numbered replies and optional Twilio Content Template clickable buttons. Text commands (`menu`, `/menu`, `start`, `/start`, `restart`, `/restart`) still work at any time.

## Inactivity behavior

| Condition | Behavior |
|-----------|----------|
| `last_message_at` is null | Active — first recorded turn, no auto-menu |
| Inbound within `WHATSAPP_MENU_INACTIVITY_SECONDS` | Normal qualification flow |
| Inbound after inactivity threshold | Show menu (clickable template or plain text) |
| Explicit `menu` / `restart` commands | Always honored before inactivity check |

`last_message_at` is updated on every processed turn (language gate, menu gate, inactivity menu, qualification). Idempotent `MessageSid` replays do not update activity.

## Menu pending state

| Field | Purpose |
|-------|---------|
| `menu_pending` | `true` while waiting for a menu choice |
| `menu_pending_until` | Expiry timestamp (`WHATSAPP_MENU_PENDING_SECONDS`, default 600s) |

While pending, numeric replies (`1`–`4`) and button payloads (`menu_*`) are interpreted as menu actions.

## Twilio Content Template payloads

Configure a Twilio Quick Reply / list template with these **button payload** values:

| Payload | Action |
|---------|--------|
| `menu_continue` | Resume qualification from next missing field |
| `menu_restart` | Clear qualification state, keep language/session |
| `menu_language` | Send existing language picker template |
| `menu_human` | `human_handoff_requested=true` |

Numeric fallback (plain-text menu):

| Reply | Action |
|-------|--------|
| `1` | Continue |
| `2` | Restart |
| `3` | Change language |
| `4` | Talk to human |

## Fallback behavior

| `TWILIO_MENU_CONTENT_SID` | Menu delivery | n8n response |
|---------------------------|---------------|--------------|
| Set | Django sends Twilio Content Template directly | `{"status":"awaiting_menu_selection","message":"Menu sent."}` — **stop workflow** (no duplicate reply) |
| Empty | Plain-text numbered menu in `reply_text` | Normal reply path via n8n |

Same stop pattern as `awaiting_language_selection` for the language picker.

## Env vars added

| Variable | Default | Purpose |
|----------|---------|---------|
| `WHATSAPP_MENU_INACTIVITY_SECONDS` | `600` | Idle time before auto-menu |
| `WHATSAPP_MENU_PENDING_SECONDS` | `600` | Menu choice window |
| `TWILIO_MENU_CONTENT_SID` | `""` | Optional clickable menu Content Template SID |

## Routing order (extract turn)

1. MessageSid idempotency
2. Language gate
3. Voice transcription (when needed)
4. WhatsApp menu gate (commands, pending numeric/button choices)
5. **Inactivity menu gate** (auto-show menu when idle)
6. Completed shortcut or normal qualification turn
7. Touch `last_message_at`

## Changed files

| File | Change |
|------|--------|
| `apps/qualification/migrations/0006_...py` | **New** — `last_message_at`, `menu_pending` |
| `apps/qualification/models.py` | `last_message_at`, `menu_pending` fields |
| `config/settings.py` | New env vars |
| `config/settings_test.py` | Test defaults |
| `.env.example` | Document new env vars |
| `apps/qualification/domain/menu_picker_pending.py` | `menu_pending` flag; `WHATSAPP_MENU_PENDING_SECONDS` |
| `apps/qualification/domain/session_inactivity.py` | **New** — inactivity threshold helper |
| `apps/qualification/domain/whatsapp_menu_commands.py` | `menu_*` button payload parsing |
| `apps/qualification/integrations/twilio_whatsapp_menu.py` | **New** — clickable menu send |
| `apps/qualification/services/conversation_session_service.py` | `touch_session_last_message_at()` |
| `apps/qualification/services/whatsapp_menu_service.py` | Inactivity gate, clickable menu, button payloads |
| `apps/qualification/services/extract_service.py` | Inactivity gate + activity tracking |
| `apps/qualification/api/views.py` | Pass-through `awaiting_menu_selection` |
| `apps/qualification/tests/test_whatsapp_clickable_menu_inactivity.py` | **New** — 11 tests |
| `apps/qualification/tests/test_whatsapp_menu_restart_flow.py` | Assert `menu_pending` flag |

## Tests run

```bash
python manage.py check
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 DJANGO_SETTINGS_MODULE=config.settings_test \
  .venv/bin/python -m pytest -p pytest_django.plugin -q
```

**Result:** 647 passed (11 new clickable menu/inactivity tests).

Coverage includes:

- Active user within 10 minutes continues normal flow
- Inactive user after 10 minutes gets menu
- Button payloads: `menu_restart`, `menu_continue`, `menu_language`, `menu_human`
- Numeric option `2` restarts
- Direct `/restart` restarts immediately
- Voice transcript after inactivity triggers menu
- Language preserved after restart
- Clickable template path returns `awaiting_menu_selection`

## Remaining risks

1. **n8n wiring** — Production workflow must stop on `status === "awaiting_menu_selection"` (same pattern as language picker).
2. **Twilio template** — `TWILIO_MENU_CONTENT_SID` must use the exact `menu_*` payloads above.
3. **Migration required** — Deploy must run `0006_whatsappconversationsession_inactivity_menu_pending`.
4. **First message** — No auto-menu until at least one prior turn sets `last_message_at`.
5. **Menu pending expiry** — Stale menus expire silently; customer must send `menu` again.
6. **Human handoff via menu** — API response flag only; no CRM integration in this change.
