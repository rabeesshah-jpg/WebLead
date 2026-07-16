# Django and DRF Final Architecture Review

## Review Scope

- **Review date:** 2026-06-24
- **Repository/branch inspected:** WebLead / `feature/lead-qualification` (baseline commit `e286614`; working tree contained additional uncommitted migration work at inspection time)
- **Audit mode:** Read-only — no application code, configuration, tests, or existing documentation files were modified during this audit
- **Files and modules reviewed:**
  - `config/settings.py`, `config/settings_test.py`, `config/urls.py`
  - `apps/qualification/api/` (`views.py`, `serializers.py`, `permissions.py`, `exceptions.py`, `logging.py`)
  - `apps/qualification/services/` (`extract_service.py`, `transcription_service.py`, `render_audio_service.py`, `extraction_service.py`)
  - `apps/qualification/domain/` (`validators.py`)
  - `apps/qualification/integrations/` (`openrouter.py`)
  - `apps/qualification/` domain and integration modules (`qualification_turn.py`, `conversation_flow.py`, `extractor.py`, `filtering.py`, `phone_confirmation.py`, `whatsapp_audio.py`, `openrouter_client.py`, `internal_auth.py`, `views.py`, `render_audio_views.py`, `media_views.py`, `urls.py`, `message_idempotency.py`, `conversation_state.py`, `voice_note_logging.py`)
  - `apps/webhooks/` (`views.py`, `urls.py`, `twilio_validation.py`, `n8n_forward.py`)
  - `apps/qualification/tests/` (~25 test modules), `apps/webhooks/tests/test_twilio_whatsapp_inbound.py`
  - `requirements.txt`, `.env.example`
  - Existing architecture notes under `docs/architecture/` (read for context only; not modified)
- **Commands used for inspection (read-only):**
  - `git status --short`, `git branch --show-current`, `git rev-parse --short HEAD`, `git diff --name-only`
  - `find apps config -type f | sort`
  - `grep` for `APIView`, `REST_FRAMEWORK`, `request.data`, `except Exception`, E.164/phone patterns, logging helpers, auth headers, `PUBLIC_MEDIA_BASE_URL`
  - Direct file reads of modules listed above
- **Verification limitations:**
  - **Tests not executed** in this read-only audit (`Not executed in this read-only audit.`)
  - **Runtime flows not exercised** (n8n, Twilio live webhooks, OpenRouter, Deepgram, Supertonic, public media fetch)
  - Static inspection only; multi-process deployment behavior inferred from code structure

---

## Executive Summary

- **Overall architecture assessment:** The project has completed a meaningful, contract-preserving migration of internal JSON qualification endpoints to thin DRF `APIView` classes with serializers, a shared permission, typed error responses, and service-layer orchestration. Domain extraction logic, conversation flow, and provider HTTP clients remain appropriately separated. Twilio inbound webhook and public binary media delivery correctly remain Django function views.
- **DRF architecture score:** **8/10**
- **Django best-practice score:** **7.5/10**
- **Reusability score:** **7/10**
- **Testability score:** **9/10**
- **Security/operational safety score:** **8/10**
- **Whether a rewrite is recommended:** **No**
- **Whether incremental improvements are recommended:** **Yes** — focused on removing legacy duplication, hardening production state persistence, and retiring compatibility bridges once tests migrate

---

## Current Architecture Map

### API layer

| Route | Handler | Style |
|---|---|---|
| `POST /api/internal/qualification/extract/` | `ExtractAPIView` | DRF `APIView` |
| `POST /api/internal/qualification/render-audio/` | `RenderAudioAPIView` | DRF `APIView` |
| `POST /api/webhooks/twilio/whatsapp-inbound/` | `twilio_whatsapp_inbound` | Django function view |
| `GET/HEAD /media/whatsapp_voice_replies/<uuid>/` | `whatsapp_voice_reply_media` | Django function view |

`apps/qualification/urls.py` wires extract and render-audio to DRF views. `config/urls.py` mounts webhooks, internal qualification APIs, and public media.

### Service layer

- **`ExtractService`** (`services/extract_service.py`) — idempotency cache lookup, text vs voice message resolution, `VoiceNoteTranscriptionService`, `handle_qualification_turn`, `finalize_turn_response`
- **`VoiceNoteTranscriptionService`** (`services/transcription_service.py`) — Twilio media download, Deepgram transcription, voice-note logging
- **`RenderAudioService`** (`services/render_audio_service.py`) — TTS text-length validation, `render_whatsapp_voice_reply_safe`, response dict assembly
- **`ExtractionService`** (`services/extraction_service.py`) — post-OpenRouter parse → phone guard → confidence filter pipeline

### Domain layer

Pure modules: `extractor.py`, `filtering.py`, `phone_confirmation.py`, `conversation_flow.py`, `conversation_state.py`, `schema.py`, `prompts.py`, `channels.py`, `models.py` (dataclasses), `domain/validators.py` (E.164).

### Integration layer

- **`integrations/openrouter.py`** — HTTP transport, timeout handling, provider envelope extraction
- **`openrouter_client.py`** — compatibility facade delegating to transport + `ExtractionService`
- **`twilio_media.py`**, **`deepgram_client.py`**, **`supertonic_client.py`** — provider HTTP with typed exceptions
- **`apps/webhooks/n8n_forward.py`** — n8n outbound form POST from Twilio webhook

### Function-based webhook/media boundaries

Documented in `docs/architecture/drf-function-view-boundaries.md` (pre-existing). Twilio webhook: signature validation → n8n forward. Media endpoint: UUID validation → file lookup/TTL → `FileResponse`/`HttpResponse`.

### Test structure

~5,900 lines across `apps/qualification/tests/` plus webhook tests. Layers covered:

- Serializer parity vs legacy parsers (`test_extract_serializers.py`, `test_render_audio_serializers.py`)
- DRF view contracts (`test_extract_api_view.py`, `test_render_audio_api_view.py`)
- Legacy endpoint regression (`test_internal_extract_endpoint.py`, `test_render_audio_endpoint.py`)
- Cross-endpoint error contracts (`test_api_error_contracts.py`, `internal_api_test_helpers.py`)
- Permissions/exceptions (`test_api_permissions.py`)
- Services (`test_extract_service.py`, `test_transcription_service.py`, `test_render_audio_service.py`)
- Provider clients (`test_openrouter_client.py`, `test_openrouter_transport.py`, `test_extraction_service.py`)
- Twilio webhook (`test_twilio_whatsapp_inbound.py`)
- Public media (`test_whatsapp_audio_media.py`, integration cases in render-audio endpoint tests)

---

## DRF Assessment

### APIViews

**`ExtractAPIView`** and **`RenderAudioAPIView`** (`api/views.py`) are appropriately thin:

- Configuration guard in `dispatch()` before permissions (503 when `N8N_QUALIFICATION_API_SECRET` is blank)
- Serializer validation → service call → response serializer
- Typed exception → status/body mapping via `error_response()`
- Structured logging via `api/logging.py`

**Concerns:**

- **`ExtractAPIView.perform_authentication`** sets `request._user = None` and `request._auth = None` (lines 103–107) because `django.contrib.auth` is not installed. This uses private DRF request attributes and is a deliberate workaround, not idiomatic DRF auth configuration.
- **`RenderAudioAPIView.perform_authentication`** is an empty override (lines 197–198) — inconsistent with extract’s explicit `_user` assignment; both avoid session auth but differ in mechanism.
- **`ExtractAPIView`** imports `QualificationTurnRequest` and `_is_openrouter_timeout_error` from legacy `views.py` (lines 60–63), coupling the DRF layer to a module intended as legacy parser/logging compatibility.

Neither APIView contains OpenRouter, Deepgram, or Supertonic HTTP calls directly — good separation.

### Serializers

**Strengths:**

- `ExtractRequestSerializer` and `RenderAudioRequestSerializer` mirror legacy `_parse_extract_request()` / `_parse_render_audio_request()` with `trim_whitespace=False` and `initial_data`-driven validation for parity (`api/serializers.py`).
- `ExtractResponseSerializer.to_representation()` omits `transcript` when absent in instance (lines 227–231) — preserves text-channel omission contract.
- Business rules (TTS length, OpenRouter extraction, confidence filtering) remain outside request serializers.

**Risks:**

- `TWILIO_INBOUND_MESSAGE_SID_PATTERN` is compiled separately in `api/serializers.py` (line 30) and `views.py` (line 37) — duplicate regex, drift risk.
- Serializer field-level `validate_whatsapp_number` runs before `validate()` reads `initial_data`; parity is maintained via tests but the pattern is non-obvious for maintainers.

### Permissions

**`InternalWebhookSecretPermission`** (`api/permissions.py`) delegates to `is_internal_qualification_authorized()` which uses `secrets.compare_digest` (`internal_auth.py` lines 13–23). Appropriate and timing-safe.

**Configuration-before-auth ordering** is implemented in `dispatch()` on both APIViews (lines 85–101 extract, 179–195 render-audio): blank configured secret → 503 before `super().dispatch()` reaches permission checks. Matches n8n contract requirements.

### Authentication configuration

No `django.contrib.auth` in `INSTALLED_APPS`. DRF runs with `authentication_classes = []` on both APIViews. Extract uses private `_user` hack; render-audio uses empty `perform_authentication`. **Unable to confirm from static inspection** whether all DRF code paths behave identically across Django/DRF version upgrades without runtime regression tests.

### Exception mapping

**`error_response()`** (`api/exceptions.py` lines 21–28) returns `{"error": message}` — matches immutable public contract.

**`qualification_exception_handler`** maps `PermissionDenied` to `{"error": "Forbidden."}` (lines 37–40). For other DRF errors with only a `detail` key, it rewrites to `{"error": str(detail)}` (lines 42–43). Views already return generic `Invalid request.` for serializer failures, so serializer dictionaries should not leak — but any uncaught DRF validation path could expose non-contract `error` text via `str(detail)`.

Broad `except Exception` in both APIViews (extract lines 163–165, render-audio lines 258–264) maps to 500 with generic body — acceptable for public contract, but masks unexpected defects unless logged (logging is present).

### Response contract safety

DRF settings use JSON renderer/parser only (`config/settings.py` lines 29–38) — browsable API not exposed. Success responses pass through response serializers without adding default fields. Error responses use shared constants matching n8n expectations.

---

## Class-Based View Assessment

### Views correctly using class-based architecture

- **`ExtractAPIView`** — internal JSON POST, serializer validation, service orchestration, contract errors
- **`RenderAudioAPIView`** — same pattern for TTS media URL generation

### Views that should remain function-based

| View | Evidence | Assessment |
|---|---|---|
| `twilio_whatsapp_inbound` (`webhooks/views.py`, 34 lines) | Form `request.POST`, Twilio signature, empty HTTP status responses | **Correctly function-based** |
| `whatsapp_voice_reply_media` (`media_views.py`, 42 lines) | `FileResponse`, HEAD semantics, binary `audio/ogg` | **Correctly function-based** |

### Views that are too large or mixed in responsibility

- **`apps/qualification/views.py`** (~235 lines) — no longer hosts live extract endpoint, but retains `_parse_extract_request()`, logging compatibility wrappers, `QualificationTurnRequest`, and re-exports `download_twilio_media` / `transcribe_audio` for test patch compatibility (`transcription_service.py` lines 39–45). Mixed legacy adapter + patch bridge role.
- **`apps/qualification/whatsapp_audio.py`** — combines storage, ffmpeg conversion, Supertonic orchestration, and public URL building. Acceptable for current scale but the largest non-test module in the qualification app.

No inappropriate use of ViewSets or model-backed CRUD detected.

---

## Function-Based View Boundary Assessment

### Twilio inbound webhook

**Evidence:** `apps/webhooks/views.py` → `validate_twilio_signature()` → `twilio_post_params()` → `forward_to_n8n()`.

- Uses Django `request.POST` (form-encoded), not `request.data`
- Does not use `InternalWebhookSecretPermission` or DRF parsers
- Returns empty bodies for 200/403/502
- `twilio_validation.py` logs message SID prefix only; tests assert no body/phone/signature leakage (`test_twilio_whatsapp_inbound.py`)

**Verdict:** Boundary is correct. DRF migration would add risk without benefit.

### Public WhatsApp audio media endpoint

**Evidence:** `media_views.py` → `is_valid_audio_id()` → `find_audio_file()` → `_file_is_expired()` → `FileResponse`/`HttpResponse`.

- Public, no internal secret
- UUID path converter + pattern validation
- TTL eviction on access
- Tests cover GET/HEAD/404/405 (`test_whatsapp_audio_media.py`, `test_render_audio_endpoint.py`)

**Verdict:** Boundary is correct. Uses private `_file_is_expired` from `whatsapp_audio.py` (line 8) — minor encapsulation leak but not an HTTP-layer concern.

---

## Service, Domain, and Integration Separation

### Strengths

- Clear pipeline: **APIView → serializer → service → domain/integration → response serializer**
- OpenRouter split: **`integrations/openrouter.py`** (HTTP) + **`ExtractionService`** (parse/filter/guard) + **`openrouter_client.py`** (facade)
- Services return plain `dict` / `str`, never `Response` or `JsonResponse`
- `qualification_turn.py` maps provider exceptions to `QualificationServiceUnavailableError` / `QualificationServiceRequestError` — stable API-layer mapping inputs
- Voice-note path isolates provider failures in `VoiceNoteTranscriptionService` with injectable collaborators for tests

### Risks

| ID | Evidence | Issue |
|---|---|---|
| SVC-01 | `conversation_state.py`, `message_idempotency.py` | In-memory dicts — not durable across processes/restarts |
| SVC-02 | `transcription_service.py` lines 39–45 | Default collaborators imported from legacy `views.py` for patch compatibility — service layer depends on HTTP legacy module |
| SVC-03 | `ExtractAPIView` lines 60–63 | DRF view imports types/helpers from `views.py` |
| SVC-04 | `openrouter_client.py` | Facade retained for backward-compatible imports and `urllib.request` patch paths — intentional but adds indirection |

### Boundary violations

No service returns HTTP response objects. No APIView performs OpenRouter HTTP directly. **Minor violation:** integration concerns (voice-note logging event names) are embedded in `VoiceNoteTranscriptionService` — acceptable given contract stability requirements.

---

## Reusability and Duplicate-Code Assessment

### Validation

| Area | Status | Evidence |
|---|---|---|
| E.164 anchored validation | **Centralized** | `domain/validators.py` used by serializers, extractor, conversation_flow, legacy `views.py` parser |
| E.164 in-message discovery | **Intentionally separate** | `phone_confirmation.py` `E164_IN_MESSAGE_PATTERN` (unanchored `findall`) |
| MessageSid regex | **Duplicated** | `api/serializers.py` line 30, `views.py` line 37 |
| Request parsing | **Duplicated (legacy)** | `views.py` `_parse_extract_request`, `render_audio_views.py` `_parse_render_audio_request` maintained for parity tests alongside DRF serializers |

### Logging

| Area | Status | Evidence |
|---|---|---|
| Internal API logging | **Centralized** | `api/logging.py` — JSON events, `message_sid_prefix`, `safe_failure_type` |
| Legacy wrappers | **Compatibility bridges** | `views.py` `_log_event`, `render_audio_views.py` `_log_event` delegate to `api/logging.py` with TODO comments |
| Voice-note logging | **Separate module** | `voice_note_logging.py` duplicates `_message_sid_prefix` (8-char prefix) — not yet unified with `api/logging.py` |

### Errors

**Centralized** in `api/exceptions.py` with constants reused by APIViews. Immutable public JSON documented and tested (`test_api_error_contracts.py`, `internal_api_test_helpers.py`).

### Provider handling

OpenRouter transport extracted. Twilio media, Deepgram, Supertonic remain dedicated `*_client.py` modules — appropriate, not over-abstracted.

### Compatibility wrappers

`openrouter_client.py`, `views.py` logging/transcription re-exports, `render_audio_views.py` parser — legitimate for incremental migration; should be retired with explicit test patch migration plan.

---

## Configuration and Deployment Assessment

### DRF settings

```python
# config/settings.py
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "EXCEPTION_HANDLER": "apps.qualification.api.exceptions.qualification_exception_handler",
}
```

Browsable API disabled — good. Global exception handler installed — good for `PermissionDenied`; views still use explicit `error_response()` for most paths.

### Public media URL behavior

- `PUBLIC_MEDIA_BASE_URL` from environment (`.env.example` line 27, `settings.py` line 173)
- `build_public_media_url()` raises `RenderAudioServiceUnavailableError` when unset (`whatsapp_audio.py` lines 151–155)
- Media URLs embed UUID, not request_id — tested
- **Risk:** Stale tunnel URLs if `PUBLIC_MEDIA_BASE_URL` points to ephemeral dev tunnel while n8n/Twilio cache old URLs — operational, not code defect

### Tunnel/development considerations

`.env.example` documents `PUBLIC_MEDIA_BASE_URL` as empty by default. `SUPERTONIC_BASE_URL` defaults to localhost. `ALLOWED_HOSTS` defaults to localhost/127.0.0.1. Production requires explicit host and public media base configuration.

### Environment documentation

`.env.example` lists required integration variables without secret values. Timeout settings documented with positive-integer validation in `settings.py` (OpenRouter, Deepgram, Twilio media, Supertonic, n8n forward).

### Timeout configuration

Explicit per-provider timeouts loaded with `ImproperlyConfigured` guards — robust pattern.

---

## Logging and Security Assessment

### Secret safety

- Internal auth uses `secrets.compare_digest` (`internal_auth.py`)
- Twilio webhook logs exclude signature, body, phone (`test_twilio_whatsapp_inbound.py`)
- OpenRouter client tests assert safe error messages (`test_openrouter_client.py` `_assert_client_error_is_safe`)
- n8n forward sends secret in header; not logged in webhook tests

### PII safety

- API logging uses `message_sid_prefix` (8 chars) not full SID (`api/logging.py` lines 20–24)
- Voice-note logging excludes transcript and media URL (`voice_note_logging.py` docstring line 27)
- **Unable to confirm from static inspection** that no code path logs full customer messages in production without log review under failure scenarios

### Safe failure handling

Public errors are generic strings. `safe_failure_type()` logs exception class names only. Provider HTTP error bodies are not forwarded to clients (OpenRouter maps to generic messages).

### Observability quality

Structured JSON log events with consistent `event`, `timestamp`, `request_path` keys for internal APIs. Separate event namespaces for extract vs render-audio vs voice-note vs Twilio webhook — good for dashboard filtering.

---

## Test Coverage Assessment

### Existing coverage strengths

| Area | Evidence |
|---|---|
| Serializer parity | `test_extract_serializers.py`, `test_render_audio_serializers.py` |
| Permission delegation | `test_api_permissions.py` |
| 503-before-403 ordering | `test_extract_api_view.py`, `test_render_audio_api_view.py`, `test_api_error_contracts.py` |
| Exact error JSON | `test_api_error_contracts.py`, `internal_api_test_helpers.assert_public_error_contract` |
| No `detail` leakage | Asserted in contract tests |
| Extract/render endpoint contracts | DRF view tests + legacy endpoint tests |
| Text and voice paths | `test_internal_extract_endpoint.py`, `test_extract_api_view.py`, `test_voice_note_failures.py` |
| Idempotency | `test_extract_service.py`, `test_extract_api_view.py` |
| Twilio signature | `test_twilio_whatsapp_inbound.py` (10 tests) |
| n8n payload compatibility | `N8N_TEXT_PAYLOAD` / `N8N_VOICE_PAYLOAD` in serializer and endpoint tests |
| Public media GET/HEAD | `test_whatsapp_audio_media.py`, `test_render_audio_endpoint.py` |
| OpenRouter timeout | `test_openrouter_client.py`, `test_openrouter_transport.py`, `test_internal_extract_endpoint.py` |
| Supertonic/ffmpeg failures | `test_render_audio_endpoint.py`, `test_render_audio_service.py` |

### Missing coverage (static assessment)

| Gap | Notes |
|---|---|
| Global DRF exception handler paths other than `PermissionDenied` | Limited direct tests for `detail` → `error` rewrite edge cases |
| Multi-worker idempotency / conversation persistence | In-memory stores not integration-tested for production topology |
| `RenderAudioAPIView` vs `ExtractAPIView` auth workaround parity | No explicit test that render-audio dispatch survives without `django.contrib.auth` |
| CI evidence in repo | **Not executed in this read-only audit** — prior docs reference pytest; no CI config reviewed here |

### Runtime verification still required

See **Runtime Verification Checklist** below. All items: **Needs runtime verification — not executed during this read-only audit.**

---

## Findings by Priority

### Critical

*None identified from static inspection.* Public error contracts, permission ordering, and webhook boundaries appear correctly implemented with strong automated test intent in the repository.

### High

#### F-H01 — In-memory conversation and idempotency state

- **Severity:** High (production multi-process / restart)
- **Evidence:** `conversation_state.py` (`_conversations` dict), `message_idempotency.py` (`_turn_responses_by_message_sid` dict)
- **Why it matters:** Multiple Gunicorn/uWSGI workers or process restarts lose qualification progress and MessageSid idempotency guarantees n8n/Twilio may rely on.
- **Risk if not addressed:** Duplicate OpenRouter calls, inconsistent replies, lost qualification progress after deploy.
- **Recommended fix:** Introduce durable storage (Redis, database) behind existing function interfaces; preserve dict-shaped API for callers.
- **Safe to apply incrementally:** Yes — behind adapters with feature flag
- **Required tests before implementation:** Multi-request idempotency integration test; restart simulation; existing `test_extract_service.py` idempotency tests as baseline

#### F-H02 — DRF view coupling to legacy `views.py`

- **Severity:** High (maintainability)
- **Evidence:** `ExtractAPIView` imports `QualificationTurnRequest`, `_is_openrouter_timeout_error` from `views.py` (lines 60–63); `VoiceNoteTranscriptionService` defaults to `views.download_twilio_media` / `views.transcribe_audio` (lines 39–45)
- **Why it matters:** Prevents clean retirement of legacy module; obscures dependency direction.
- **Risk if not addressed:** Accidental reintroduction of HTTP logic into `views.py`; harder DRF layer testing.
- **Recommended fix:** Move shared types to `services/` or `api/types.py`; move default media/transcription callables to `integrations/` or `services/transcription_service.py` module-level defaults.
- **Safe to apply incrementally:** Yes
- **Required tests:** Existing transcription and extract API tests; update patch paths deliberately

#### F-H03 — `PUBLIC_MEDIA_BASE_URL` operational dependency

- **Severity:** High (deployment)
- **Evidence:** `whatsapp_audio.build_public_media_url()` (lines 151–155); `.env.example` empty default
- **Why it matters:** Render-audio returns URLs n8n/Twilio must fetch; wrong or stale base URL breaks voice replies silently after tunnel rotation.
- **Risk if not addressed:** 404 on media fetch; broken voice qualification flow in production.
- **Recommended fix:** Deployment checklist + startup validation command; document stable public URL requirement (not tunnel-specific in production).
- **Safe to apply incrementally:** Yes (ops/docs/management command)
- **Required tests:** Existing render-audio unavailable tests; add startup check test if command added

### Medium

#### F-M01 — Duplicated `TWILIO_INBOUND_MESSAGE_SID_PATTERN`

- **Severity:** Medium
- **Evidence:** `api/serializers.py` line 30, `views.py` line 37
- **Why it matters:** Regex drift could break serializer/parser parity.
- **Recommended fix:** Single constant in `domain/` or `channels.py`; import in both places.
- **Incremental:** Yes | **Tests:** `test_extract_serializers.py` parity tests

#### F-M02 — Duplicated `message_sid_prefix` in voice-note logging

- **Severity:** Medium
- **Evidence:** `voice_note_logging.py` lines 12–15 vs `api/logging.py` lines 20–24
- **Why it matters:** Redaction format could diverge.
- **Recommended fix:** Import `message_sid_prefix` from `api/logging.py` in voice-note module (or shared `logging_utils`).
- **Incremental:** Yes | **Tests:** `test_api_logging.py`, voice-note failure tests

#### F-M03 — `ExtractAPIView` private DRF `_user` assignment

- **Severity:** Medium
- **Evidence:** `api/views.py` lines 103–107
- **Why it matters:** Relies on DRF internals; may break on DRF upgrades; inconsistent with render-audio approach.
- **Recommended fix:** Document pattern; align both APIViews on same approach; consider minimal custom `authentication_classes` no-op class.
- **Incremental:** Yes | **Tests:** Full extract API test suite

#### F-M04 — `qualification_exception_handler` generic `detail` rewrite

- **Severity:** Medium
- **Evidence:** `api/exceptions.py` lines 42–43
- **Why it matters:** Uncaught DRF errors could return non-contract `error` strings via `str(detail)`.
- **Recommended fix:** Map only known cases; default unknown DRF errors to `Internal server error.` for internal APIs.
- **Incremental:** Yes | **Tests:** `test_api_permissions.py` + new handler edge-case tests

#### F-M05 — Legacy parsers retained alongside serializers

- **Severity:** Medium
- **Evidence:** `views.py` `_parse_extract_request`, `render_audio_views.py` `_parse_render_audio_request`
- **Why it matters:** Dual maintenance burden; parity tests mitigate but do not eliminate drift risk.
- **Recommended fix:** After confidence period, deprecate parsers; keep serializer as sole validation source.
- **Incremental:** Yes | **Tests:** Existing parity tests must pass until removal

#### F-M06 — `openrouter_client.py` compatibility facade

- **Severity:** Medium
- **Evidence:** `openrouter_client.py` entire module; TODO in docstring
- **Why it matters:** Extra indirection for new contributors; patch paths depend on facade `urllib.request`.
- **Recommended fix:** Migrate callers/tests to `integrations.openrouter` + `ExtractionService`; remove facade.
- **Incremental:** Yes | **Tests:** `test_openrouter_client.py`, grep patch paths

#### F-M07 — `media_views.py` imports private `_file_is_expired`

- **Severity:** Medium (encapsulation)
- **Evidence:** `media_views.py` line 8
- **Recommended fix:** Expose public `is_audio_file_expired(path)` in `whatsapp_audio.py`.
- **Incremental:** Yes | **Tests:** `test_whatsapp_audio_media.py`, render-audio media tests

#### F-M08 — Broad `except Exception` in APIViews

- **Severity:** Medium (observability)
- **Evidence:** `api/views.py` lines 163–165, 258–264
- **Why it matters:** Correct public contract but may hide bugs; relies on logging only.
- **Recommended fix:** Catch `QualificationTurnProcessingError` specifically where possible; log exception type (already via event); optional Sentry hook.
- **Incremental:** Yes

### Low

#### F-L01 — `RenderAudioRequestSerializer` accepts over-length text

- **Severity:** Low (by design)
- **Evidence:** `test_render_audio_serializers.py` `test_request_serializer_does_not_validate_text_length`; length enforced in `RenderAudioService`
- **Why it matters:** Documented split — serializer shape vs service business rule. Not a defect if intentional.
- **Recommended fix:** None required; keep documented.

#### F-L02 — `DATABASES = {}` — no ORM persistence

- **Severity:** Low (known architectural choice)
- **Evidence:** `config/settings.py` line 49
- **Why it matters:** Confirms state must be externalized for production scale.
- **Recommended fix:** Part of F-H01 if persistence needed.

#### F-L03 — Import order in `media_views.py`

- **Severity:** Low (style)
- **Evidence:** `require_http_methods` imported after `whatsapp_audio` imports (lines 7–14)
- **Recommended fix:** Style cleanup only.

#### F-L04 — Multiple architecture audit documents

- **Severity:** Low
- **Evidence:** `docs/architecture/drf-architecture-audit.md`, `drf-refactor-audit.md`, `drf-function-view-boundaries.md`
- **Recommended fix:** Consolidate into this review as canonical post-migration reference; archive or link older docs.

#### F-L05 — `pytest_django` plugin naming in docs/commands

- **Severity:** Low
- **Evidence:** Some docs say `pytest -p pytest_django`; project tests use `pytest_django.plugin` in practice per working tree
- **Recommended fix:** Standardize documented test command in README/Makefile when next touched.

---

## Good Practices Already Implemented

1. **Thin DRF APIViews with service delegation** — `api/views.py` `ExtractAPIView` / `RenderAudioAPIView` post handlers are ~50 lines each, mapping exceptions to stable JSON.
2. **Immutable public error contract** — constants in `api/exceptions.py`; tested with exact dict equality (`test_api_error_contracts.py`).
3. **503-before-403 configuration guard** — `dispatch()` override on both internal APIViews before `super().dispatch()`.
4. **JSON-only DRF configuration** — no browsable API in `REST_FRAMEWORK` settings.
5. **Serializer parity testing** — `test_extract_serializers.py` compares against legacy parsers field-for-field.
6. **OpenRouter transport/service split** — `integrations/openrouter.py` + `services/extraction_service.py` + facade (`openrouter_client.py`).
7. **Centralized E.164 validation** — `domain/validators.py` shared across serializers and domain modules.
8. **Shared internal API logging** — `api/logging.py` with SID prefix redaction and typed failure labels.
9. **Correct function-view boundaries** — Twilio webhook and public media (`webhooks/views.py`, `media_views.py`).
10. **Strong n8n payload fixtures** — `N8N_TEXT_PAYLOAD` / `N8N_VOICE_PAYLOAD` reused across serializer and endpoint tests.
11. **Injectable service collaborators** — `ExtractService`, `VoiceNoteTranscriptionService`, `RenderAudioService` accept mocks in tests.
12. **Safe Twilio webhook logging** — `twilio_validation.py` structured events without PII; tested in `test_twilio_whatsapp_inbound.py`.
13. **Timing-safe internal secret comparison** — `secrets.compare_digest` in `internal_auth.py`.
14. **Provider timeouts validated at settings load** — positive integer guards for OpenRouter, Deepgram, Twilio, Supertonic, n8n.

---

## Recommended Improvement Roadmap

### Phase 1 — Critical/High

1. **Plan durable state for conversation + MessageSid idempotency** (F-H01) without changing public API shapes.
2. **Decouple DRF views and transcription service from legacy `views.py`** (F-H02) — move types and default callables.
3. **Harden `PUBLIC_MEDIA_BASE_URL` deployment validation** (F-H03) — management check, runbook, avoid tunnel URLs in production.

### Phase 2 — Medium

1. Consolidate duplicated regex and logging helpers (F-M01, F-M02).
2. Align DRF authentication workaround across both APIViews (F-M03).
3. Tighten global exception handler for unknown DRF errors (F-M04).
4. Retire legacy parsers when parity confidence is sufficient (F-M05).
5. Migrate off `openrouter_client` facade (F-M06).
6. Public TTL helper for media views (F-M07).

### Phase 3 — Low / Optional

1. Documentation consolidation (F-L04).
2. Style/import cleanup (F-L03).
3. Standardize pytest invocation in project docs (F-L05).

*No code provided in this section — implementation guidance only.*

---

## Intentionally Deferred or Not Recommended

| Change | Why defer |
|---|---|
| Migrate Twilio webhook to DRF | Form-encoded contract + signature validation; no JSON serializer benefit (`webhooks/views.py`) |
| Migrate public media endpoint to DRF | Binary `FileResponse`; DRF JSON stack adds no value (`media_views.py`) |
| Generic LLM provider abstraction | OpenRouter integration already split; further abstraction premature (`integrations/openrouter.py`) |
| ViewSets / routers | No model-backed CRUD resources (`DATABASES = {}`) |
| Full rewrite | Contract tests and incremental migration already invested; rewrite risk >> benefit |

---

## Runtime Verification Checklist

| Flow | Status |
|---|---|
| n8n text message flow → extract endpoint | Needs runtime verification — not executed during this read-only audit |
| n8n voice-note flow → extract with transcription | Needs runtime verification — not executed during this read-only audit |
| Twilio outbound text delivery | Needs runtime verification — not executed during this read-only audit |
| Twilio outbound audio delivery (render-audio URL) | Needs runtime verification — not executed during this read-only audit |
| Public media URL fetch returns `audio/ogg` | Needs runtime verification — not executed during this read-only audit |
| OpenRouter timeout → 502 + `qualification_internal_upstream_timeout` log | Needs runtime verification — not executed during this read-only audit (unit tests exist) |
| Deepgram failure → 503 extract response | Needs runtime verification — not executed during this read-only audit (unit tests exist) |
| Supertonic failure → 503 render-audio response | Needs runtime verification — not executed during this read-only audit (unit tests exist) |

---

## Final Verdict

- **Is the project following DRF best practices?** **Mostly yes** for internal JSON APIs: thin APIViews, serializers, permissions, explicit error responses, JSON-only settings. Minor deviations (private `_user` hack, legacy module imports) are documented technical debt, not architectural rejection of DRF.
- **Is the use of class-based views appropriate?** **Yes** for extract and render-audio internal endpoints.
- **Are function-based views appropriately retained?** **Yes** for Twilio inbound webhook and public WhatsApp audio media.
- **Is the code sufficiently reusable?** **Adequate and improving** — domain validators, API logging, OpenRouter transport, and extraction service show good reuse; remaining duplication is mostly intentional compatibility scaffolding.
- **Top three recommended next actions:**
  1. **Externalize in-memory conversation and MessageSid idempotency** before multi-worker production deployment.
  2. **Remove DRF/service dependencies on legacy `views.py`** by relocating shared types and default integration callables.
  3. **Operationalize `PUBLIC_MEDIA_BASE_URL`** with stable production URL validation and runbook — voice reply chain depends on it.

---

*End of read-only architecture review. No application files were modified to produce this document.*
