# WhatsApp Voice Lead Agent

Django backend for **Nora AI**: bilingual (English / Arabic) WhatsApp lead qualification with text and voice notes.

| Item | Value |
|------|--------|
| Business WhatsApp number | **+923301675395** |
| WhatsApp transport | **WAHA** (WhatsApp HTTP API) |
| Orchestration | **n8n** workflows |
| Runtime | Python **3.12**, Django **5.x** |
| Deploy target | Local + **Vercel** (`config/wsgi.py`) |

This repository owns:

- WAHA inbound webhook handling and outbound sends
- Lead qualification extract (LLM via OpenRouter)
- Conversation session state (language, menus, idle reset, existing customers)
- Interactive WhatsApp pickers (language, menu, referral, business type, project type)
- Voice-note STT (Deepgram) and reply TTS (Supertonic)
- Internal APIs consumed by n8n / LiveKit workers

It does **not** own the full n8n workflow graph or the WAHA WhatsApp session itself (those are configured separately).

---

## Table of contents

1. [Architecture](#architecture)
2. [Message flow](#message-flow)
3. [Repository layout](#repository-layout)
4. [Requirements](#requirements)
5. [Local setup](#local-setup)
6. [WAHA setup](#waha-setup)
7. [Environment variables](#environment-variables)
8. [HTTP API reference](#http-api-reference)
9. [Qualification behavior](#qualification-behavior)
10. [Interactive messages](#interactive-messages)
11. [Voice notes](#voice-notes)
12. [n8n integration](#n8n-integration)
13. [Database and persistence](#database-and-persistence)
14. [Testing](#testing)
15. [Scripts](#scripts)
16. [Deployment](#deployment)
17. [Troubleshooting](#troubleshooting)
18. [Further documentation](#further-documentation)

---

## Architecture

```text
┌─────────────┐     ┌──────────┐     ┌────────────────────────────────────────┐
│  WhatsApp   │────▶│   WAHA   │────▶│  Django                                │
│  user       │◀────│  :3000   │◀────│  webhooks / whatsapp / qualification   │
└─────────────┘     └──────────┘     └───────────────┬────────────────────────┘
                                                     │
                                                     ▼
                                              ┌─────────────┐
                                              │    n8n      │
                                              │  workflow   │
                                              └──────┬──────┘
                                                     │
                                                     ▼
                                      POST /api/internal/qualification/extract/
                                      (+ optional render-audio / send)
```

| Component | Role |
|-----------|------|
| **WAHA** | Linked WhatsApp session; emits `message` webhooks; sends text / buttons / lists / voice |
| **`apps.webhooks`** | Authenticate WAHA POST; map event → extract-shaped JSON; forward to n8n |
| **`apps.whatsapp`** | WAHA REST client, chatId helpers, interactive send + text fallback, media download |
| **`apps.qualification`** | Session ORM, extract turn, language gate, menus, STT/TTS, booking / handoff |
| **n8n** | Dedupe by `message_sid`, call extract, route replies; skip Content when Django already sent interactives |
| **OpenRouter** | LLM field extraction |
| **Deepgram** | Voice-note transcription (EN / AR models) |
| **Supertonic** | TTS for voice replies (Arabic gated by `SUPERTONIC_ARABIC_ENABLED`) |

### Ownership split (Django vs n8n)

| Concern | Owner |
|---------|--------|
| Language picker (`lang_en` / `lang_ar`) | Django via WAHA |
| Main menu list | Django via WAHA |
| `referral_source` / `business_type` / `project_type` lists or buttons | Django via WAHA (`option_template`) |
| Booking link / existing-customer paths | Django (often as part of extract turn) |
| Normal text / voice replies | n8n → Django send proxy **or** direct WAHA |
| Lead Data Table updates in n8n | n8n (from extract `accepted_fields`) |

When extract returns `option_template` (and typically `should_send_text === false`), **n8n must not** send that interactive again.

---

## Message flow

### Inbound text / button / list reply

```text
1. User messages +923301675395
2. WAHA POSTs event to:
     /api/webhooks/waha/whatsapp-inbound/
   Header: X-Api-Key: <WAHA_WEBHOOK_SECRET or WAHA_API_KEY>
3. Django ignores fromMe / groups; maps body → extract JSON
4. Django POSTs JSON to N8N_WEBHOOK_URL (X-Internal-Webhook-Secret)
5. n8n calls POST /api/internal/qualification/extract/
6. Django updates WhatsAppConversationSession, may send pickers via WAHA
7. n8n sends reply_text / audio only when flags allow
```

### Inbound voice note

Same path; payload uses `input_channel: "whatsapp_voice_note"` plus `media_url` / `media_content_type`. Extract downloads media from WAHA (with `X-Api-Key`), transcribes via Deepgram, then continues qualification on the transcript.

### Normalized inbound payload (Django → n8n)

```json
{
  "whatsapp_number": "+9233XXXXXXXXX",
  "message": "Hello",
  "message_sid": "true_9233…@c.us_…",
  "button_payload": "lang_en",
  "button_text": "English",
  "input_channel": "whatsapp_text",
  "media_url": null,
  "media_content_type": null
}
```

`button_payload` / `button_text` are set for interactive replies when WAHA provides them. Voice notes set `input_channel` to `whatsapp_voice_note` and fill media fields.

---

## Repository layout

```text
whatsapp-voice-lead-agent/
├── apps/
│   ├── webhooks/           # WAHA inbound view + n8n_forward
│   ├── whatsapp/           # WAHA client, message_service, webhook_handler, media
│   └── qualification/      # Domain, services, extract API, STT/TTS, models
├── config/                 # settings, urls, wsgi, Vercel bootstrap
├── data/                   # Local SQLite (gitignored content)
├── docs/                   # Setup guides, n8n notes, ADRs, reports
├── scripts/                # Config / local smoke helpers
├── docker-compose.waha.yml # WAHA container + webhook env
├── .env.example            # All documented environment variables
├── manage.py
├── Makefile                # make test
├── pytest.ini
├── requirements.txt
├── vercel.json
└── waha-whatsapp-inbound.json   # Stub n8n inbound workflow
```

### Key modules

| Path | Purpose |
|------|---------|
| `apps/webhooks/views.py` | `waha_whatsapp_inbound` — auth, parse, forward |
| `apps/whatsapp/webhook_handler.py` | WAHA event → extract payload |
| `apps/whatsapp/message_service.py` | Text + interactive sends + numbered-text fallback |
| `apps/whatsapp/waha_client.py` | REST: `sendText`, buttons, lists, media |
| `apps/qualification/api/views.py` | Extract / render-audio / voice-call-completed |
| `apps/qualification/models.py` | `WhatsAppConversationSession` |
| `apps/qualification/domain/` | Language, menu, validators, messages, idle reset |
| `apps/qualification/services/` | ExtractService, render audio, language gate, etc. |

---

## Requirements

- **Python 3.12** (`.python-version`)
- Docker (for WAHA)
- Optional: PostgreSQL, Redis
- Accounts / services:
  - WAHA session linked to +923301675395
  - n8n instance with WhatsApp inbound workflow
  - OpenRouter API key + model
  - Deepgram API key (voice notes)
  - Supertonic TTS reachable at `SUPERTONIC_BASE_URL` (voice replies)

---

## Local setup

```bash
# 1. Clone and virtualenv
cd whatsapp-voice-lead-agent
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Environment
cp .env.example .env
# Edit .env — at minimum for a smoke path:
#   DJANGO_SECRET_KEY, DEBUG=true
#   WAHA_BASE_URL, WAHA_SESSION, WAHA_API_KEY
#   WAHA_HOOK_URL, WAHA_HOOK_CUSTOM_HEADERS
#   N8N_WEBHOOK_URL, N8N_WEBHOOK_SECRET, N8N_QUALIFICATION_API_SECRET
#   OPENROUTER_API_KEY, OPENROUTER_MODEL
#   BASE_WEBHOOK_URL (public origin if n8n is remote)

# 3. Database
python manage.py migrate
# With empty DATABASE_URL → SQLite at data/qualification.sqlite3

# 4. Run Django
python manage.py runserver 8000
```

Health check:

```bash
curl -sS http://127.0.0.1:8000/
# {"status":"ok","service":"whatsapp-voice-lead-agent"}
```

Optional config checks:

```bash
./scripts/check_qualification_config.sh
./scripts/check_voice_note_config.sh
```

---

## WAHA setup

Full guide: [docs/waha-setup-guide.md](docs/waha-setup-guide.md).

### Start / restart

```bash
docker compose -f docker-compose.waha.yml down
docker compose -f docker-compose.waha.yml up -d
```

Dashboard / Swagger: [http://localhost:3000](http://localhost:3000)

Compose maps:

| `.env` | Container env |
|--------|----------------|
| `WAHA_API_KEY` | `WAHA_API_KEY` |
| `WAHA_HOOK_URL` | `WHATSAPP_HOOK_URL` |
| `WAHA_HOOK_CUSTOM_HEADERS` | `WHATSAPP_HOOK_CUSTOM_HEADERS` |
| (fixed) | `WHATSAPP_HOOK_EVENTS=message` |
| `WAHA_PUBLIC_BASE_URL` (optional) | `WAHA_BASE_URL` inside WAHA |

Engine defaults to **NOWEB** (better for list messages). Interactive send failures fall back to numbered plain text in Django.

### Local Docker networking

Inside the WAHA container, `localhost` is the **container**, not your host Django process.

For local development:

```env
WAHA_HOOK_URL=http://host.docker.internal:8000/api/webhooks/waha/whatsapp-inbound/
WAHA_HOOK_CUSTOM_HEADERS=X-Api-Key:your-same-secret
```

`docker-compose.waha.yml` sets:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

so Linux resolves `host.docker.internal` to the Docker host.

Production: set `WAHA_HOOK_URL` to your public HTTPS Django origin (same path). Do not hardcode URLs in compose.

Verify env inside the container:

```bash
docker compose -f docker-compose.waha.yml exec waha \
  printenv WHATSAPP_HOOK_URL WHATSAPP_HOOK_EVENTS WHATSAPP_HOOK_CUSTOM_HEADERS
```

### Link the number

1. Open Swagger at `http://localhost:3000` (send `X-Api-Key` as configured).
2. Create/start session `default` (or match `WAHA_SESSION`).
3. Fetch QR (`GET /api/default/auth/qr` or Dashboard) and scan with the phone for **+923301675395**.
4. Confirm session status `WORKING`.
5. Send a test WhatsApp message from another phone and confirm Django / n8n receive it.

---

## Environment variables

Authoritative template: [`.env.example`](.env.example). Summary by group:

### Django core

| Variable | Description |
|----------|-------------|
| `DJANGO_SECRET_KEY` | Django secret |
| `DEBUG` | `true` / `false` |
| `ALLOWED_HOSTS` | Comma-separated hosts (Vercel merges `.vercel.app` when applicable) |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated HTTPS origins |
| `DATABASE_URL` | Empty → local SQLite; else Postgres URL |
| `DJANGO_MIGRATE_ON_STARTUP` | Force migrate on process start |
| `QUALIFICATION_REDIS_URL` | Optional Redis for locks / idempotency / multi-worker |

### Public URLs

| Variable | Description |
|----------|-------------|
| `BASE_WEBHOOK_URL` | Public Django origin used by n8n callbacks |
| `PUBLIC_MEDIA_BASE_URL` | Base for voice reply media URLs (defaults to `BASE_WEBHOOK_URL`) |

### WAHA

| Variable | Description |
|----------|-------------|
| `WAHA_BASE_URL` | Django → WAHA API (e.g. `http://localhost:3000`) |
| `WAHA_SESSION` | Session name (default `default`) |
| `WAHA_API_KEY` | WAHA REST + fallback webhook auth |
| `WAHA_WEBHOOK_SECRET` | Preferred inbound `X-Api-Key` (falls back to `WAHA_API_KEY`) |
| `WAHA_HOOK_URL` | Passed to compose as `WHATSAPP_HOOK_URL` |
| `WAHA_HOOK_CUSTOM_HEADERS` | e.g. `X-Api-Key:secret` (`Header:Value;…`) |
| `WAHA_PUBLIC_BASE_URL` | Optional public base for WAHA media URLs |
| `WAHA_MEDIA_DOWNLOAD_TIMEOUT_SECONDS` | Media download timeout |
| `WAHA_MEDIA_MAX_BYTES` | Max download size (default 10 MiB) |

### n8n / internal auth

| Variable | Description |
|----------|-------------|
| `N8N_WEBHOOK_URL` | Django POSTs normalized inbound here (`N8N_WHATSAPP_WEBHOOK_URL` legacy alias) |
| `N8N_WEBHOOK_SECRET` | Sent as `X-Internal-Webhook-Secret` on forward |
| `N8N_QUALIFICATION_API_SECRET` | Protects extract / render-audio / send |
| `N8N_OPTION_TEMPLATE_WEBHOOK_URL` | Optional; else option_template delivery uses `N8N_WEBHOOK_URL` |
| `WEBLEAD_VOICE_EVENT_SECRET` | `X-WebLead-Secret` for voice-call-completed |

### Qualification / UX timers

| Variable | Description |
|----------|-------------|
| `LEAD_QUALIFICATION_ENABLED` | Master switch |
| `QUALIFICATION_CONFIDENCE_THRESHOLD` | Default `0.75` |
| `WHATSAPP_MENU_INACTIVITY_SECONDS` | Idle menu (timer-driven) |
| `WHATSAPP_MENU_PENDING_SECONDS` | Window to accept menu replies |
| `SESSION_IDLE_RESET_SECONDS` | Idle reset behavior |
| `EXISTING_CUSTOMER_FOLLOWUP_DELAY_SECONDS` | Delayed Noura follow-up |
| `ONBOARDING_REINTRO_AFTER_SECONDS` | Retained for env compatibility |
| `BOOKING_LINK` | Booking URL injected when qualification completes |
| `QUALIFICATION_CONVERSATION_TTL_SECONDS` | Conversation cache TTL |
| `QUALIFICATION_IDEMPOTENCY_*` | Message / processing idempotency TTLs |

### LLM / STT / TTS

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL`, `OPENROUTER_TIMEOUT_SECONDS` | Extraction LLM |
| `DEEPGRAM_*` | Voice STT (EN defaults + AR `nova-3` / `ar`) |
| `SUPERTONIC_BASE_URL`, `SUPERTONIC_ENGLISH_VOICE` | TTS |
| `SUPERTONIC_ARABIC_ENABLED`, `SUPERTONIC_ARABIC_VOICE` | Arabic TTS gate |
| `MAX_TTS_TEXT_LENGTH`, `WHATSAPP_AUDIO_TTL_SECONDS`, `SUPERTONIC_TTS_TIMEOUT_SECONDS` | Audio limits / TTL |

---

## HTTP API reference

### Health

```http
GET /
```

```json
{"status": "ok", "service": "whatsapp-voice-lead-agent"}
```

### WAHA inbound webhook

```http
POST /api/webhooks/waha/whatsapp-inbound/
X-Api-Key: <WAHA_WEBHOOK_SECRET or WAHA_API_KEY>
Content-Type: application/json
```

| Status | Meaning |
|--------|---------|
| `200` | Accepted (including ignored `fromMe` / groups — still ack) |
| `403` | Missing/invalid API key or secret not configured |
| `400` | Invalid JSON or unparsable event |
| `502` | Forward to n8n failed |

No Twilio signature validation. Body is WAHA JSON; Django maps it and forwards extract-shaped JSON to n8n.

### Qualification extract

```http
POST /api/internal/qualification/extract/
X-Internal-Webhook-Secret: <N8N_QUALIFICATION_API_SECRET>
Content-Type: application/json
```

**Request (common fields):**

| Field | Notes |
|-------|--------|
| `whatsapp_number` | E.164 (e.g. `+9233…`) |
| `message` | Required for `whatsapp_text` |
| `message_sid` | Idempotency / dedupe key |
| `input_channel` | `whatsapp_text` (default) or `whatsapp_voice_note` |
| `media_url` / `media_content_type` | Voice notes |
| `button_payload` / `button_text` | Interactive reply ids |
| `event_source` | e.g. inactivity timer (not user input) |
| `call_sid` / `utterance_id` / `is_final` | Voice-call related |

**Response (selected fields):**

| Field | Notes |
|-------|--------|
| `reply_text` / `whatsapp_text` / `spoken_text` | Customer-facing copy |
| `qualification_status` | Pipeline status string |
| `conversation_language` | `en` / `ar` |
| `accepted_fields` / `rejected_fields` | Extracted lead data |
| `next_field` | Next required field |
| `should_send_text` / `should_send_audio` | n8n send gates |
| `option_template` | `referral_source` / `business_type` / `project_type` — Django already sent |
| `send_booking_link` / `booking_link` | Booking completion |
| `duplicate_detected` | Idempotent replay |
| `transcript` | Present for voice-note turns |

### Render audio

```http
POST /api/internal/qualification/render-audio/
X-Internal-Webhook-Secret: <N8N_QUALIFICATION_API_SECRET>
```

Used when `should_send_audio` is true. Returns a public media URL under `/media/whatsapp_voice_replies/<uuid>/` for WAHA `sendVoice` / `sendFile`.

### Send WhatsApp text (proxy)

```http
POST /api/internal/whatsapp/send/
X-Internal-Webhook-Secret: <N8N_QUALIFICATION_API_SECRET>
Content-Type: application/json

{
  "phone_number": "+9233XXXXXXXXX",
  "message": "Hello from Nora"
}
```

```json
{"ok": true, "message_id": "…"}
```

Lets n8n send text without holding `WAHA_API_KEY` in the workflow (Django calls WAHA).

### Voice call completed

```http
POST /api/internal/qualification/voice-call-completed/
X-WebLead-Secret: <WEBLEAD_VOICE_EVENT_SECRET>
```

LiveKit / worker post-call completion → WhatsApp follow-up path.

### Voice reply media

```http
GET /media/whatsapp_voice_replies/<uuid>/
```

Public audio bytes for WhatsApp voice replies (TTL controlled by `WHATSAPP_AUDIO_TTL_SECONDS`).

---

## Qualification behavior

Persistent model: `WhatsAppConversationSession` (`whatsapp_number` unique).

Tracks among other things:

- Language (`en` / `ar`) and language-picker pending windows
- Menu pending / last menu metadata
- `accepted_fields` JSON for the active qualification cycle
- `conversation_cycle` (bumped on idle reset / menu restart)
- `qualified_at` (durable existing-customer marker)
- Booking link and existing-customer follow-up timestamps
- Human handoff request time

Typical customer journey:

1. **Language selection** — Django sends buttons; status may be `awaiting_language_selection`
2. **Onboarding / qualification questions** — LLM extract fills fields with confidence threshold
3. **Option templates** — referral source, project type, business type as WAHA lists/buttons
4. **Completion** — booking link and/or existing-customer handoff / follow-up
5. **Menu** — inactivity or explicit menu; options such as continue / restart / language / human
6. **Language commands** — mid-conversation language change (see domain `language_commands`)

Master switch: `LEAD_QUALIFICATION_ENABLED=false` disables qualification behavior.

---

## Interactive messages

Implemented in `apps/whatsapp/message_service.py`:

| Helper | Stable ids (examples) |
|--------|------------------------|
| `send_language_picker` | `lang_en`, `lang_ar` |
| `send_whatsapp_menu` | `continue`, `restart`, `language`, `human` |
| `send_referral_source_list` | `google`, `instagram`, … |
| `send_business_type_list` | `biz_*` |
| `send_project_type_buttons` | project-type button ids |
| `deliver_option_template` | Dispatches by `option_template` key |

If WAHA returns an error for buttons/lists, Django sends **numbered plain text** instead. Qualification already accepts both button ids and numeric replies.

---

## Voice notes

**Inbound**

1. WAHA stores media; webhook includes media metadata / URL.
2. Extract downloads with `X-Api-Key` (`apps/whatsapp/media.py`).
3. Deepgram transcribes using language-specific model settings.
4. Turn continues on transcript text.

**Outbound**

1. n8n calls `/api/internal/qualification/render-audio/` when `should_send_audio`.
2. Django synthesizes via Supertonic and exposes a public URL.
3. n8n (or WAHA) sends voice with that URL.

Arabic TTS remains behind `SUPERTONIC_ARABIC_ENABLED` until a verified Arabic voice is configured.

---

## n8n integration

Primary doc: [docs/integrations/n8n/WAHA-whatsapp-transport.md](docs/integrations/n8n/WAHA-whatsapp-transport.md).

Stub workflow: [`waha-whatsapp-inbound.json`](waha-whatsapp-inbound.json).

### Checklist

- [ ] Point WAHA webhook at Django inbound URL with `X-Api-Key`
- [ ] Set `N8N_WEBHOOK_URL` to the n8n WhatsApp inbound webhook
- [ ] Call extract with `X-Internal-Webhook-Secret`
- [ ] Dedupe on `message_sid`
- [ ] If `qualification_status` / language gate is awaiting language → **stop** (Django sent picker)
- [ ] If `option_template` is set → **do not** resend interactive Content
- [ ] Send text only when `should_send_text === true`
- [ ] Use Django `/api/internal/whatsapp/send/` or WAHA `/api/sendText`
- [ ] Remove legacy Twilio Trigger / Content SID nodes

Related n8n docs under `docs/integrations/n8n/`:

- `LLM-5-django-qualification-endpoint.md`
- `T3-6-T3-7-fallback-setup.md`
- `T3-8-T3-9-lead-storage-and-clarification-setup.md`
- `T3-11-whatsapp-text-voice-reply-routing.md`

---

## Database and persistence

| Mode | Behavior |
|------|----------|
| No `DATABASE_URL` | SQLite file `data/qualification.sqlite3` |
| `DATABASE_URL=postgres://…` | PostgreSQL via `dj-database-url` |
| Vercel without `DATABASE_URL` | SQLite under `/tmp` + migrate on cold start |
| No `QUALIFICATION_REDIS_URL` | Process-local in-memory locks / idempotency (fine for single worker) |
| Redis set | Shared locks / idempotency across workers |

Run migrations after pull:

```bash
python manage.py migrate
```

---

## Testing

```bash
make test
```

Equivalent:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 DJANGO_SETTINGS_MODULE=config.settings_test \
  .venv/bin/python -m pytest -p pytest_django.plugin -q
```

- Settings module: `config.settings_test`
- Markers: `language_gate`, `whatsapp_menu` (see `pytest.ini`)
- Coverage includes WAHA inbound/auth, message service fallbacks, extract API contracts, Arabic routing, menus, booking, idle reset, and more under `apps/*/tests/`

---

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/check_qualification_config.sh` | Validate qualification-related env |
| `scripts/check_voice_note_config.sh` | Validate voice-note / Deepgram-related env |
| `scripts/test_render_audio_local.sh` | Local render-audio smoke |

---

## Deployment

### Vercel

- Entrypoint: `config/wsgi.py` (`application` / `app`)
- `vercel.json` sets `maxDuration: 60` for the WSGI function
- Set production env vars in the Vercel project (same names as `.env.example`)
- Ensure `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` include the deployment host
- Point `WAHA_HOOK_URL` at the **public** Django inbound URL
- Set `BASE_WEBHOOK_URL` / `PUBLIC_MEDIA_BASE_URL` to stable public HTTPS origins

### WAHA in production

- Run WAHA on a host/VPS with a durable volume for sessions (`waha_sessions`)
- Prefer a public `WAHA_PUBLIC_BASE_URL` so media URLs work for clients
- Keep `WAHA_API_KEY` and webhook secrets strong and rotated

---

## Troubleshooting

| Symptom | Likely cause | What to check |
|---------|--------------|---------------|
| No inbound to Django | Hook URL wrong / container not restarted | `printenv WHATSAPP_HOOK_URL`; recreate compose |
| `403` on inbound | `X-Api-Key` mismatch | `WAHA_HOOK_CUSTOM_HEADERS` vs `WAHA_WEBHOOK_SECRET` / `WAHA_API_KEY` |
| Hook hits WAHA itself | Used `localhost` inside container | Use `host.docker.internal` locally |
| Compose warns `$oy` unset | `$` inside `DJANGO_SECRET_KEY` in `.env` | Harmless for WAHA if `WAHA_*` are set |
| n8n never called | `N8N_WEBHOOK_URL` empty / forward 502 | Django logs `waha_n8n_forward_failed` |
| Duplicate replies | n8n still sending when `option_template` set | Skip Content/list send in workflow |
| Interactive fails | Engine/limits | Django falls back to numbered text; check WAHA logs |
| Voice note fails | Deepgram / media auth | `WAHA_API_KEY`, Deepgram keys, media URL reachability |
| Extract `503` | Secret missing | `N8N_QUALIFICATION_API_SECRET` must be set |

Useful loggers: `apps.webhooks`, qualification API logging in `apps.qualification.api.logging`.

---

## Further documentation

| Doc | Topic |
|-----|--------|
| [docs/waha-setup-guide.md](docs/waha-setup-guide.md) | WAHA Docker, QR, smoke tests |
| [docs/integrations/n8n/WAHA-whatsapp-transport.md](docs/integrations/n8n/WAHA-whatsapp-transport.md) | Post-Twilio n8n wiring |
| [docs/decisions/ADR-002-qualification-confidence-threshold.md](docs/decisions/ADR-002-qualification-confidence-threshold.md) | Confidence threshold ADR |
| [docs/architecture/](docs/architecture/) | DRF / function-view boundaries |
| [docs/](docs/) | Language, menu, Arabic TTS/STT reports |

---

## License / status

Internal WebLead / Nora AI project. Twilio WhatsApp transport has been removed; use WAHA exclusively for WhatsApp I/O.
