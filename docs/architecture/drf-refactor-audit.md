# DRF Refactor Architecture Audit (Phase 1)

**Project:** WebLead
**Date:** 2026-06-24
**Scope:** Read-only audit. No application behavior changes in Phase 1.

---

## Executive summary

| Item | Status |
| --- | --- |
| Django REST Framework installed | **No** — not in `requirements.txt`, not in `INSTALLED_APPS` |
| Current API style | Plain Django function views + `JsonResponse` |
| Primary apps | `apps.qualification`, `apps.webhooks` |
| Test runner | `pytest` + `pytest-django` (`Makefile`, `pytest.ini`) |
| Database | Empty `DATABASES = {}` (stateless / in-memory) |

The qualification WhatsApp text and voice-note flow works today. The recommended path is to **introduce DRF incrementally** behind unchanged URL paths and JSON contracts so n8n, Twilio, Deepgram, Supertonic, and Cloudflare integrations keep working without workflow changes.

---

## 1. Current endpoint inventory

| Method | Path | View / handler | Auth | Purpose |
| --- | --- | --- | --- | --- |
| `POST` | `/api/webhooks/twilio/whatsapp-inbound/` | `apps.webhooks.views.twilio_whatsapp_inbound` | Twilio `X-Twilio-Signature` | Validate Twilio webhook, forward form body to n8n |
| `POST` | `/api/internal/qualification/extract/` | `apps.qualification.views.internal_qualification_extract` | `X-Internal-Webhook-Secret` | Run one qualification turn (text or voice) |
| `POST` | `/api/internal/qualification/render-audio/` | `apps.qualification.render_audio_views.internal_render_audio` | `X-Internal-Webhook-Secret` | TTS via Supertonic → store OGG → return public `media_url` |
| `GET`, `HEAD` | `/media/whatsapp_voice_replies/<uuid:audio_id>/` | `apps.qualification.media_views.whatsapp_voice_reply_media` | None (public) | Serve generated voice reply audio |

**URL wiring**

- Root: `config/urls.py`
- Qualification internal API: `apps/qualification/urls.py` (included at `api/internal/qualification/`)
- Webhooks: `apps/webhooks/urls.py` (included at `api/webhooks/`)

---

## 2. Current request and response contracts

### 2.1 Twilio WhatsApp inbound → n8n

**Request:** `POST`, `application/x-www-form-urlencoded` (Twilio standard fields: `MessageSid`, `From`, `Body`, `NumMedia`, `MediaUrl0`, etc.)

**Success:** `200` empty body
**Failure:** `403` (bad signature), `502` (n8n forward failed)

**Contract owner:** Twilio → Django → n8n. n8n receives the original Twilio form fields. Do not change parameter names or forwarding format.

### 2.2 Internal qualification extract

**Request:** `POST`, `Content-Type: application/json`

```json
{
  "whatsapp_number": "+923001234567",
  "input_channel": "whatsapp_text",
  "message": "I need a new website for a restaurant",
  "message_sid": "SM0cc5a1d9e22bf9850ca24261ee23ce90",
  "media_url": null,
  "media_content_type": null
}
```

| Field | Text channel | Voice channel |
| --- | --- | --- |
| `whatsapp_number` | required, E.164 | required, E.164 |
| `input_channel` | `whatsapp_text` (default) | `whatsapp_voice_note` |
| `message` | required, non-empty | optional (transcribed if omitted) |
| `message_sid` | optional, `SM…` or `MM…` (34 chars) | recommended |
| `media_url` | ignored if present | required, `https://` Twilio media URL |
| `media_content_type` | ignored if present | required, must start with `audio/` |

Extra top-level keys → `400`. Wrong method → `405`.

**Success `200` body** (shape must remain stable for n8n):

```json
{
  "accepted_fields": { "project_type": "new_website", "requirements": "..." },
  "rejected_fields": { "referral_source": "value_missing" },
  "human_handoff_requested": false,
  "next_field": "referral_source",
  "reply_text": "Thank you. How did you hear about us?",
  "qualification_status": "in_progress",
  "preferred_phone": null,
  "reply_mode": "text",
  "send_booking_link": false,
  "booking_link": null
}
```

Voice-only addition on success: `"transcript": "<transcribed text>"` when `input_channel` is `whatsapp_voice_note`.

When `qualification_status` is `completed`: `send_booking_link: true`, `booking_link` set, `reply_text` is the voice-safe completion line.

**Error bodies** (exact strings matter for n8n branching):

| Status | Body |
| --- | --- |
| `400` | `{"error": "Invalid request."}` |
| `403` | `{"error": "Forbidden."}` |
| `502` | `{"error": "Qualification service request failed."}` |
| `503` | `{"error": "Qualification service is unavailable."}` |
| `500` | `{"error": "Internal server error."}` |

**Idempotency:** When `message_sid` is provided, successful `200` responses are cached in memory; replays return the same JSON without re-processing.

Reference docs: `docs/integrations/n8n/LLM-5-django-qualification-endpoint.md`, `docs/integrations/n8n/T3-11-whatsapp-text-voice-reply-routing.md`.

### 2.3 Internal render-audio

**Request:** `POST`, `application/json`

```json
{
  "text": "Thank you. How did you hear about us?",
  "voice": "F1",
  "lang": "en",
  "request_id": "SM_TEST_001"
}
```

| Field | Required | Notes |
| --- | --- | --- |
| `text` | yes | non-empty, max `MAX_TTS_TEXT_LENGTH` |
| `voice` | no | default `F1` |
| `lang` | no | default `en` |
| `request_id` | no | echoed in response; `[A-Za-z0-9_-]{1,128}` |

**Success `200`:**

```json
{
  "media_url": "https://<public-host>/media/whatsapp_voice_replies/<uuid>/",
  "content_type": "audio/ogg",
  "request_id": "SM_TEST_001"
}
```

**Errors:** same generic error pattern as extract (`400`, `403`, `502`, `503`, `500`).

### 2.4 Public voice media

**Request:** `GET` or `HEAD` `/media/whatsapp_voice_replies/<uuid>/`

**Success:** `200`, `Content-Type: audio/ogg`, file body (or `HEAD` with `Content-Length`)
**Failure:** `404` (invalid UUID, missing file, expired TTL)

No JSON contract. Twilio/n8n consume the URL returned by render-audio.

---

## 3. Layer assignment (current → target)

| Layer | Responsibility | Current location | Target location (post-refactor) |
| --- | --- | --- | --- |
| **API views** | HTTP method, auth gate, status codes, delegate | `views.py`, `render_audio_views.py`, `media_views.py`, `webhooks/views.py` | `api/views.py` (DRF `APIView`) per app |
| **Serializers** | Request validation, response shape | Inline in views (`_parse_extract_request`, `_parse_render_audio_request`) | `api/serializers.py` |
| **Services** | Orchestration, business rules | `qualification_turn.py`, `conversation_flow.py`, `whatsapp_audio.py` (partial), voice resolution in `views.py` | `services/` modules |
| **Integration clients** | External HTTP (Twilio media, Deepgram, OpenRouter, Supertonic, n8n) | `twilio_media.py`, `deepgram_client.py`, `openrouter_client.py`, `supertonic_client.py`, `webhooks/n8n_forward.py` | `integrations/` (or keep `*_client.py` naming) |
| **Domain helpers** | Pure logic, no I/O | `filtering.py`, `extractor.py`, `phone_confirmation.py`, `channels.py`, `schema.py`, `prompts.py`, `conversation_state.py`, `message_idempotency.py` | `domain/` or existing top-level modules |
| **Auth** | Shared secret validation | `internal_auth.py` | `api/permissions.py` or `auth/internal.py` |
| **Tests** | Contract, service, client tests | `apps/*/tests/` | Same tree; add `api/`, `services/`, `integrations/` test mirrors |

### What belongs where (detail)

**API views (thin)**

- Check `N8N_QUALIFICATION_API_SECRET` configured
- Call `is_internal_qualification_authorized` (later: DRF permission class)
- Validate with serializer → call service → serialize response
- Map domain exceptions to HTTP status + exact error JSON
- No OpenRouter/Deepgram/Twilio calls directly

**Serializers**

- `ExtractRequestSerializer` / `ExtractResponseSerializer`
- `RenderAudioRequestSerializer` / `RenderAudioResponseSerializer`
- Reproduce every validation rule currently in `_parse_*` functions

**Services**

- `QualificationExtractService.run_turn(...)` — idempotency, channel finalize, exception mapping inputs
- `VoiceNoteTranscriptionService.transcribe_from_twilio_media(...)` — move logic from `_resolve_turn_message` in `views.py`
- `RenderAudioService.render(...)` — wrap `render_whatsapp_voice_reply_safe`
- `QualificationTurnService` — already mostly `handle_qualification_turn` + `conversation_flow`

**Integration clients**

- Keep HTTP isolated; clients should not call `filter_qualification_fields` or `build_turn_response`
- **Today:** `openrouter_client.extract_qualification_from_openrouter` mixes LLM call + parse + filter + phone guard → split in Phase 3

**Domain helpers**

- `conversation_flow`, `filtering`, `extractor`, `phone_confirmation`, `channels`, `schema`, `prompts`
- In-memory `conversation_state`, `message_idempotency` (document persistence risk separately)

**Tests**

- Endpoint contract tests stay; update imports/patch paths only
- Add dedicated service and integration unit tests where views are currently over-mocked

---

## 4. Duplicate or overly large modules

| Module | Lines (approx.) | Issue |
| --- | --- | --- |
| `apps/qualification/views.py` | ~452 | **Fat view:** request parsing, voice pipeline orchestration, logging, HTTP mapping |
| `apps/qualification/render_audio_views.py` | ~127 | Duplicates `_log_event`, manual JSON parse/validate pattern |
| `apps/qualification/openrouter_client.py` | ~142 | Client + extraction pipeline (parse, phone guard, filter) |
| `apps/qualification/whatsapp_audio.py` | ~200 | Storage, ffmpeg, Supertonic orchestration, public URL building |
| `apps/qualification/conversation_flow.py` | ~315 | Large but cohesive domain module — acceptable |
| Logging helpers | scattered | `_log_event` in two view files; `voice_note_logging.py` separate |

**Duplication**

- E.164 regex in `views.py` and `conversation_flow.py`
- Twilio MessageSid pattern only in `views.py`
- Internal auth + 503-when-secret-missing repeated in extract and render-audio views
- Safe error JSON mapping duplicated between views

---

## 5. Security and testing risks

### Security

| Risk | Severity | Notes |
| --- | --- | --- |
| In-memory conversation + idempotency state | **High (ops)** | Lost on restart; multi-worker inconsistency. Not a secret leak, but data integrity risk. |
| `.env` in workspace | **High** | `.gitignore` covers it; rules must enforce never commit |
| `media/` generated audio | **Medium** | Gitignored; public URLs are UUID-guess resistant but unauthenticated |
| Logging | **Low–Medium** | Voice path uses safe structured logs; views do not log full phone/transcript. Maintain discipline during refactor. |
| `openrouter_client` sends full customer message to OpenRouter | **Expected** | External LLM; ensure logs never capture message body |
| No CSRF on webhooks/internal API | **OK** | `@csrf_exempt` appropriate for machine clients with secret/signature |
| Twilio signature validation | **Good** | Official `RequestValidator`, proxy-aware URL |
| Internal auth | **Good** | `secrets.compare_digest`, constant-time compare |

### Testing

| Area | Coverage | Gap |
| --- | --- | --- |
| Extract endpoint | Strong (`test_internal_extract_endpoint.py`, voice tests) | Few tests patch at view layer instead of service boundary |
| Render-audio | Good | Public media TTL/HEAD covered |
| Webhooks | Basic inbound tests | n8n forward error paths |
| Integration clients | OpenRouter, Deepgram, Twilio have unit tests | Supertonic client tests live inside render-audio tests only |
| DRF | N/A | No renderer/parser/throttle tests yet |

**Test command note:** Project convention is `make test` / `pytest` (`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`). `python manage.py test` may not discover pytest-style tests unless configured.

---

## 6. Phased migration plan

### Phase 1 — Audit and Cursor setup (this document)

- No application code changes
- Add `.cursor/rules/` and `.cursor/skills/`
- Confirm contracts and inventory

**Rollback:** Delete new docs/rules/skills only.

### Phase 2 — DRF foundation (no contract changes)

| Action | Files |
| --- | --- |
| Add `djangorestframework` to `requirements.txt` | `requirements.txt` |
| Register `rest_framework` in `INSTALLED_APPS` | `config/settings.py` |
| Add minimal DRF settings (JSON only, no browsable API in prod) | `config/settings.py` |
| Create package skeleton | `apps/qualification/api/__init__.py`, `services/__init__.py`, `integrations/__init__.py` |
| Add shared internal permission | `apps/qualification/api/permissions.py` |
| Add contract snapshot tests (optional baseline JSON fixtures) | `apps/qualification/tests/test_api_contract_snapshots.py` |

**Rollback:** Revert dependency and new files; no URL or behavior change.

### Phase 3 — Extract endpoint to DRF

| Action | Files |
| --- | --- |
| Move request/response validation to serializers | `apps/qualification/api/serializers/extract.py` |
| Move voice resolution to service | `apps/qualification/services/voice_note.py` |
| Move turn orchestration wrapper | `apps/qualification/services/extract.py` |
| Thin DRF `APIView` | `apps/qualification/api/views/extract.py` |
| Wire URL to DRF view (same path) | `apps/qualification/urls.py` |
| Deprecate old function view | `apps/qualification/views.py` (remove or re-export) |
| Update test patch paths | `apps/qualification/tests/test_internal_extract_endpoint.py`, `test_voice_note_failures.py` |

**Rollback:** Point `urls.py` back to `internal_qualification_extract`; keep serializers/services unused.

### Phase 4 — Render-audio endpoint to DRF

| Action | Files |
| --- | --- |
| Serializers | `apps/qualification/api/serializers/render_audio.py` |
| Service | `apps/qualification/services/render_audio.py` |
| DRF view | `apps/qualification/api/views/render_audio.py` |
| URLs | `apps/qualification/urls.py` |
| Tests | `apps/qualification/tests/test_render_audio_endpoint.py` |

**Rollback:** Restore `render_audio_views.internal_render_audio` in URLs.

### Phase 5 — Integration client cleanup

| Action | Files |
| --- | --- |
| Split OpenRouter HTTP from extraction pipeline | `integrations/openrouter_client.py`, `services/extraction.py` |
| Relocate clients (optional re-exports for compat) | `twilio_media.py` → `integrations/twilio_media.py`, etc. |
| Extract shared logging | `apps/qualification/logging.py` or `api/logging.py` |
| Remove duplicate parsers from old views | delete dead code in `views.py`, `render_audio_views.py` |

**Rollback:** Re-export from old module paths for one release.

### Phase 6 — Webhooks app (lower priority)

| Action | Files |
| --- | --- |
| Optional DRF `APIView` for Twilio inbound | `apps/webhooks/api/views.py` |
| Keep form encoding + signature validation identical | `twilio_validation.py`, `n8n_forward.py` |

**Rollback:** Keep function view in `urls.py`.

### Phase 7 — Hardening (optional, separate approval)

- Persistent conversation store (if product requires)
- Rate limiting / throttling on internal API
- Not part of initial DRF refactor unless approved

---

## 7. Explicit contract preservation (n8n / external)

**The following must not change without explicit product/integration approval:**

1. URL paths listed in section 1
2. HTTP methods and status codes in section 2
3. Exact JSON keys and error message strings for n8n-facing endpoints
4. `X-Internal-Webhook-Secret` header name and `N8N_QUALIFICATION_API_SECRET` setting
5. Twilio webhook form forwarding to n8n (`application/x-www-form-urlencoded`)
6. Twilio signature validation behavior and response codes (`200`/`403`/`502`)
7. Public `media_url` path pattern: `/media/whatsapp_voice_replies/<uuid>/`
8. `reply_mode`, `transcript`, `send_booking_link`, `booking_link` response semantics documented in T3-11
9. MessageSid idempotency behavior when `message_sid` is supplied
10. Deepgram, Supertonic, OpenRouter request/response formats as consumed by existing clients

Phase 2+ work should be validated by running the full pytest suite and comparing endpoint responses to fixtures derived from current tests (`N8N_TEXT_PAYLOAD`, `N8N_VOICE_PAYLOAD`, etc.).

---

## 8. Rollback approach per phase

| Phase | Rollback trigger | Steps |
| --- | --- | --- |
| 2 | DRF install breaks deploy | Remove `rest_framework` from settings and requirements; redeploy previous image |
| 3 | Extract contract regression | `git revert` Phase 3 commit; restore function view URLconf |
| 4 | Render-audio regression | Revert URL to `render_audio_views`; keep Phase 3 if stable |
| 5 | Import breakage | Restore re-export shims; revert file moves |
| 6 | Webhook regression | Revert to `webhooks.views.twilio_whatsapp_inbound` only |

**General practice**

- One phase per PR/commit series
- Run `pytest`, `python manage.py check`, `git diff --check` before merge
- Keep old view functions until DRF path is proven in staging
- Tag git release before each phase merge

---

## 9. Dependencies and configuration

**Current `requirements.txt`:**

- `Django>=5.0,<6.0`
- `django-environ>=0.11.0`
- `twilio>=9.0.0`
- `pytest>=8.0.0`
- `pytest-django>=4.8.0`

**Missing for DRF target:** `djangorestframework`

**Settings of note:** `config/settings.py` — extensive env validation for Twilio, Deepgram, OpenRouter, Supertonic timeouts; `DATABASES = {}`; JSON logging for `apps.qualification` and `apps.webhooks`.

---

## 10. Recommended Phase 2 scope

1. Add `djangorestframework` and minimal `REST_FRAMEWORK` config (JSON renderer only).
2. Create `apps/qualification/api/`, `services/`, `integrations/` package scaffolding (empty `__init__.py` only).
3. Implement `InternalWebhookSecretPermission` matching `internal_auth.is_internal_qualification_authorized`.
4. Add one smoke test proving DRF is importable and permission class works.
5. Document in README or `docs/architecture/` that new endpoints must follow `.cursor/rules/django-drf-architecture.mdc`.

Do **not** yet move extract or render-audio views — Phase 3/4.

---

## Appendix: module map (qualification app)

```
apps/qualification/
├── views.py                 # FAT: extract endpoint + voice pipeline
├── render_audio_views.py    # render-audio endpoint
├── media_views.py           # public OGG serving
├── urls.py
├── internal_auth.py
├── qualification_turn.py    # turn service (good)
├── conversation_flow.py     # domain
├── conversation_state.py      # in-memory store
├── message_idempotency.py
├── channels.py
├── openrouter_client.py     # integration + pipeline
├── deepgram_client.py
├── twilio_media.py
├── supertonic_client.py
├── whatsapp_audio.py        # TTS + storage + ffmpeg
├── extractor.py, filtering.py, phone_confirmation.py, prompts.py, schema.py, models.py, config.py
├── voice_note_config.py, voice_note_logging.py
└── tests/                   # 14 test modules, ~150 test functions
```
