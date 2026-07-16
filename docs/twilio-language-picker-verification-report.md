# Twilio Language Picker Verification Report

**Date:** 2026-06-30
**Scope:** Backend/env/config for live WhatsApp language selection. Twilio Console Content Template approval and live delivery cannot be verified from repository code alone.

## Backend configuration (code + environment)

| Setting | Expected format | Local `.env` status | Loaded by Django |
|---|---|---|---|
| `TWILIO_LANGUAGE_PICKER_CONTENT_SID` | Twilio Content SID, `HX…` (typically 34 chars) | **SET** — HX-prefixed, length 34 | `config/settings.py` → `send_language_picker()` `content_sid=` |
| `TWILIO_WHATSAPP_FROM_NUMBER` | Approved WhatsApp sender, `whatsapp:+E164` | **SET** — `whatsapp:` prefix present | `config/settings.py` → `messages.create(from_=…)` |
| `TWILIO_ACCOUNT_SID` | `AC…` | **SET** | Required for Content API send |
| `TWILIO_AUTH_TOKEN` | Secret token | **SET** | Required for Content API send |

**Code path:** `apps/qualification/integrations/twilio_language_picker.py` → `send_language_picker()`
**Invoked by:** `LanguageGateService` when `session.language is None` (new customer) or on language-change commands.

**`.env.example` gap:** `TWILIO_LANGUAGE_PICKER_CONTENT_SID` is documented; `TWILIO_WHATSAPP_FROM_NUMBER` is **not** listed in `.env.example` (required at runtime when picker send is enabled).

**Automated tests:** `apps/qualification/tests/test_twilio_language_picker_config.py` — **4 passed** (mocked Twilio client; confirms `content_sid` and `from_` wiring).

## Expected Django button payload contract

Django resolves inbound Quick Reply selections in `apps/qualification/domain/language_selection.py`:

| Button label (Twilio Content UI) | Required `ButtonPayload` | Persisted language |
|---|---|---|
| English | `lang_en` | `en` |
| العربية | `lang_ar` | `ar` |

**Rules enforced in code:**
- `ButtonPayload` is authoritative over conflicting `Body` text.
- Typed fallbacks (`English`, `العربية`, etc.) apply only when no valid button payload is present and language is unset or awaiting reselection.

**If Twilio Console payloads differ** (e.g. `Lang_EN`, `english`, empty payload), Django will not persist language from the button tap and the customer may remain on the selector path or fall through incorrectly.

## What cannot be verified from code

The following require **Twilio Console** and/or a **real WhatsApp device**:

- Content Template exists and is **approved** for WhatsApp.
- Template SID in Console matches `TWILIO_LANGUAGE_PICKER_CONTENT_SID` in deployment `.env`.
- Quick Reply button payloads exactly match `lang_en` / `lang_ar`.
- Sender number in Console matches `TWILIO_WHATSAPP_FROM_NUMBER`.
- Template language/category fits WhatsApp policy.
- Live message delivery to a new customer number.

No Twilio Content API lookup was run during this verification (would require live credentials and is out of repository scope).

## Manual Twilio Console checks (required)

1. Open [Twilio Console](https://console.twilio.com/) → **Messaging** → **Content Template Builder** (or Content Editor).
2. Find the template whose **Content SID** equals deployment `TWILIO_LANGUAGE_PICKER_CONTENT_SID` (`HX…`).
3. Confirm template **WhatsApp approval status** is approved (not draft/rejected).
4. Open the template actions / Quick Reply configuration and verify:
   - Button **English** → payload **`lang_en`**
   - Button **العربية** → payload **`lang_ar`**
5. Confirm the **WhatsApp sender** configured for outbound messages matches `TWILIO_WHATSAPP_FROM_NUMBER` (including `whatsapp:` prefix in Django `.env`).
6. Confirm `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` in deployment `.env` belong to the same Twilio project as the Content Template.

## Real WhatsApp test checklist

Use a **new customer number** with no existing `WhatsAppConversationSession` row (or delete test session in Django admin/DB before test).

| Step | Action | Pass criteria |
|---|---|---|
| 1 | Send any first inbound text (e.g. `hello`) from new WhatsApp number | Customer receives Twilio Content message with **English** and **العربية** buttons |
| 2 | Do **not** send a second bot reply from n8n for this turn | n8n stops when Django returns `"status": "awaiting_language_selection"` |
| 3 | Tap **English** | Django persists `language=en`; first English qualification question arrives |
| 4 | Repeat with new number; tap **العربية** | Django persists `language=ar`; first Arabic qualification question arrives |
| 5 | Check Django logs | Events `language_selector_sent` then `language_selection_accepted` |
| 6 | Optional: send `LANGUAGE` mid-conversation | Picker resent; lead fields unchanged after reselection |

**Failure signals:**
- HTTP **503** on extract → missing/invalid `TWILIO_LANGUAGE_PICKER_CONTENT_SID` or related Twilio config.
- HTTP **502** on extract → Twilio Content send failed (check sender, template approval, credentials).
- Buttons appear but wrong language after tap → **payload mismatch** in Content Template.

## Summary

| Area | Status |
|---|---|
| Backend env vars present (local) | **PASS** — SID and sender set with expected formats |
| Backend code wiring | **PASS** — Content API uses env SID + sender; payloads `lang_en`/`lang_ar` in resolver |
| Twilio Console template payloads | **NOT VERIFIED** — manual check required |
| Live WhatsApp end-to-end | **NOT VERIFIED** — manual test checklist above |
