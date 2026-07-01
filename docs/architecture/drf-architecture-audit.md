# WebLead DRF Architecture Audit

## Review scope

- **Branch reviewed:** `feature/lead-qualification` (commit `e286614` baseline; working tree includes uncommitted T3.6 timeout changes)
- **Review date:** 2026-06-24
- **Files inspected:**
  - `requirements.txt`, `config/settings.py`, `config/urls.py`
  - `apps/webhooks/` (`views.py`, `urls.py`, `n8n_forward.py`, `twilio_validation.py`, tests)
  - `apps/qualification/` (views, render_audio_views, media_views, urls, internal_auth, qualification_turn, conversation_flow, openrouter_client, twilio_media, deepgram_client, supertonic_client, whatsapp_audio, domain modules, tests)
  - `.cursor/rules/django-drf-architecture.mdc`, `.cursor/rules/testing-security.mdc`
  - `.cursor/skills/django-drf-feature-development/SKILL.md`, `django-drf-api-feature/SKILL.md`, `django-api-review/SKILL.md`
  - `docs/architecture/drf-refactor-audit.md` (prior audit, for comparison)
- **Commands run:**
  - `python manage.py check` — pass (0 issues)
  - `python manage.py test` — 0 tests (project uses pytest, not Django test discovery)
  - `git diff --check` — pass
  - `git status` — modified qualification files + untracked `.cursor/`, `docs/architecture/`

---

## Executive summary

- **DRF status:** **Not installed** (not in `requirements.txt`; not in `INSTALLED_APPS`; no `REST_FRAMEWORK` settings)
- **Current API architecture rating:** **C+** — solid domain logic and contract tests; HTTP layer is pre-DRF function views with heavy manual validation
- **Reusability rating:** **C** — duplicated auth, logging, parsing, and regex patterns across view modules
- **Maintainability rating:** **C+** — `views.py` (~489 lines) is the primary maintenance risk; domain and integration clients are otherwise readable
- **Is a DRF refactor recommended?** **Yes** (incremental, contract-preserving)
- **Is a full rewrite recommended?** **No**

---

## What is already well structured

- **Domain extraction pipeline** — `extractor.py`, `schema.py`, `filtering.py`, `phone_confirmation.py` are pure, testable, and correctly separate from HTTP (`extractor.py` L122–177; `filtering.py` L14–47).
- **Conversation orchestration** — `qualification_turn.py` and `conversation_flow.py` own business flow; views should delegate more to services built from these modules.
- **Integration clients (mostly)** — `twilio_media.py`, `deepgram_client.py`, `supertonic_client.py` isolate HTTP with explicit timeouts and typed exceptions (e.g. `DeepgramTimeoutError`, `OpenRouterTimeoutError`).
- **Internal auth helper** — `internal_auth.py` uses `secrets.compare_digest` and a single header constant; ready to become a DRF permission class.
- **Contract regression tests** — `test_internal_extract_endpoint.py` (~798 lines), `test_render_audio_endpoint.py`, `test_twilio_whatsapp_inbound.py` lock n8n/Twilio behavior including exact error JSON and status codes.
- **Cursor guidance exists** — `.cursor/rules/django-drf-architecture.mdc` and `.cursor/skills/django-drf-feature-development/SKILL.md` define the target architecture (not yet implemented in code).
- **Twilio webhook view** — `apps/webhooks/views.py` (34 lines) is appropriately thin: validate signature → forward → map errors.

---

## Current DRF gaps

| Area | Current implementation | Gap | Recommended solution | Priority |
|---|---|---|---|---|
| DRF package | Absent from `requirements.txt` | No serializers, permissions, or API exception hooks | Add `djangorestframework`; minimal JSON-only `REST_FRAMEWORK` | High |
| Request validation | Manual `json.loads` + `_parse_*` in `views.py`, `render_audio_views.py` | Duplicated, not composable, not DRF-standard | `ExtractRequestSerializer`, `RenderAudioRequestSerializer` | High |
| Response formatting | Manual `dict` + `JsonResponse` | Response shape not declared in one place | `ExtractResponseSerializer`, `RenderAudioResponseSerializer`, `ErrorResponseSerializer` | High |
| Views | Function-based everywhere | Extract view mixes 6+ responsibilities | Thin `APIView` classes under `api/views/` | High |
| Permissions | `is_internal_qualification_authorized()` called inline | Duplicated 503-when-secret-missing in two views | `InternalWebhookSecretPermission` + optional `ServiceConfigured` check | Medium |
| Exception mapping | Per-view `try/except` blocks | Duplicated status/body/logging logic | `api/exceptions.py` + view-level handler or explicit mapper functions | Medium |
| OpenRouter client | HTTP + parse + guard + filter in one module | Integration mixed with domain pipeline | Split HTTP client from `ExtractionService` | Medium |
| Tests | `django.test.Client`, pytest | No DRF `APIClient`; no serializer unit tests | Add serializer tests; keep existing contract tests | Medium |
| URL modules | `apps/qualification/urls.py` at app root | Works today; not aligned with target `api/` package | Move to `api/urls.py` when views migrate | Low |
| Public media | `media_views.py` function view | Already thin | Keep function-based or lightweight `APIView` | Low |

---

## Serializer assessment

| Endpoint | Request serializer needed | Response serializer needed | Existing domain validation to keep | Priority |
|---|---|---|---|---|
| `POST /api/internal/qualification/extract/` | **`ExtractRequestSerializer`** — `whatsapp_number`, `input_channel`, `message`, `message_sid`, `media_url`, `media_content_type`; channel-conditional rules from `views.py` L55–66, L183–269 | **`ExtractResponseSerializer`** — `accepted_fields`, `rejected_fields`, `human_handoff_requested`, `next_field`, `reply_text`, `qualification_status`, `preferred_phone`, `reply_mode`, `send_booking_link`, `booking_link`, optional `transcript` | OpenRouter response parsing (`extractor.py`), confidence filter (`filtering.py`), conversation merge (`conversation_flow.py`) — **not** in serializers | High |
| `POST /api/internal/qualification/render-audio/` | **`RenderAudioRequestSerializer`** — `text`, `voice`, `lang`, `request_id` (rules in `render_audio_views.py` L41–76) | **`RenderAudioResponseSerializer`** — `media_url`, `content_type`, `request_id` | TTS length limits (`whatsapp_audio.validate_text_length`), Supertonic WAV validation — service/domain | High |
| `POST /api/webhooks/twilio/whatsapp-inbound/` | **None (form POST)** — not JSON; keep `request.POST` parsing in `twilio_validation.twilio_post_params` | **Empty 200 / 403 / 502** — no JSON body | Twilio signature validation stays outside DRF serializer layer | Low |
| `GET/HEAD /media/whatsapp_voice_replies/<uuid>/` | **Path UUID only** — validate via URL converter + `is_valid_audio_id` | **Binary `audio/ogg`** — not JSON serializer | File TTL and path lookup in `whatsapp_audio.py` | Low |

**Shared serializers**

- **`ErrorResponseSerializer`** — single `error` field; enforce exact strings: `"Invalid request."`, `"Forbidden."`, `"Qualification service request failed."`, `"Qualification service is unavailable."`, `"Internal server error."`

**Contract risk during migration:** High for extract/render-audio if serializer field names, optional-field behavior, or error strings change. Mitigate with existing fixtures (`N8N_TEXT_PAYLOAD`, `N8N_VOICE_PAYLOAD`) and unchanged `JsonResponse`/`Response` data dicts produced by serializers.

---

## Class-based view assessment

| Endpoint | Current style | Recommended style | Reason | Contract risk |
|---|---|---|---|---|
| `POST .../extract/` | Function `internal_qualification_extract` (`views.py` L410+) | **`APIView`** | Largest view; needs serializer + service injection; POST-only action endpoint | Medium — preserve status/body exactly |
| `POST .../render-audio/` | Function `internal_render_audio` (`render_audio_views.py` L79–126) | **`APIView`** | Same pattern as extract; smaller scope | Medium |
| `POST .../twilio/whatsapp-inbound/` | Function `twilio_whatsapp_inbound` (`webhooks/views.py` L18–33) | **Remain function-based** (or optional thin `APIView` later) | Already thin; form-encoded Twilio contract; DRF adds little value now | Low |
| `GET/HEAD .../media/.../<uuid>/` | Function `whatsapp_voice_reply_media` (`media_views.py` L17–41) | **Remain function-based** | File streaming; no JSON; clear and small | Low |

Do **not** introduce `ModelViewSet` — project has no ORM models and no CRUD resources (`DATABASES = {}`).

---

## Views that should remain function-based

| Endpoint/file | Reason |
|---|---|
| `apps/webhooks/views.py` → `twilio_whatsapp_inbound` | Thin (34 lines); form POST + empty HTTP responses; Twilio signature is not a DRF permission pattern |
| `apps/qualification/media_views.py` → `whatsapp_voice_reply_media` | Public binary file serve; `FileResponse`/`HttpResponse`; no request/response JSON contract |

---

## Thin-view and service-layer assessment

| Current file | Mixed responsibilities | Recommended service split | Priority |
|---|---|---|---|
| **`views.py` (~489 lines)** | Request parsing (L183–300), voice pipeline orchestration (`_resolve_turn_message` L304–394), logging (L93–180), auth/503 gates (L413–420), exception→HTTP mapping (L445–476), idempotency (L431–434, L484–486) | **`ExtractService.run_turn()`** — idempotency, voice resolution, call `handle_qualification_turn`, finalize channel response; **`VoiceNoteTranscriptionService`** — Twilio download + Deepgram; move logging to `api/logging.py` | **Critical** |
| **`render_audio_views.py` (~127 lines)** | Parsing (L41–76), auth, logging, exception mapping, response dict | **`RenderAudioService.render()`** wrapping `render_whatsapp_voice_reply_safe` | High |
| **`openrouter_client.py` (~171 lines)** | HTTP (L112–147) + `parse_extraction_json` + phone guard + filter (L154–168) | Keep HTTP in **`integrations/openrouter.py`**; move post-HTTP steps to **`services/extraction.py`** | Medium |
| **`whatsapp_audio.py` (~199 lines)** | Supertonic call, ffmpeg, filesystem, public URL | **`services/render_audio.py`** orchestrates; keep storage helpers in module or `integrations/` | Medium |
| **`qualification_turn.py`** | Good orchestration size | Rename/move to **`services/qualification_turn.py`** when `api/` package added | Low |

**Target call chain (extract endpoint):**

```text
ExtractAPIView
  → ExtractRequestSerializer
  → ExtractService.run_turn()
      → VoiceNoteTranscriptionService (if voice)
      → handle_qualification_turn() / qualification_turn service
      → finalize_turn_response() (channels domain)
  → ExtractResponseSerializer
```

---

## Integration and domain-layer assessment

| Current file | Correct layer? | Recommended location/role | Notes |
|---|---|---|---|
| `extractor.py` | **Yes — domain** | `domain/extraction.py` or keep at root | OpenRouter **response** validation; must stay out of DRF serializers |
| `schema.py` | **Yes — domain** | `domain/schema.py` | JSON schema for OpenRouter request only |
| `filtering.py` | **Yes — domain** | `domain/filtering.py` | Confidence threshold rules |
| `phone_confirmation.py` | **Yes — domain** | `domain/phone_confirmation.py` | Post-LLM guardrails |
| `conversation_flow.py` | **Yes — domain** | `domain/conversation_flow.py` | Questions, merge, completion |
| `channels.py` | **Yes — domain** | `domain/channels.py` | `reply_mode`, booking link fields |
| `conversation_state.py` | **Yes — domain** | `domain/conversation_state.py` | In-memory store |
| `qualification_turn.py` | **Service** | `services/qualification_turn.py` | Already acts as service |
| `twilio_media.py` | **Yes — integration** | `integrations/twilio_media.py` | |
| `deepgram_client.py` | **Yes — integration** | `integrations/deepgram.py` | |
| `openrouter_client.py` | **Partial** | Split HTTP vs extraction pipeline | |
| `supertonic_client.py` | **Yes — integration** | `integrations/supertonic.py` | |
| `webhooks/n8n_forward.py` | **Yes — integration** | `integrations/n8n_forward.py` | |
| `whatsapp_audio.py` | **Mixed** | Service + storage helpers | |
| `internal_auth.py` | **API concern** | `api/permissions.py` | |

---

## Code reuse and duplication findings

| Duplicate or mixed code | Evidence | Best reusable solution | Priority |
|---|---|---|---|
| Manual JSON request parsing | `views.py` `_parse_extract_request` L250+; `render_audio_views.py` `_parse_render_audio_request` L41–76 | **DRF serializers** | High |
| `_log_event` copy | `views.py` L93–99; `render_audio_views.py` L32–38 | **Shared logging helper** (`api/logging.py` or extend `voice_note_logging.py` pattern) | Medium |
| Internal auth + blank-secret 503 gate | `views.py` L413–420; `render_audio_views.py` L82–87 | **`InternalWebhookSecretPermission`** + **`QualificationServiceConfigured`** permission or mixin | Medium |
| Safe error `JsonResponse` mapping | Repeated blocks in both view files | **`api/exceptions.py`** mapper: `map_service_error(exc) -> (status, {"error": ...})` | Medium |
| E.164 phone regex | `views.py` L65; `extractor.py` L12; `conversation_flow.py` L31 | **`domain/validators.py`** single `E164_PHONE_PATTERN` | Low |
| MessageSid prefix logging | `views.py` L110–113; `voice_note_logging.py` L12–15 | **Shared `message_sid_prefix()`** in logging module | Low |
| Upstream timeout vs failure logging | `views.py` L136–180 (extract only) | **Generalize** for future provider timeouts in shared mapper | Low |
| OpenRouter post-HTTP pipeline | `openrouter_client.py` L154–168 | **`ExtractionService`** used by qualification turn | Medium |

---

## Permissions and exception handling assessment

| Area | Current state | Recommended DRF approach | Contract impact |
|---|---|---|---|
| `X-Internal-Webhook-Secret` | `internal_auth.is_internal_qualification_authorized()` (`internal_auth.py` L13–23) | **`InternalWebhookSecretPermission`** on extract + render-audio `APIView`; 403 body unchanged | **None** if permission returns same 403 JSON |
| Missing `N8N_QUALIFICATION_API_SECRET` | View returns 503 before auth check | **`QualificationServiceConfigured`** permission or `initial()` hook; same 503 body | **None** |
| Twilio `X-Twilio-Signature` | `validate_twilio_signature()` in webhook view | **Keep separate** — not DRF `permission_classes`; form POST webhook | **None** |
| Safe error responses | Hard-coded dicts in views | DRF `exception_handler` **or** explicit mapper returning exact strings | **Breaking if strings change** — mapper must be fixture-tested |
| OpenRouter timeout (T3.6) | `qualification_internal_upstream_timeout` log + 502 | Preserve in `ExtractAPIView` exception branch; same event name | **None** |
| n8n branching | Depends on 400/403/502/503/500 + exact `error` keys | Document mapper as contract; regression tests required | **High risk if refactored carelessly** |

---

## DRF test assessment

| Test area | Current coverage | Missing tests | Recommendation |
|---|---|---|---|
| Endpoint contracts | Strong — `test_internal_extract_endpoint.py`, `test_render_audio_endpoint.py`, `test_twilio_whatsapp_inbound.py` | — | Keep `django.test.Client` tests during migration; responses must match byte-for-byte |
| Serializer validation | None (no serializers) | Field rules, channel conditionals, extra keys, E.164, MessageSid | Add `test_extract_request_serializer.py`, `test_render_audio_request_serializer.py` |
| DRF `APIClient` | Not used | Optional after `APIView` migration | Can stay on `Client` if JSON identical |
| Service layer | Partial — `qualification_turn` tested via mocks | Dedicated `ExtractService`, `VoiceNoteTranscriptionService` tests | Add when services extracted from `views.py` |
| Integration clients | Good — `test_openrouter_client.py`, voice/deepgram/twilio tests | — | Keep mocking `urllib.request.urlopen` |
| Permissions | `test_internal_auth.py` | DRF permission class unit tests | Add `test_internal_webhook_secret_permission.py` |
| Exception mapping | Implicit in endpoint tests | Unit tests for `map_qualification_api_error()` | Add with Phase 2/3 |
| Test harness | pytest + `pytest-django`; `manage.py test` finds 0 tests | Fix `settings` fixture errors in render-audio tests; valid `Makefile` `test` target | Infrastructure — not DRF-specific but blocks CI confidence |

---

## Safe DRF implementation roadmap

### Phase 1 — DRF foundation

1. Add `djangorestframework` to `requirements.txt` (no endpoint changes).
2. Add `rest_framework` to `INSTALLED_APPS`; configure `REST_FRAMEWORK` with JSON renderer/parser only (disable browsable API in production).
3. Create scaffold only:
   - `apps/qualification/api/__init__.py`
   - `apps/qualification/api/permissions.py` — `InternalWebhookSecretPermission`
   - `apps/qualification/api/exceptions.py` — error body constants + mapper
   - `apps/qualification/services/__init__.py`
   - `apps/qualification/integrations/__init__.py` (optional re-exports)
4. Add permission smoke tests; fix pytest/Makefile harness.
5. **Rollback:** revert dependency and new empty packages; URLs unchanged.

### Phase 2 — Qualification extract endpoint

1. Add `ExtractRequestSerializer`, `ExtractResponseSerializer`, `ErrorResponseSerializer`.
2. Extract `VoiceNoteTranscriptionService` from `views._resolve_turn_message`.
3. Add `ExtractService` (idempotency, turn orchestration, `finalize_turn_response`).
4. Add `ExtractAPIView`; wire same URL `extract/` in `urls.py`.
5. Keep `internal_qualification_extract` as thin wrapper or remove after parity tests pass.
6. **Rollback:** point `urls.py` back to function view.

### Phase 3 — Render-audio endpoint

1. Add `RenderAudioRequestSerializer`, `RenderAudioResponseSerializer`.
2. Add `RenderAudioService`.
3. Add `RenderAudioAPIView`; same URL `render-audio/`.
4. **Rollback:** restore `render_audio_views.internal_render_audio`.

### Phase 4 — Shared cleanup

1. Consolidate logging helpers (`_log_event`, upstream timeout/failure).
2. Split `openrouter_client.py` HTTP from extraction service.
3. Centralize E.164 / MessageSid validators.
4. Optional: move `apps/qualification/urls.py` → `api/urls.py` with include from app urls.
5. Optional: thin `APIView` for webhooks only if team wants consistency (not required).

---

## Tasks that should not be refactored now

- **n8n workflow JSON** — manual fallback verification only
- **Twilio signature validation** — working; do not merge into DRF permissions
- **Public media endpoint** — remain function-based unless there is a clear win
- **OpenRouter response parsing (`extractor.py`)** — do not move into DRF serializers
- **Conversation domain rules** — do not rewrite during HTTP-layer migration
- **In-memory `conversation_state`** — persistence is a separate product decision
- **Database / ModelViewSet** — no models exist; defer until persistence is approved
- **Changing live JSON keys or error strings** — forbidden without explicit approval

---

## Suggested Git commit boundaries

1. `chore: add djangorestframework and api package scaffold` — Phase 1 only
2. `refactor(qualification): add extract serializers and ExtractService` — no URL switch
3. `refactor(qualification): migrate extract endpoint to DRF APIView` — URL unchanged; function view removed
4. `refactor(qualification): migrate render-audio to DRF APIView` — same pattern
5. `refactor(qualification): shared logging, permissions, openrouter client split` — Phase 4 cleanup

Each commit should run pytest contract suites for affected endpoints.

---

## Final verdict

- **Best first DRF task:** Phase 1 — install DRF, add `InternalWebhookSecretPermission`, error-body constants, and package scaffold **without switching any live endpoint**.
- **Biggest architecture issue:** `apps/qualification/views.py` (~489 lines) combines HTTP parsing, voice orchestration, logging, auth, exception mapping, and response shaping in one function-based module.
- **Expected benefit after refactor:** Thin, testable API layer; serializers as living documentation of n8n contracts; shared permissions and error mapping; safer incremental feature work without duplicating parse/logic blocks.
- **Confirmation that API contracts should remain unchanged:** **Yes.** All endpoint URLs, request/response JSON shapes, HTTP status codes, auth headers (`X-Twilio-Signature`, `X-Internal-Webhook-Secret`), and documented error strings must be preserved through migration. DRF is an internal structural improvement only.

### Live contract fields (must not change)

```text
accepted_fields, rejected_fields, reply_text, reply_mode,
send_booking_link, booking_link, qualification_status,
media_url, content_type, request_id
```
