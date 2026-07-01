# Arabic Language Foundation Implementation Report

## Scope Completed

- Added optional `TWILIO_LANGUAGE_PICKER_CONTENT_SID` (and internal `TWILIO_WHATSAPP_FROM_NUMBER` for future outbound send) to Django settings and `.env.example`.
- Introduced SQLite-backed Django ORM persistence for WhatsApp session metadata via `WhatsAppConversationSession`.
- Added nullable `language` and `language_selected_at` fields with a safe data migration that backfills only `NULL` rows to `"en"`.
- Added shared language constants (`LANGUAGE_BUTTON_PAYLOADS`, `SUPPORTED_CONVERSATION_LANGUAGES`) in `apps/qualification/domain/language.py`.
- Added optional Twilio inbound payload parser for `ButtonPayload` / `ButtonText` (not wired into the webhook view).
- Added `send_language_picker()` Twilio Content API helper (not invoked from inbound flow).
- Added `pysqlite3-binary` fallback shim for environments with a broken stdlib `sqlite3` module.
- Added tests and ran the full qualification + webhooks test suites.

### Intentionally Not Implemented

- Arabic qualification prompts, response templates, or Deepgram language routing.
- n8n workflow changes.
- Language-selection business logic in the Twilio inbound webhook or qualification turn handler.
- Wiring `send_language_picker()` into any inbound or outbound flow.
- Syncing Redis/in-memory qualification state (`accepted_fields`) with the new ORM session table.
- Arabic TTS or render-audio language defaults beyond existing unrelated `lang` field on TTS.

## Existing Model Selected

| Item | Value |
|------|-------|
| **Model** | `WhatsAppConversationSession` |
| **App** | `apps.qualification` |
| **Table** | `qualification_whatsapp_conversation_session` |

### Why This Model

The project had **no Django ORM conversation model** and `DATABASES = {}` before this task. Qualification conversation state (accepted fields, idempotency) lives in **Redis or in-memory** backends keyed by WhatsApp number (`qualification:conversation:{whatsapp_number}`).

`WhatsAppConversationSession` is a new, focused ORM table for **persistent per-customer metadata** (language selection) without duplicating the Redis qualification payload or changing the stateless extract/turn APIs. It is the natural place to store `language` and `language_selected_at` until the webhook layer is extended in a later phase.

**Important:** Active customers whose state exists only in Redis do **not** automatically receive an ORM row from this migration. A future phase should create or backfill ORM rows on first contact and set `language="en"` when Redis shows an in-progress English qualification.

## Files Changed

| File | Purpose |
|------|---------|
| `apps/qualification/models.py` | Added `WhatsAppConversationSession` ORM model with `Language` choices |
| `apps/qualification/migrations/0001_initial_whatsapp_conversation_session.py` | Schema migration |
| `apps/qualification/migrations/0002_backfill_conversation_language_en.py` | Data migration (`NULL` → `"en"`) |
| `apps/qualification/domain/language.py` | `LANGUAGE_BUTTON_PAYLOADS`, `SUPPORTED_CONVERSATION_LANGUAGES` |
| `apps/qualification/services/conversation_session_service.py` | Create/get-or-create helpers (not wired to webhook) |
| `apps/qualification/integrations/twilio_language_picker.py` | `send_language_picker()` helper |
| `apps/webhooks/twilio_inbound_payload.py` | Optional `ButtonPayload` / `ButtonText` parser |
| `config/settings.py` | SQLite `DATABASES`, Twilio language-picker settings |
| `config/settings_test.py` | In-memory SQLite for tests |
| `config/sqlite_compat.py` | `pysqlite3` fallback for broken stdlib sqlite |
| `config/wsgi.py`, `manage.py`, `conftest.py` | Early sqlite compat import |
| `.env.example` | `TWILIO_LANGUAGE_PICKER_CONTENT_SID` with comment |
| `.gitignore` | Ignore `data/` SQLite directory |
| `requirements.txt` | `pysqlite3-binary` |
| `apps/qualification/tests/test_conversation_language_foundation.py` | Model, migration, constants, parser tests |
| `apps/qualification/tests/test_twilio_language_picker_config.py` | Settings and helper configuration tests |

## Database Migration

| Item | Detail |
|------|--------|
| **Initial migration** | `0001_initial_whatsapp_conversation_session` |
| **Data migration** | `0002_backfill_conversation_language_en` |
| **Fields added** | `whatsapp_number`, `language`, `language_selected_at` |

### Data Migration Behavior

Forward (`backfill_language_en`):

```python
WhatsAppConversationSession.objects.filter(language__isnull=True).update(language="en")
```

- Only rows with `language IS NULL` are updated.
- Rows that already have `"en"` or `"ar"` are never overwritten.

Reverse (`reverse_backfill_language_en`):

- Sets `language=NULL` only where `language="en"` **and** `language_selected_at IS NULL`.
- Rows with a user-selected timestamp are preserved.

### Why New Records Remain `language=NULL`

- No model-level `default="en"`.
- `create_conversation_session()` and `get_or_create_conversation_session()` explicitly default `language` to `None`.
- The data migration runs once at deploy; it does not affect inserts after migration.
- Future new customers with `language IS NULL` can be shown the Twilio language picker.

### Old Records Protected

- Pre-existing ORM rows with a non-null language are skipped by the `language__isnull=True` filter.
- Reverse migration avoids clearing rows that have `language_selected_at` set.

## Configuration

| Setting | Source |
|---------|--------|
| `TWILIO_LANGUAGE_PICKER_CONTENT_SID` | `.env` / `env("TWILIO_LANGUAGE_PICKER_CONTENT_SID", default="")` |
| `TWILIO_WHATSAPP_FROM_NUMBER` | Internal; required only when `send_language_picker()` is called |

**Location:** `config/settings.py` (after `TWILIO_ACCOUNT_SID`).

**When Content SID is empty:**

- Django starts normally.
- Existing English WhatsApp flow is unchanged.
- `send_language_picker()` raises `TwilioLanguagePickerConfigurationError`.

**Database:** `BASE_DIR / "data" / "qualification.sqlite3"` (SQLite). Tests use `:memory:`.

## Twilio Integration Readiness

| Item | Detail |
|------|--------|
| **Helper added** | Yes — `apps/qualification/integrations/twilio_language_picker.py` |
| **Future trigger point** | Twilio inbound webhook (`apps/webhooks/views.py`) or n8n pre-qualification step, when `WhatsAppConversationSession.language IS NULL` for a new customer |
| **Missing config behavior** | Raises `TwilioLanguagePickerConfigurationError` with a specific message (missing SID, credentials, or `TWILIO_WHATSAPP_FROM_NUMBER`) |

The helper uses the Twilio REST SDK (`content_sid` on `messages.create`). It is **not** called anywhere in the current codebase.

## Future Button Payload Support

**Constants** (`apps/qualification/domain/language.py`):

```python
LANGUAGE_BUTTON_PAYLOADS = {"lang_en": "en", "lang_ar": "ar"}
SUPPORTED_CONVERSATION_LANGUAGES = frozenset({"en", "ar"})
```

**Optional inbound fields** (`apps/webhooks/twilio_inbound_payload.py`):

- `ButtonPayload` → `TwilioInboundPayload.button_payload`
- `ButtonText` → `TwilioInboundPayload.button_text`

The webhook view still forwards the raw param dict to n8n unchanged. No language-selection logic runs yet.

## Tests

### Added / Updated

- `apps/qualification/tests/test_conversation_language_foundation.py`
- `apps/qualification/tests/test_twilio_language_picker_config.py`

### Commands Executed

```bash
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py migrate --noinput

DJANGO_SETTINGS_MODULE=config.settings_test PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  python -m pytest -p django -p pytest_django \
  apps/qualification/tests/test_conversation_language_foundation.py \
  apps/qualification/tests/test_twilio_language_picker_config.py \
  apps/webhooks/tests/test_twilio_whatsapp_inbound.py \
  apps/qualification/tests/test_persistence.py

DJANGO_SETTINGS_MODULE=config.settings_test PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  python -m pytest -p django -p pytest_django \
  apps/qualification/tests/ apps/webhooks/tests/
```

### Actual Results

| Command | Result |
|---------|--------|
| `makemigrations --check` | `No changes detected` |
| `migrate --plan` | Shows `0001` + `0002` as expected |
| `migrate --noinput` | Both migrations applied OK |
| Targeted regression tests | **34 passed** |
| Full `apps/qualification/tests/` + `apps/webhooks/tests/` | **457 passed** |

No project-wide linter configuration was found; lint was not run.

## Manual Twilio Console Setup Required

1. Open Twilio Console.
2. Go to **Messaging → Content Template Builder**.
3. Create **Quick Reply** content.
4. Message body:

   ```text
   Welcome! Please select your preferred language.

   مرحبًا بك! يرجى اختيار اللغة المفضلة لديك.
   ```

5. Add button **English** with payload `lang_en`.
6. Add button **العربية** with payload `lang_ar`.
7. Copy the generated Content SID.
8. Add to `.env`:

   ```env
   TWILIO_LANGUAGE_PICKER_CONTENT_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

9. When enabling outbound send, also set `TWILIO_WHATSAPP_FROM_NUMBER` to your approved WhatsApp sender (e.g. `whatsapp:+15557654321`).

## Assumptions and Limitations

- **Redis vs ORM:** Existing in-flight English qualifications in Redis are unaffected and have no ORM row until a future sync step creates one. The data migration only affects rows present in SQLite at deploy time (initially none).
- **SQLite:** Chosen as the first database backend because the project previously had no DB. Production may later switch to PostgreSQL via settings without changing the model.
- **`pysqlite3-binary`:** Added because the local pyenv Python had a broken stdlib `_sqlite3` (`sqlite3_deserialize` symbol error). On hosts with a working stdlib sqlite, the shim is a no-op.
- **`TWILIO_WHATSAPP_FROM_NUMBER`:** Not in `.env.example` yet; documented here for when outbound picker send is wired.
- **Not verified in live Twilio:** Content API send against a real Content SID was only tested with mocks.

### Next Implementation Phase

1. On first inbound message, `get_or_create` `WhatsAppConversationSession`; if `language IS NULL`, send language picker.
2. Handle `ButtonPayload` in webhook or n8n; map via `LANGUAGE_BUTTON_PAYLOADS`; set `language` and `language_selected_at`.
3. Lazy-backfill `language="en"` for Redis customers with existing qualification progress.
4. Route qualification prompts, Deepgram, and TTS by `language`.
