# Arabic Supertonic TTS Audit Report

## Overall Result
- **PARTIAL**
- The Django backend implements persisted-language TTS routing, Arabic configuration gating, HTTP 200 text fallback for all audited Arabic failure modes, English backward compatibility, and render-audio idempotency. Automated tests (547 total; 103 focused) all passed. Arabic TTS production enablement is **not** safe: `SUPERTONIC_ARABIC_VOICE` is unset in the local environment, the verification management command was not run against a live Supertonic instance, and no manually listened Arabic sample exists in the repository. n8n fallback branching is documented but not evidenced in exported workflow files.

## Scope Audited
- Arabic TTS configuration
- Persisted language source of truth
- English compatibility
- Text fallback behavior
- Render-audio response contract
- Idempotency
- Arabic voice verification
- n8n integration readiness

## Actual Architecture Found
- **Conversation model:** `WhatsAppConversationSession` in `apps/qualification/models.py` — `language` field (`en` / `ar`, nullable).
- **Language resolver:** `get_conversation_language()` in `apps/qualification/domain/language.py` loads `WhatsAppConversationSession.language` via `get_or_create_conversation_session()`, then `normalize_conversation_language()` (null/invalid → `en`).
- **Render endpoint:** `POST /api/internal/qualification/render-audio/` — `RenderAudioAPIView` in `apps/qualification/api/views.py`, routed in `apps/qualification/urls.py`.
- **Request serializer:** `RenderAudioRequestSerializer` in `apps/qualification/api/serializers.py` (also legacy parser `_parse_render_audio_request` in `apps/qualification/render_audio_views.py`).
- **Response serializer:** `RenderAudioResponseSerializer` in `apps/qualification/api/serializers.py`.
- **Renderer service:** `RenderAudioService` in `apps/qualification/services/render_audio_service.py`.
- **Supertonic client:** `synthesize_wav()` in `apps/qualification/supertonic_client.py`; wrapped by `render_whatsapp_voice_reply_safe()` in `apps/qualification/whatsapp_audio.py` (WAV → OGG via ffmpeg, UUID storage under `media/whatsapp_voice_replies/`).
- **Configuration resolver:** `get_supertonic_voice_config()` and `SupertonicVoiceConfig` in `apps/qualification/domain/supertonic_config.py`.
- **API response formatter:** `_build_success_response()` / `_build_fallback_response()` in `RenderAudioService`; serialized by `RenderAudioResponseSerializer`.
- **Existing error mapping:**
  - `InvalidRenderAudioRequestError` → HTTP 400 (`Invalid request.`)
  - Missing `N8N_QUALIFICATION_API_SECRET` at dispatch → HTTP 503 (pre-auth)
  - Auth failure → HTTP 403
  - `RenderAudioServiceUnavailableError` / `RenderAudioProcessingError` during TTS → HTTP **200** text fallback (not 503)
  - Unexpected exceptions in view → HTTP 500
- **Idempotency:** `render_audio_idempotency.py` — in-memory or Redis cache keyed by `request_id`.
- **Arabic verification:** `verify_arabic_supertonic_voice` management command in `apps/qualification/management/commands/verify_arabic_supertonic_voice.py`.

## Files Inspected
| File | Purpose | Findings |
|---|---|---|
| `apps/qualification/models.py` | `WhatsAppConversationSession` ORM model | `language` choices `en`/`ar`, nullable; unique `whatsapp_number` |
| `apps/qualification/domain/language.py` | Persisted language lookup | Session DB is authority via `get_conversation_language()` |
| `apps/qualification/domain/supertonic_config.py` | Voice config resolver | English always enabled; Arabic requires flag + voice; no silent F1 fallback for Arabic |
| `apps/qualification/services/render_audio_service.py` | TTS orchestration | Routes from persisted language; builds success/fallback payloads; caches by `request_id` |
| `apps/qualification/api/views.py` | `RenderAudioAPIView` | Thin DRF view; always returns 200 for service success/fallback dicts |
| `apps/qualification/api/serializers.py` | Request/response contract | Accepts `conversation_language` hint but does not use it for routing |
| `apps/qualification/supertonic_client.py` | Supertonic HTTP client | Sends `lang` to `/v1/tts`; maps failures to typed exceptions |
| `apps/qualification/whatsapp_audio.py` | Audio storage/conversion | OGG output; `RenderAudioServiceUnavailableError` / `RenderAudioProcessingError` |
| `apps/qualification/render_audio_idempotency.py` | Render idempotency | Redis or in-memory cache |
| `apps/qualification/render_audio_views.py` | Legacy parser helpers | Field allowlist; not the active view layer |
| `apps/qualification/urls.py` | URL routing | `render-audio/` → `RenderAudioAPIView` |
| `config/urls.py` | Root URLs | Mounts internal qualification + public media endpoint |
| `config/settings.py` | Django settings | `SUPERTONIC_*` vars loaded; Arabic disabled by default |
| `config/settings_test.py` | Test settings | Arabic TTS disabled in tests |
| `.env.example` | Env documentation | Documents English + Arabic Supertonic vars |
| `apps/qualification/management/commands/verify_arabic_supertonic_voice.py` | Manual Arabic verification | Uses sample phrase; writes WAV/OGG under `media/arabic_supertonic_verification/` |
| `docs/integrations/n8n/T3-11-whatsapp-text-voice-reply-routing.md` | n8n contract docs | Documents `fallback_to_text` IF branch and render-audio fields |
| `twilio-whatsapp-inbound.json` | Exported n8n workflow | Inbound webhook only; no render-audio / fallback branch |
| `apps/qualification/tests/test_arabic_supertonic_tts.py` | Arabic TTS integration tests | Covers routing, fallback, idempotency, lang hint ignored |
| `apps/qualification/tests/test_supertonic_config.py` | Resolver unit tests | All resolver scenarios covered |
| `apps/qualification/tests/test_render_audio_*.py` | Render-audio tests | Endpoint, service, serializer, API view coverage |
| `apps/qualification/tests/test_api_error_contracts.py` | Error contract tests | Confirms TTS failures map to 200 fallback, not 503 |

## Persisted Language Verification
| Requirement | Result | Evidence |
|---|---|---|
| Arabic session (`language == "ar"`) uses Arabic TTS config when enabled | **PASS** | `get_supertonic_voice_config("ar")` returns `voice=M1, lang=ar, enabled=True` when configured; `test_arabic_render_succeeds_when_enabled` calls `synthesize_wav(..., voice="M1", lang="ar")` |
| English session (`language == "en"`) uses English TTS config | **PASS** | `get_supertonic_voice_config("en")` returns `voice=F1, enabled=True`; `test_valid_request_produces_media_url_with_audio_ogg` |
| Incoming `lang` / `conversation_language` cannot force Arabic when persisted language is English | **PASS** | `RenderAudioService._resolve_conversation_language()` uses only `whatsapp_number` → DB; request `voice`/`lang` not passed to renderer; no test for English session + `lang=ar`, but code path is unambiguous |
| Persisted language wins on conflict; safe warning logged; no customer content/credentials logged | **PARTIAL** | `tts_lang_hint_mismatch` logged when request `lang` ≠ persisted language (`render_audio_service.py` L155–169); uses `request_id_prefix` only. **Gap:** `conversation_language` request field is accepted but not compared or logged on mismatch |
| Legacy English requests without `whatsapp_number` remain compatible | **PASS** | `_resolve_conversation_language()` defaults to `LANGUAGE_ENGLISH` when `whatsapp_number` is absent; `test_legacy_english_request_without_whatsapp_number_still_renders`, `test_valid_request_produces_media_url_with_audio_ogg` |
| Arabic rendering not enabled without reliable persisted session lookup | **PASS** | Without `whatsapp_number`, language defaults to `en`; Arabic TTS requires `conversation_language == "ar"` from DB lookup |

## Configuration Verification
| Requirement | Result | Evidence |
|---|---|---|
| English configuration remains functional | **PASS** | `SUPERTONIC_ENGLISH_VOICE` defaults to `F1`; English path always `enabled=True` |
| English voice variables backward compatible | **PASS** | `DEFAULT_SUPERTONIC_ENGLISH_VOICE = "F1"`; `.env.example` documents `SUPERTONIC_ENGLISH_VOICE=F1` |
| English does not require Arabic configuration | **PASS** | Arabic vars default off/empty; English tests pass with `SUPERTONIC_ARABIC_ENABLED=False` |
| Arabic TTS disabled by default | **PASS** | `SUPERTONIC_ARABIC_ENABLED = env.bool(..., default=False)` in `settings.py`; shell audit: `False` |
| Arabic voice ID not hardcoded in Python | **PASS** | Loaded from `SUPERTONIC_ARABIC_VOICE` env only; resolver returns `""` when unset |
| Arabic requires explicit enable flag | **PASS** | `enabled = bool(settings.SUPERTONIC_ARABIC_ENABLED and voice)` |
| Arabic requires configured Arabic-compatible voice | **PASS** | `test_missing_arabic_voice_returns_text_fallback` |
| Missing Arabic config → controlled text fallback, not 500/503 | **PASS** | Disabled/missing voice returns `status=text_fallback`, HTTP 200; no renderer call |
| Arabic does not silently use English F1 | **PASS** | `test_arabic_does_not_use_english_f1_when_arabic_voice_not_configured` |

**Settings shell audit (secrets redacted):**
```
MAX_TTS_TEXT_LENGTH: 800
SUPERTONIC_ARABIC_ENABLED: False
SUPERTONIC_ARABIC_VOICE: MISSING
SUPERTONIC_BASE_URL: SET
SUPERTONIC_ENGLISH_VOICE: SET
SUPERTONIC_TTS_TIMEOUT_SECONDS: 60
```

## Render-Audio Response Verification
| Scenario | Expected | Actual | Result |
|---|---|---|---|
| Arabic TTS disabled | HTTP 200, `fallback_to_text=true` | HTTP 200, `status=text_fallback`, `fallback_reason=arabic_tts_unavailable` | **PASS** |
| Arabic voice missing | HTTP 200, `fallback_to_text=true` | Same as above | **PASS** |
| Arabic Supertonic upstream failure | HTTP 200, `fallback_to_text=true` | HTTP 200; no provider error in body (`test_arabic_upstream_failure_returns_text_fallback`) | **PASS** |
| Arabic invalid audio output (ffmpeg) | HTTP 200, `fallback_to_text=true` | HTTP 200, `arabic_tts_unavailable` | **PASS** |
| No raw provider errors in API response | Sanitized | `Supertonic` string absent from response body in failure tests | **PASS** |
| No keys/tokens/credentials/storage internals exposed | Sanitized | Public `media_url` only on success; fallback returns null URLs | **PASS** |
| Voice not sent when `fallback_to_text=true` | n8n must branch | Backend returns null `media_url`/`audio_url`; documented n8n IF on `fallback_to_text` | **PASS** (backend); **NOT VERIFIED** (n8n runtime) |
| English success response compatible | Legacy fields preserved | Returns `media_url`, `content_type`, `audio_url`, `audio_content_type`, `request_id` | **PASS** |
| n8n-required fields not removed/renamed | Additive contract | Legacy + new fields coexist in `RenderAudioResponseSerializer` | **PASS** |
| Duplicate `request_id` no duplicate audio work | Idempotent cache | `test_duplicate_request_id_does_not_render_twice` — `synthesize_wav` called once | **PASS** |
| Audio content type | Audit template shows `audio/mpeg` | Actual: `audio/ogg` (WhatsApp voice requirement) | **PASS** (intentional deviation from template) |
| Arabic fallback returns 503 | Must not | All Arabic fallback tests assert HTTP 200 | **PASS** — no critical 503 regression |

**Successful audio response (actual):**
```json
{
  "status": "rendered",
  "fallback_to_text": false,
  "conversation_language": "ar",
  "media_url": "https://.../media/whatsapp_voice_replies/{uuid}/",
  "content_type": "audio/ogg",
  "audio_url": "https://.../media/whatsapp_voice_replies/{uuid}/",
  "audio_content_type": "audio/ogg",
  "request_id": "..."
}
```

**Text fallback response (actual):**
```json
{
  "status": "text_fallback",
  "fallback_to_text": true,
  "conversation_language": "ar",
  "fallback_reason": "arabic_tts_unavailable",
  "media_url": null,
  "content_type": null,
  "audio_url": null,
  "audio_content_type": null,
  "request_id": "..."
}
```

## Arabic Text Fallback Verification
- **Disabled Arabic TTS:** Unit + endpoint tests confirm HTTP 200, `fallback_to_text=true`, `fallback_reason=arabic_tts_unavailable`, renderer not called.
- **Missing Arabic voice:** Same controlled fallback when `SUPERTONIC_ARABIC_ENABLED=true` but `SUPERTONIC_ARABIC_VOICE=""`.
- **Arabic renderer failure:** `SupertonicRequestError` and `FfmpegConversionError` both map to text fallback with HTTP 200.
- **Invalid audio output:** `SupertonicResponseError` path covered in English tests; Arabic ffmpeg failure covered.
- **HTTP status behavior:** No 503 in any Arabic TTS fallback scenario. HTTP 503 only when `N8N_QUALIFICATION_API_SECRET` is blank at dispatch (configuration gate, not TTS failure).
- **Customer-facing effect:** Backend returns fallback payload; customer journey continues if n8n sends `reply_text` when `fallback_to_text=true` (documented, not runtime-verified).

## English Regression Verification
- **Existing English render behavior:** `test_valid_request_produces_media_url_with_audio_ogg` — full pipeline with mocked Supertonic/ffmpeg.
- **Existing English response contract:** `test_render_calls_renderer_with_configured_english_voice_and_returns_contract_payload`; legacy fields unchanged.
- **English TTS failure fallback:** `test_supertonic_failure_returns_safe_text_fallback`, `test_render_audio_unavailable_failure_maps_to_text_fallback_contract` — HTTP 200, `english_tts_unavailable`.
- **Test results:** All English render-audio tests passed (included in focused suite below).

## Arabic Voice Verification
- **Verification command/path found:** **YES** — `python manage.py verify_arabic_supertonic_voice`
- **Arabic sample phrase:** `مرحبًا، شكرًا لتواصلك معنا. كيف يمكننا مساعدتك؟` (constant `ARABIC_SAMPLE_PHRASE`)
- **Uses configured Arabic voice:** **YES** — reads `SUPERTONIC_ARABIC_VOICE`, calls `synthesize_wav(..., lang="ar")`
- **Generates test audio in controlled location:** **YES** — `media/arabic_supertonic_verification/`
- **Does not expose credentials:** **YES** — prints voice ID and paths only
- **Reports success/failure safely:** **YES** — `CommandError` on misconfiguration/failure
- **Does not claim pronunciation quality:** **YES** — stdout requires manual listening before enablement
- **Generated test audio evidence:** **NOT FOUND** — no `arabic_supertonic_*` files in repository; command run during audit exited: `SUPERTONIC_ARABIC_VOICE is not configured`
- **Manual listening status:** **NOT PERFORMED** — no human listening evidence
- **Arabic production enablement safe:** **NO** — enable flag is off; voice unconfigured; no verified sample

## n8n Readiness
- **Conclusion:** **Backend complete, n8n pending** (contract documented; live workflow not evidenced in repo)
- **Required render request fields:** Documented in `docs/integrations/n8n/T3-11-whatsapp-text-voice-reply-routing.md` — `text`, `request_id`, `whatsapp_number`, `conversation_language` (hint only)
- **Fallback IF branch requirement:** Documented as `{{ $json.fallback_to_text }}` equals `true` → send text reply
- **Implemented in code:** Full backend contract including `fallback_to_text`, `status`, `fallback_reason`, dual URL fields
- **Must still be configured manually in n8n:**
  - Voice route: `POST render-audio` after `reply_mode=voice`
  - IF node on `fallback_to_text`
  - Text fallback using original `reply_text` (not render-audio body)
  - Pass `whatsapp_number` on every Arabic voice render (required for persisted language lookup)
- **Repository evidence:** `twilio-whatsapp-inbound.json` contains only inbound webhook + payload inspection — no render-audio or fallback branch. Cannot verify n8n Cloud has been updated.

## Tests Run
| Command | Result |
|---|---|
| `.venv/bin/python manage.py makemigrations --check --dry-run` | **PASS** — No changes detected |
| Settings shell (SUPERTONIC/TTS/VOICE names, redacted) | **PASS** — Arabic disabled, voice missing, English SET |
| `python manage.py verify_arabic_supertonic_voice` | **FAILED (expected)** — `SUPERTONIC_ARABIC_VOICE is not configured` |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 DJANGO_SETTINGS_MODULE=config.settings_test .venv/bin/python -m pytest -p pytest_django -q` | **PASS** — 547 passed |
| Focused: `test_render_audio_*`, `test_arabic_supertonic_tts`, `test_supertonic_config`, `test_language_gate_routing`, `test_api_error_contracts` | **PASS** — 103 passed |

**Test classification:**
- Arabic Supertonic routing/fallback: **Unit test passed** (mocked Supertonic/ffmpeg)
- Live Supertonic integration: **Not run** (no live service in CI)
- Arabic voice verification command: **Service unavailable / manual verification required**
- n8n end-to-end fallback routing: **Manual verification required**

## Gaps and Risks
- **Arabic TTS production enablement blocked:** No configured `SUPERTONIC_ARABIC_VOICE`, no generated verification audio, no manual listening sign-off.
- **n8n fallback branch not in exported workflow:** Backend contract is ready; production customer journey depends on manual n8n IF node wiring.
- **`conversation_language` request hint ignored for routing (correct) but mismatch not logged:** Only `lang` field triggers `tts_lang_hint_mismatch`; n8n sends `conversation_language` per docs — silent ignore is safe but reduces observability.
- **No automated test for English persisted session + `lang=ar` / `conversation_language=ar` hints:** Code review indicates persisted language wins; test gap only.
- **Arabic voice render requires `whatsapp_number`:** Legacy requests without it always route English — documented in implementation report; n8n must always send `whatsapp_number` for Arabic customers.
- **Request `voice` field validated but unused for TTS routing:** Harmless for security (resolver controls voice) but could confuse operators expecting request override.
- **Not a critical blocker:** Arabic fallback scenarios do **not** return HTTP 503.

## Final Recommendation
**2. Ready only for Arabic text fallback; do not enable Arabic TTS.**

Enable Arabic text fallback in production once n8n `fallback_to_text` branching is wired. Keep `SUPERTONIC_ARABIC_ENABLED=false` until `verify_arabic_supertonic_voice` succeeds against a live Supertonic instance and a human approves the generated sample pronunciation.
