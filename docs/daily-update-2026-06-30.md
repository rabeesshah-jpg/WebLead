# Daily Update — 30 June 2026

**Project:** WebLead — Twilio WhatsApp lead qualification (Arabic/English)

---

## Completed today

### Audits
- **Arabic Supertonic TTS audit** — Backend routing, text fallback (HTTP 200), and idempotency verified; **576 tests passing**. Arabic TTS remains disabled pending voice config and manual listening. Report: `docs/arabic-supertonic-tts-audit-report.md`
- **Arabic language support (full journey) audit** — Persisted language, language gate, bilingual messages, OpenRouter/Deepgram/TTS covered; gaps flagged (Arabic/Persian phone digits, n8n workflow not in repo). Report: `docs/arabic-language-support-complete-audit.md`
- **Twilio language-picker verification** — Local env has `TWILIO_LANGUAGE_PICKER_CONTENT_SID` (HX…) and `TWILIO_WHATSAPP_FROM_NUMBER` configured; Console/live WhatsApp checks documented as manual. Report: `docs/twilio-language-picker-verification-report.md`

### Implementation
- **Explicit `/language` slash commands** — Strict parser and gate integration:
  - `/language` → re-send Twilio picker, `awaiting_language_selection`, no lead reset
  - `/language set en|english` / `/language set ar|arabic|العربية` → update session language only, return next question in chosen language without OpenRouter
  - Button tap after `/language` preserves qualification progress
  - Additive API field: `language_command_action` (`picker_sent` / `language_changed`)
  - Report: `docs/language-change-commands-report.md`

### Validation
- Ran `makemigrations --check --dry-run` — no pending migrations (after language-command work)
- Full pytest suite: **576 passed**
- Arabic Supertonic verification command tested locally with inline `SUPERTONIC_ARABIC_VOICE=M1` — sample WAV/OGG generated; manual listening still required before production enablement

---

## In progress / not done

| Item | Status |
|---|---|
| Arabic/Persian phone-digit normalization | Not implemented |
| n8n Cloud workflow (language gate IF, button forwarding, TTS fallback) | Documented; not evidenced in exported JSON |
| Twilio Console Content Template payload verification (`lang_en` / `lang_ar`) | Manual check required |
| Live WhatsApp E2E test (new customer → picker → qual) | Manual check required |
| Arabic TTS production enablement | Disabled; `SUPERTONIC_ARABIC_VOICE` not in `.env` |

---

## Blockers / risks

1. **n8n** — `twilio-whatsapp-inbound.json` is inbound-only; production must stop on `awaiting_language_selection` and forward `ButtonPayload` to Django.
2. **Phone digits** — Eastern Arabic/Persian digits fail E.164 validation; may cause repeat phone prompts for Arabic users.
3. **Arabic TTS** — Do not set `SUPERTONIC_ARABIC_ENABLED=true` until voice is configured and manually approved.

---

## Tomorrow / next steps

1. Manual Twilio Console check: Content SID, button payloads, sender number.
2. Live WhatsApp test with a new customer number (picker → English/Arabic → first question).
3. Wire n8n **Language Selector Already Sent?** branch if not already in Cloud.
4. Implement Arabic/Persian digit normalization (if prioritized).
5. Optional: add `TWILIO_WHATSAPP_FROM_NUMBER` to `.env.example`.

---

## Test command reference

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
DJANGO_SETTINGS_MODULE=config.settings_test \
.venv/bin/python -m pytest -p pytest_django -q
```
const djangoNodeOutput =
  $('Call Django Qualification API').first().json;