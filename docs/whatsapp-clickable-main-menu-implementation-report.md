# WhatsApp clickable main menu (Twilio list-picker) — implementation report

**Date:** 2026-07-03

## Summary

Replaced the plain numbered `/menu` text fallback (when configured) with a Twilio **list-picker** Content Template send via `send_whatsapp_main_menu()`. List-picker `ButtonPayload` values are routed **before** the language gate and OpenRouter extraction. Typed numeric fallbacks (`1`–`4`) remain supported while `menu_pending` is active. Human handoff requests are now persisted on the WhatsApp session row.

## Files changed

| File | Change |
|------|--------|
| `config/settings.py` | Added `TWILIO_WHATSAPP_MENU_CONTENT_SID` (falls back to `TWILIO_MENU_CONTENT_SID`), `LEAD_QUALIFICATION_ENABLED` |
| `config/settings_test.py` | Test defaults for new settings |
| `.env.example` | Documented new env vars |
| `apps/qualification/integrations/twilio_whatsapp_menu.py` | `send_whatsapp_main_menu()`, `get_whatsapp_menu_content_sid()`, backward-compatible `send_whatsapp_menu()` alias |
| `apps/qualification/domain/whatsapp_menu_commands.py` | List-picker payloads, `resolve_menu_action()`, legacy payload aliases |
| `apps/qualification/domain/whatsapp_menu_logging.py` | **New** — structured menu log helper |
| `apps/qualification/domain/messages.py` | `menu_unknown_selection` copy (EN/AR) |
| `apps/qualification/models.py` | `human_handoff_requested_at` field |
| `apps/qualification/migrations/0007_...py` | **New** — handoff timestamp migration |
| `apps/qualification/services/conversation_session_service.py` | `mark_session_human_handoff_requested()` |
| `apps/qualification/services/whatsapp_menu_service.py` | Early button routing, structured logs, feature-flag guard, handoff persistence |
| `apps/qualification/services/extract_service.py` | Menu button gate before language gate; feature-flag guards |
| `conftest.py` | Disable early button gate for non-menu tests |
| `apps/qualification/tests/test_whatsapp_clickable_main_menu.py` | **New** — 11 integration tests |
| `apps/qualification/tests/test_twilio_whatsapp_main_menu_config.py` | **New** — Content SID unit tests |
| `apps/qualification/tests/test_whatsapp_menu_commands.py` | **New** — parser unit tests |
| `apps/qualification/tests/test_whatsapp_clickable_menu_inactivity.py` | Updated setting/patch names |
| `apps/qualification/tests/test_whatsapp_menu_restart_flow.py` | Added `LEAD_QUALIFICATION_ENABLED` to settings |

**Unchanged (already satisfied requirements):**

- `apps/webhooks/serializers.py` — already maps `MessageSid`, `From`, `Body`, `ButtonText`, `ButtonPayload`
- `apps/qualification/api/serializers.py` — already accepts `button_payload`, `button_text`, `button_type`

## Final request flow

```
Inbound extract turn
  1. MessageSid idempotency (replay → cached response, no duplicate restart/handoff)
  2. Early menu button gate (list-picker ButtonPayload → menu action)
  3. Language gate
  4. Voice transcription (when needed)
  5. Menu text gate (menu/restart commands, numeric 1–4 while menu_pending)
  6. Inactivity menu gate (auto-send list-picker when idle)
  7. Qualification turn (OpenRouter) OR completed shortcut
  8. Touch last_message_at
```

When `TWILIO_WHATSAPP_MENU_CONTENT_SID` is set, `/menu` and inactivity triggers call Twilio Content API directly and return:

```json
{"status": "awaiting_menu_selection", "message": "Menu sent."}
```

n8n must **stop** the workflow on this status (same pattern as `awaiting_language_selection`) so customers do not also receive the old plain numbered `reply_text`.

When the Content SID is **not** set, the existing plain-text numbered menu in `reply_text` is still returned for local/dev fallback.

## Twilio Console template configuration

Create a **WhatsApp** Content Template using type **`twilio/list-picker`** (not quick-reply — WhatsApp limits in-session quick replies to three buttons).

Configure **four list items** with these exact item IDs (`ButtonPayload` values):

| List item ID (`ButtonPayload`) | Action |
|-------------------------------|--------|
| `menu_continue` | Resume qualification from next missing field |
| `menu_restart` | Clear qualification state, keep language/session |
| `menu_change_language` | Send existing language picker template |
| `menu_human_handoff` | Human handoff + persist `human_handoff_requested_at` |

Copy the template **Content SID** (`HX…`) into `TWILIO_WHATSAPP_MENU_CONTENT_SID`.

**Legacy aliases still accepted:** `menu_language`, `menu_human`.

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `TWILIO_WHATSAPP_MENU_CONTENT_SID` | `""` (falls back to `TWILIO_MENU_CONTENT_SID`) | List-picker Content Template SID |
| `TWILIO_MENU_CONTENT_SID` | `""` | Deprecated alias; used when preferred name is unset |
| `LEAD_QUALIFICATION_ENABLED` | `true` | Master switch for menu/inactivity/extraction routing |
| `TWILIO_WHATSAPP_FROM_NUMBER` | `""` | Sender for Content API outbound messages |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | `""` | Twilio API credentials |
| `WHATSAPP_MENU_INACTIVITY_SECONDS` | `600` | Idle threshold before auto-menu |
| `WHATSAPP_MENU_PENDING_SECONDS` | `600` | Window for numeric `1`–`4` fallbacks |

## Payload-to-action mapping

| Input | Normalized action |
|-------|-------------------|
| `menu_continue` | `continue` |
| `menu_restart` | `restart` |
| `menu_change_language` / `menu_language` | `change_language` |
| `menu_human_handoff` / `menu_human` | `human_handoff` |
| `1` (while `menu_pending`) | `continue` |
| `2` (while `menu_pending`) | `restart` |
| `3` (while `menu_pending`) | `change_language` |
| `4` (while `menu_pending`) | `human_handoff` |
| `menu`, `/menu`, `start`, `/start` | Show main menu |
| `restart`, `/restart` | Immediate restart |

## Structured logs

| Event | When |
|-------|------|
| `whatsapp_menu_sent` | Content API send succeeded |
| `whatsapp_menu_selection_received` | Valid menu payload or numeric selection received |
| `whatsapp_menu_action_routed` | Action dispatched (continue/restart/language/human) |
| `whatsapp_menu_unknown_payload` | Unrecognized payload while menu pending |
| `whatsapp_menu_send_failed` | Twilio send or configuration failure |

All logs include `message_sid_prefix` (first 8 chars), `channel`, and `action` where applicable. No secrets, full phone numbers, or message bodies are logged.

## Test results

```bash
python manage.py check
# System check identified no issues (0 silenced).

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 DJANGO_SETTINGS_MODULE=config.settings_test \
  .venv/bin/python -m pytest -p pytest_django.plugin \
  apps/qualification/tests/test_whatsapp_clickable_main_menu.py \
  apps/qualification/tests/test_whatsapp_menu_commands.py \
  apps/qualification/tests/test_twilio_whatsapp_main_menu_config.py \
  apps/qualification/tests/test_whatsapp_clickable_menu_inactivity.py \
  apps/qualification/tests/test_whatsapp_menu_restart_flow.py -q
# 45 passed
```

Coverage includes:

- `/menu` sends Twilio Content SID (not plain text) when configured
- Each list-picker `ButtonPayload` routes correctly
- Numeric `1`–`4` fallbacks route correctly
- Unknown payload does not call OpenRouter
- Repeated `MessageSid` is idempotent for restart
- `LEAD_QUALIFICATION_ENABLED=false` skips menu and uses normal extraction
- Missing Content SID raises `TwilioWhatsAppMenuConfigurationError` on direct send

## Manual WhatsApp verification steps

1. Run migration `0007_whatsappconversationsession_human_handoff_requested_at`.
2. Set `TWILIO_WHATSAPP_MENU_CONTENT_SID`, `TWILIO_WHATSAPP_FROM_NUMBER`, Twilio credentials, and `LEAD_QUALIFICATION_ENABLED=true`.
3. Create/approve the list-picker template in Twilio Console with the four item IDs above.
4. Send `menu` from a test WhatsApp number after language is selected.
5. Confirm the list-picker appears (not a numbered text block).
6. Tap **Continue** — bot resumes at the next missing qualification field.
7. Send `menu` again → tap **Restart** — fields clear, language preserved.
8. Send `menu` → tap **Change language** — language picker template arrives.
9. Send `menu` → tap **Talk to human** — handoff acknowledgement; verify `human_handoff_requested_at` in DB.
10. Replay the same inbound webhook `MessageSid` — confirm no duplicate restart/handoff.
11. Confirm n8n stops on `status === "awaiting_menu_selection"`.

## Known WhatsApp limitations

1. **Quick-reply cap** — In-session quick-reply templates support at most **three** buttons; four options require a **list-picker** template.
2. **24-hour session window** — List-picker and Content API messages follow WhatsApp session rules; outside the window Twilio may require an approved template and an open customer care window.
3. **Template approval** — The list-picker Content Template must be approved by WhatsApp before production use.
4. **n8n stop signal required** — When Django sends the template directly, n8n must not also send `reply_text` or customers receive duplicate menus.
5. **Numeric fallback** — Typed `1`–`4` only work during the `menu_pending` window (`WHATSAPP_MENU_PENDING_SECONDS`); list-picker taps work via `ButtonPayload` without that window.
6. **Plain-text fallback** — When no Content SID is configured, the numbered text menu is still returned for development environments.
