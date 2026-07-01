# Arabic Language Support Complete Audit

## Overall Result
- **PARTIAL**
- The Django backend implements persisted `WhatsAppConversationSession.language` as the authority for language gate routing, bilingual qualification messages, OpenRouter Arabic prompt augmentation, Deepgram language-aware transcription, and Arabic Supertonic TTS with HTTP 200 text fallback. Automated tests pass (547 total; 133 language-focused). Two planned capabilities are **not implemented**: Arabic/Persian phone-digit normalization and mid-conversation language-change commands. n8n production wiring is documented only in part; exported workflow JSON does not include language gate, `awaiting_language_selection`, or TTS fallback branches. Twilio Console Content SID validity and live delivery cannot be verified from the repository. Arabic TTS must remain disabled until `SUPERTONIC_ARABIC_VOICE` is configured and a sample is manually approved.

## Final Deployment Recommendation
**2. Ready for Arabic text and Arabic voice-note transcription, but Arabic TTS remains disabled.**

Backend text and voice-note paths are implemented and tested with mocks. Production rollout still requires Twilio Content configuration, n8n workflow updates, live Deepgram validation, and keeping `SUPERTONIC_ARABIC_ENABLED=false` until Arabic voice quality is manually approved.

## Scope Audited
- Twilio language selector
- Persisted language model
- Inbound button payload handling
- Language gate order
- n8n stateless design
- English/Arabic message catalog
- OpenRouter Arabic prompt routing
- Arabic/Persian phone digits
- Arabic Deepgram routing
- Arabic TTS and text fallback
- Language-change commands
- Tests and operational readiness

## Actual Architecture Found
| Layer | Actual file/class/service | Findings |
|---|---|---|
| Conversation model | `apps/qualification/models.py` → `WhatsAppConversationSession` | `language` (`en`/`ar`, nullable), `language_selected_at`, unique `whatsapp_number` |
| Session helpers | `apps/qualification/services/conversation_session_service.py` | `get_or_create_conversation_session()`, `persist_selected_language()`, Redis lazy English backfill for in-flight leads |
| Language reader | `apps/qualification/domain/language.py` → `get_conversation_language()` | DB session + `normalize_conversation_language()` (null/invalid → `en`) |
| Language parser | `apps/qualification/domain/language_selection.py` → `resolve_selected_language()` | `lang_en`/`lang_ar` buttons; typed fallbacks; button wins over body |
| Language gate | `apps/qualification/services/language_gate_service.py` → `LanguageGateService` | Runs before OpenRouter/Deepgram; sends picker or local first question |
| Extract orchestration | `apps/qualification/services/extract_service.py` → `ExtractService.run_turn()` | Idempotency → gate → transcription → OpenRouter |
| Extract API | `apps/qualification/api/views.py` → `ExtractAPIView` | Returns raw JSON for `awaiting_language_selection`; gate errors 503/502 |
| Twilio inbound edge | `apps/webhooks/views.py` → `twilio_whatsapp_inbound` | Signature validate + raw forward to n8n only; no language logic |
| Twilio inbound serializer | `apps/webhooks/serializers.py` → `TwilioInboundSerializer` | Maps `ButtonPayload`/`ButtonText`/`ButtonType`/media fields to extract JSON |
| Twilio language picker | `apps/qualification/integrations/twilio_language_picker.py` → `send_language_picker()` | Twilio Content API via `TWILIO_LANGUAGE_PICKER_CONTENT_SID` |
| Message catalog | `apps/qualification/domain/messages.py` | Bilingual `QUALIFICATION_MESSAGES` for 11 keys |
| Qualification flow | `apps/qualification/conversation_flow.py` | Field order: project_type → requirements → referral_source → whatsapp_confirmed → preferred_phone |
| OpenRouter prompts | `apps/qualification/prompts.py` → `build_extraction_system_prompt()` | Appends `ARABIC_CONVERSATION_INSTRUCTIONS` when language is `ar` |
| Phone validation | `apps/qualification/domain/validators.py` → `is_valid_e164_phone_number()` | ASCII E.164 only; no Eastern digit normalization |
| Deepgram resolver | `apps/qualification/domain/deepgram_config.py` → `get_deepgram_transcription_config()` | English/Arabic model+language from settings |
| Transcription service | `apps/qualification/services/transcription_service.py` | Uses persisted `conversation_language` |
| TTS config | `apps/qualification/domain/supertonic_config.py` → `get_supertonic_voice_config()` | Arabic requires enable flag + voice env |
| Render audio | `apps/qualification/services/render_audio_service.py` → `RenderAudioService` | Persisted language routing; HTTP 200 text fallback |
| Arabic voice verify | `apps/qualification/management/commands/verify_arabic_supertonic_voice.py` | Manual sample generation command |
| Migrations | `0001_initial_whatsapp_conversation_session.py`, `0002_backfill_conversation_language_en.py` | Create table; backfill null → `en` |
| n8n docs | `docs/integrations/n8n/T3-11-*.md`, `LLM-5-*.md`, `docs/language-selection-routing-implementation-report.md` | Partial/overlapping contracts; no workflow export for full flow |

## Requirement Status Matrix
| # | Requirement | Status | Evidence | Remaining Work |
|---|---|---|---|---|
| 1 | Persisted `WhatsAppConversationSession.language` is authority | **COMPLETE WITH EVIDENCE** | `get_conversation_language()`, gate/TTS/Deepgram/prompts all read DB | n8n must pass `whatsapp_number` |
| 2 | Twilio language selector for new customers | **BACKEND COMPLETE, MANUAL WORK PENDING** | `LanguageGateService`, `send_language_picker()` | Twilio Console Content + live send test |
| 3 | Language gate before OpenRouter/Deepgram | **COMPLETE WITH EVIDENCE** | `ExtractService.run_turn()` order; gate tests mock expensive calls | None (backend) |
| 4 | Bilingual qualification messages | **COMPLETE WITH EVIDENCE** | `domain/messages.py`; `test_qualification_messages.py` | Human Arabic copy review recommended |
| 5 | OpenRouter Arabic prompt routing | **COMPLETE WITH EVIDENCE** | `prompts.py`; `test_arabic_language_propagation.py` | Live OpenRouter Arabic quality test |
| 6 | Arabic Deepgram routing | **COMPLETE WITH EVIDENCE** | `deepgram_config.py`; `test_arabic_deepgram_voice_routing.py` | Live Deepgram Arabic audio test |
| 7 | Arabic TTS + text fallback | **PARTIALLY IMPLEMENTED** | `render_audio_service.py`; `test_arabic_supertonic_tts.py` | Configure voice; manual listen; n8n fallback branch |
| 8 | Arabic/Persian phone-digit normalization | **NOT IMPLEMENTED** | No digit transliteration in codebase | Implement + tests (critical) |
| 9 | Language-change command | **NOT IMPLEMENTED** | Deferred in implementation reports; no handler in code | Implement + tests |
| 10 | n8n stateless forwarding + branching | **NOT VERIFIABLE FROM REPOSITORY** | Docs only; `twilio-whatsapp-inbound.json` incomplete | Manual n8n Cloud workflow work |
| 11 | Automated test coverage | **COMPLETE WITH EVIDENCE** | 547 tests pass | Add phone-digit + language-change tests when built |

## Twilio Language Selector
| Requirement | Expected | Actual | Status |
|---|---|---|---|
| Content SID from environment | Not hardcoded | `settings.TWILIO_LANGUAGE_PICKER_CONTENT_SID` in `twilio_language_picker.py` | **PASS** |
| Env variable documented | `TWILIO_LANGUAGE_PICKER_CONTENT_SID` | Present in `.env.example` line 14 | **PASS** |
| WhatsApp sender from environment | Not hardcoded | `TWILIO_WHATSAPP_FROM_NUMBER` validated before send | **PASS** |
| Selector send helper | Twilio Content/Quick Reply | `send_language_picker()` uses `content_sid=` | **PASS** |
| New conversation, null language | Send selector only | `session.language is None` → `send_language_picker()` | **PASS** (unit test) |
| Existing English conversation | No selector | `test_existing_english_conversation_continues_qualification` | **PASS** |
| Existing Arabic conversation | No selector | No dedicated test; code path same as English when `language=ar` | **PARTIAL** |
| Selector response status | `awaiting_language_selection` | `build_awaiting_language_selection_response()` | **PASS** |
| No Deepgram/OpenRouter before selection | Blocked | `test_new_customer_text_sends_selector_without_openrouter`; voice-note equivalent | **PASS** |
| Twilio Console Content valid | Quick Reply `lang_en`/`lang_ar` | Not in repository | **MANUAL VERIFICATION REQUIRED** |
| Live WhatsApp delivery | Customer receives picker | Not in repository | **MANUAL VERIFICATION REQUIRED** |
| Actual Content SID value | Configured in deployment | Local env shows SET (value not disclosed) | **MANUAL VERIFICATION REQUIRED** |

## Persisted Language and Migration Safety
| Requirement | Expected | Actual | Status |
|---|---|---|---|
| New conversations start `language=None` | Yes | `create_conversation_session()`; `test_new_conversation_session_has_null_language` | **PASS** |
| Backfill existing null → English | Safe migration | `0002_backfill_conversation_language_en.py`; tests preserve explicit `ar` | **PASS** |
| Existing English customers not re-prompted | No selector | Backfill sets `en`; Redis lazy backfill for in-flight leads | **PASS** |
| Language constrained to `en`/`ar` | Model choices | `Language` TextChoices; `test_invalid_language_fails_validation` | **PASS** |
| `language_selected_at` stored | On selection | `persist_selected_language()` sets `timezone.now()` | **PASS** |
| Persisted in database | Not Redis-only | ORM table `qualification_whatsapp_conversation_session` | **PASS** |
| Used for text/voice/OpenRouter/Deepgram/TTS | Yes | Gate bypass path uses `get_conversation_language()` throughout | **PASS** |
| Null/invalid safe fallback | Default English | `normalize_conversation_language()` | **PASS** |
| Migrations valid | No pending | `makemigrations --check --dry-run` → No changes detected | **PASS** |
| No data loss / lead reset | Non-destructive | Backfill only updates `language` null rows; reverse preserves `language_selected_at` | **PASS** |

## Inbound Payload and Button Selection
| Requirement | Expected | Actual | Status |
|---|---|---|---|
| Accept `ButtonPayload` | Yes | `TwilioInboundSerializer`, `ExtractRequestSerializer` | **PASS** |
| Accept `ButtonText`, `ButtonType` | Yes | Both serializers | **PASS** |
| Accept `Body`, `From`, `MessageSid` | Yes | Required fields | **PASS** |
| Accept `MediaUrl0`, `NumMedia` | Yes | Voice-note channel mapping | **PASS** |
| `ButtonPayload` preferred | Over body | `resolve_selected_language()`; `test_valid_button_payload_overrides_conflicting_body` | **PASS** |
| `lang_en` → `en` | Yes | `LANGUAGE_BUTTONS` | **PASS** |
| `lang_ar` → `ar` | Yes | `LANGUAGE_BUTTONS` | **PASS** |
| Typed fallbacks (English/Arabic variants) | Exact matches | `LANGUAGE_TEXT_FALLBACKS`; parametrized resolver tests | **PASS** |
| Typed fallback does not override button | Yes | Resolver tests with conflicting body | **PASS** |
| Safe for non-button messages | Yes | Unknown body → `None`; standard text validates | **PASS** |
| Voice-note support preserved | Yes | `test_voice_note_message_validates_with_media_fields` | **PASS** |
| MessageSid idempotency | Active | `begin_idempotent_turn`; duplicate selector test | **PASS** |
| No duplicate selector on replay | Same SID cached | `test_duplicate_message_sid_does_not_send_duplicate_selector` | **PASS** |
| Webhook forwards raw Twilio fields to n8n | Stateless edge | `forward_to_n8n(params)` posts original form fields | **PASS** |
| n8n passes button fields to Django | Required for gate | Documented in language-selection report; serializer supports fields | **NOT VERIFIABLE FROM REPOSITORY** |

## Language-Gate and Latency Protection
| Scenario | Expected | Actual | Status |
|---|---|---|---|
| New customer text | Selector; no OpenRouter | `test_new_customer_text_sends_selector_without_openrouter` | **PASS** |
| New customer voice note | Selector; no download/Deepgram | `test_new_customer_voice_note_sends_selector_without_deepgram` | **PASS** |
| Customer taps English | Persist `en`; first English question | `test_lang_en_button_saves_language_and_starts_qualification` | **PASS** |
| Customer taps العربية | Persist `ar`; first Arabic question | `test_lang_ar_button_saves_arabic_and_starts_qualification` | **PASS** |
| Existing English customer text | Normal qualification | `test_existing_english_conversation_continues_qualification` | **PASS** |
| Existing Arabic customer text | Normal Arabic flow | Propagation tests with Arabic session; no explicit “continues” gate test | **PARTIAL** |
| Duplicate MessageSid | Cached response | Idempotency tests in gate + Deepgram suites | **PASS** |
| Invalid language-like input before selection | Selector or safe behavior | Random text (`hello`) → selector sent again on first contact | **PASS** |
| Gate before OpenRouter/Deepgram | Required order | `ExtractService.run_turn()` lines 69–88 before transcription | **PASS** |
| Missing Twilio Content SID | 503; language stays null | `test_missing_content_sid_returns_503_without_openrouter` | **PASS** |
| Twilio send failure | 502; language stays null | `test_twilio_send_failure_leaves_language_unset` | **PASS** |

## Message Catalog and Customer Reply Language
| Requirement | Expected | Actual | Status |
|---|---|---|---|
| Centralized catalog | Single module | `apps/qualification/domain/messages.py` | **PASS** |
| Project type question | Localized | `project_type` en/ar | **PASS** |
| Requirements | Localized | `requirements` en/ar | **PASS** |
| Referral source | Localized | `referral_source` en/ar | **PASS** |
| WhatsApp confirmation | Localized | `whatsapp_confirmed`, `whatsapp_confirmation_unclear` | **PASS** |
| Preferred phone | Localized | `preferred_phone`, `invalid_phone` | **PASS** |
| Completion | Localized | `completion` en/ar | **PASS** |
| Handoff | Localized | `human_handoff` en/ar | **PASS** |
| Generic retry/error | Localized | `generic_retry`, `generic_error` | **PASS** |
| Welcome / language confirmation text | In catalog | Selector text lives in Twilio Content template, not Django catalog | **PARTIAL** — by design |
| Name / company messages | In catalog | Project schema has no `full_name`/`company_name` fields | **NOT APPLICABLE** to current qualification flow |
| Language-change instruction | In catalog | Language-change feature not implemented | **NOT IMPLEMENTED** |
| Flow uses stored language | Yes | `build_turn_response`, `get_qualification_question(language=...)` | **PASS** |
| No scattered duplicate Arabic strings | Centralized | Catalog + prompts only | **PASS** |
| Arabic customer not served English by mistake | Guarded | Arabic propagation tests | **PASS** (mocked) |
| Does not re-ask valid stored fields | Yes | `_next_missing_field()` logic | **PASS** |
| Customer data unchanged in messages | Names/phones preserved in prompts | Arabic prompt rules + extraction schema | **PASS** (technical) |
| Arabic linguistic quality approved | Human review | No review evidence in repo | **LANGUAGE REVIEW RECOMMENDED** |

## OpenRouter Arabic Prompt Routing
| Requirement | Expected | Actual | Status |
|---|---|---|---|
| Arabic instructions appended for `ar` | Yes | `ARABIC_CONVERSATION_INSTRUCTIONS` in `build_extraction_system_prompt()` | **PASS** |
| Canonical English JSON keys | Yes | `EXTRACTION_SYSTEM_PROMPT` schema unchanged | **PASS** |
| No Arabic backend field names | Yes | Keys: `project_type`, `requirements`, etc. | **PASS** |
| English prompt compatible | Yes | English path unchanged | **PASS** |
| Language from persisted state | Yes | `handle_qualification_turn()` → `get_conversation_language()` | **PASS** |
| n8n language cannot override stored | Yes | No request-language override in turn handler | **PASS** |
| No automatic detection after selection | Yes | Session language fixed after `persist_selected_language()` | **PASS** |
| Arabic prompt tests | Yes | `test_arabic_language_propagation.py` prompt assertions | **PASS** |
| English regression tests | Yes | Existing extract/conversation tests (gate disabled via conftest) | **PASS** |

## Arabic and Persian Phone-Digit Handling
| Input | Expected Normalization/Validation | Actual | Status |
|---|---|---|---|
| `+966 50 123 4567` | Whitespace stripped; valid E.164 | Whitespace strip in serializers/`_normalize_phone()`; ASCII validation | **PASS** (Latin digits) |
| `٠٥٠١٢٣٤٥٦٧` | Arabic digits → ASCII | No transliteration; fails E.164 regex | **FAIL** |
| `+٩٦٦٥٠١٢٣٤٥٦٧` | Arabic digits in E.164 → ASCII | No transliteration; fails validation | **FAIL** |
| `۰۵۰۱۲۳۴۵۶۷` | Persian digits → ASCII | No transliteration; fails validation | **FAIL** |
| `+۹۶۶۵۰۱۲۳۴۵۶۷` | Persian digits in E.164 → ASCII | No transliteration; fails validation | **FAIL** |
| Valid phone stored, not re-asked | Yes when E.164 valid | `_has_preferred_phone()` uses `is_valid_e164_phone_number()` | **PASS** (ASCII only) |
| Invalid phone localized message | Arabic/English `invalid_phone` | `conversation_flow._reply_text_for_next_field()` | **PASS** |
| Normalization before validation | Required | Only whitespace removal today | **FAIL** |
| Tests for Arabic/Persian digits | Required | None found | **NOT IMPLEMENTED** |

**Critical issue:** Customers entering phone numbers with Eastern Arabic or Persian digits will likely fail validation and be re-prompted indefinitely.

## Arabic Deepgram Voice Transcription
| Scenario | Expected | Actual | Status |
|---|---|---|---|
| English voice note | English model/language | `test_english_voice_note_uses_english_deepgram_configuration` | **PASS** (mocked) |
| Arabic voice note | Arabic model + `ar` | `test_arabic_voice_note_uses_arabic_deepgram_configuration` (nova-3/ar) | **PASS** (mocked) |
| Language not selected | No Deepgram | Gate tests block transcription | **PASS** |
| Arabic config missing | Controlled error | `get_deepgram_transcription_config` raises `DeepgramConfigurationError`; 503 test exists | **PASS** |
| Hint conflicts with stored language | Stored wins | Deepgram uses `get_conversation_language()` after gate | **PASS** |
| English regression | No change | English config fallbacks to `DEEPGRAM_MODEL`/`DEEPGRAM_LANGUAGE` | **PASS** |
| No silent English fallback for Arabic | Required | Arabic path requires explicit `DEEPGRAM_ARABIC_*` | **PASS** |
| Live Arabic transcription accuracy | Real audio test | Not performed in audit | **MANUAL VERIFICATION REQUIRED** |

## Arabic TTS and Text Fallback
| Scenario | Expected | Actual | Status |
|---|---|---|---|
| Arabic TTS disabled by default | Yes | `SUPERTONIC_ARABIC_ENABLED` default `False` in `settings.py` | **PASS** |
| Arabic voice from environment | Not hardcoded | `SUPERTONIC_ARABIC_VOICE` env only | **PASS** |
| No silent English voice for Arabic | Yes | `test_arabic_does_not_use_english_f1_when_arabic_voice_not_configured` | **PASS** |
| Disabled Arabic → HTTP 200 fallback | Yes | `test_arabic_disabled_returns_text_fallback` | **PASS** |
| `fallback_to_text=true` | Yes | All Arabic fallback tests | **PASS** |
| No provider errors in response | Yes | Supertonic string absent from body in tests | **PASS** |
| `audio_url` null on fallback | Yes | Fallback response contract | **PASS** |
| English TTS compatible | Yes | `test_valid_request_produces_media_url_with_audio_ogg` | **PASS** |
| Render idempotency | Yes | `test_duplicate_request_id_does_not_render_twice` | **PASS** |
| Uses `whatsapp_number` for language | Yes | `RenderAudioService._resolve_conversation_language()` | **PASS** |
| Legacy no-`whatsapp_number` English-only | Yes | Defaults to `LANGUAGE_ENGLISH` | **PASS** |
| Verification command exists | Yes | `verify_arabic_supertonic_voice` | **PASS** |
| Manual listening before enablement | Required | Command stdout warns; no human sign-off in repo | **MANUAL VERIFICATION REQUIRED** |
| Configured voice in deployment `.env` | Required | Local audit: `SUPERTONIC_ARABIC_VOICE` **MISSING** | **FAIL** (env) |
| Generated verification sample | WAV/OGG on disk | `media/arabic_supertonic_verification/arabic_supertonic_M1_20260630_130037.{wav,ogg}` exists from dev run with inline `SUPERTONIC_ARABIC_VOICE=M1` | **PARTIAL** — sample exists; not tied to `.env`; listening not evidenced |
| n8n `fallback_to_text` branch | Documented IF node | `T3-11-whatsapp-text-voice-reply-routing.md` only | **NOT VERIFIABLE FROM REPOSITORY** |

## Language-Change Command
| Scenario | Expected | Actual | Status |
|---|---|---|---|
| English commands (`LANGUAGE`, `language`) | Resend selector; preserve lead data | No handler in codebase | **NOT IMPLEMENTED** |
| Arabic commands (`لغة`, `اللغة`, `تغيير اللغة`) | Same | No handler | **NOT IMPLEMENTED** |
| Runs before OpenRouter when applicable | Yes | N/A | **NOT IMPLEMENTED** |
| Does not wipe lead data | Yes | N/A | **NOT IMPLEMENTED** |
| Does not reset qualification progress | Yes | N/A | **NOT IMPLEMENTED** |
| Idempotent language change | Yes | N/A | **NOT IMPLEMENTED** |
| Arabic ↔ English change tests | Yes | None | **NOT IMPLEMENTED** |
| Typed `English`/`العربية` on active conversation | Ignored (not a change) | `test_typed_fallback_does_not_change_active_english_conversation` | **PASS** (current behavior is ignore, not change) |

Explicitly deferred in `docs/language-selection-routing-implementation-report.md` and `docs/arabic-customer-messages-and-language-propagation-report.md`.

## n8n Workflow Readiness
- **Repository evidence found:**
  - `twilio-whatsapp-inbound.json` — inbound webhook + field inspection only; **no** Django extract call, **no** `ButtonPayload` forwarding, **no** `awaiting_language_selection` branch, **no** render-audio/TTS fallback.
  - `docs/integrations/n8n/T3-11-whatsapp-text-voice-reply-routing.md` — documents `fallback_to_text`, render-audio fields, `conversation_language`, `whatsapp_number`.
  - `docs/language-selection-routing-implementation-report.md` — documents button forwarding and gate behavior.
  - `docs/integrations/n8n/LLM-5-django-qualification-endpoint.md` — **outdated**: still describes extract body as only `message` + `whatsapp_number` (no button fields, no voice channel, no awaiting status).
- **What must be checked manually in n8n Cloud:**
  - Forward all Twilio fields including `ButtonPayload`, `ButtonText`, `ButtonType`, `MediaUrl0`, `NumMedia`.
  - Stop workflow when Django returns `status: awaiting_language_selection` (no lead update, no customer reply duplicate, no render-audio).
  - Pass `message_sid`, `whatsapp_number`, `conversation_language`, `reply_text`, `reply_mode` through voice/text branches.
  - Add render-audio call for voice replies with `whatsapp_number`.
  - Branch on `fallback_to_text === true` to send original `reply_text` as text.
- **Whether awaiting-language flow stops correctly:** **NOT VERIFIABLE FROM REPOSITORY**
- **Whether fallback-to-text branch exists:** Documented in T3-11 only; **NOT VERIFIABLE FROM REPOSITORY**
- **Whether critical fields survive later nodes:** **NOT VERIFIABLE FROM REPOSITORY**
- **Final n8n status:** **BACKEND COMPLETE, N8N MANUAL WORK PENDING**

## Tests Run
| Command | Result | Notes |
|---|---|---|
| `.venv/bin/python manage.py makemigrations --check --dry-run` | **PASS** | No changes detected |
| Full suite: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 DJANGO_SETTINGS_MODULE=config.settings_test .venv/bin/python -m pytest -p pytest_django -q` | **PASS** | 547 passed |
| Focused language suite (13 files, 133 tests) | **PASS** | language gate, resolver, messages, Deepgram, Supertonic, render-audio, Twilio serializer, phone_confirmation |
| `verify_arabic_supertonic_voice` (without `.env` voice) | **FAILED** | `SUPERTONIC_ARABIC_VOICE is not configured` |
| Live Twilio language picker send | **NOT RUN** | Manual verification required |
| Live Deepgram Arabic transcription | **NOT RUN** | Mocked integration tests only |
| Live Supertonic Arabic TTS in CI | **NOT RUN** | Dev sample generated earlier with inline `M1`; manual listening not evidenced |

## Manual Verification Checklist
- [ ] Twilio Content SID is valid and points to correct quick-reply content.
- [ ] Twilio Quick Reply has `lang_en` and `lang_ar` payloads.
- [ ] Sandbox/production WhatsApp sender is configured.
- [ ] New customer receives selector.
- [ ] English button starts English flow.
- [ ] Arabic button starts Arabic flow.
- [ ] Arabic typed fallback works.
- [ ] Arabic voice note is transcribed correctly using live Deepgram.
- [ ] Arabic phone number with Arabic digits is accepted.
- [ ] Language-change command preserves lead fields.
- [ ] n8n stops after `awaiting_language_selection`.
- [ ] n8n sends text when `fallback_to_text=true`.
- [ ] Arabic Supertonic sample has been manually listened to before enablement.

## Critical Gaps and Risks
1. **Arabic/Persian phone-digit normalization not implemented** — valid numbers in Eastern digits will fail E.164 validation and may trap customers in repeated phone prompts. **Customer-journey blocker for Arabic locales using native digits.**
2. **Language-change command not implemented** — customers cannot switch language mid-conversation via documented commands.
3. **n8n production workflow not evidenced** — without manual n8n updates, button payloads may not reach Django, awaiting-language may not stop the workflow, and TTS fallback may not send text. **Customer-journey blocker for production until n8n is wired.**
4. **Twilio Content template not verifiable from repo** — misconfigured Content SID causes 503 for all new customers (`test_missing_content_sid_returns_503_without_openrouter`). **Production blocker if SID wrong.**
5. **Arabic TTS not production-ready** — `SUPERTONIC_ARABIC_VOICE` missing in local `.env`; manual listening not documented; keep `SUPERTONIC_ARABIC_ENABLED=false`.
6. **Outdated n8n LLM-5 documentation** — risk of integrators following wrong extract contract (missing button/voice/awaiting fields).
7. **No explicit test for existing Arabic conversation continuing without selector** — low risk given symmetric code path.

## Exact Remaining Work
1. **Backend:** Implement Arabic/Persian digit normalization before E.164 validation (phone serializers, extract flow, OpenRouter post-processing if needed) with unit tests for all audit examples.
2. **Backend:** Implement language-change command detection (English/Arabic variants) that resends picker, updates only `language`/`language_selected_at`, and preserves Redis qualification state — with idempotency tests.
3. **Backend:** Add catalog key for language-change instruction once command exists.
4. **Backend:** Add explicit integration test for existing Arabic session continuing qualification without selector.
5. **Environment:** Set `SUPERTONIC_ARABIC_VOICE` after manual voice verification; keep `SUPERTONIC_ARABIC_ENABLED=false` until approved.
6. **Environment:** Confirm `TWILIO_LANGUAGE_PICKER_CONTENT_SID` and `TWILIO_WHATSAPP_FROM_NUMBER` in production (values not in report).
7. **Twilio Console:** Create/verify Quick Reply Content with `English` → `lang_en` and `العربية` → `lang_ar`; approve for WhatsApp.
8. **n8n Cloud:** Update workflow to forward all Twilio fields; call Django extract; **stop** on `awaiting_language_selection`; pass button fields; add render-audio + `fallback_to_text` branch; preserve `reply_text`/`conversation_language`/`message_sid`/`whatsapp_number`.
9. **Documentation:** Update `LLM-5-django-qualification-endpoint.md` to match current `ExtractRequestSerializer` contract.
10. **Live testing:** New-customer selector, Arabic text flow, Arabic voice note with live Deepgram, Arabic-digit phone entry (after fix), TTS text fallback path in n8n.
11. **Manual approval:** Listen to Arabic Supertonic verification sample; human review of Arabic message catalog strings.

## Final Verdict
- **Complete (backend, with evidence):** Persisted conversation language model and migrations; language selection resolver; language gate ordering; Twilio picker send helper; bilingual message catalog for current qualification fields; OpenRouter Arabic prompt routing; Deepgram language-aware config; render-audio Arabic fallback contract; MessageSid/idempotency; Twilio inbound serializer mapping; 547 automated tests passing.
- **Incomplete:** Arabic/Persian phone-digit normalization; language-change commands; n8n production workflow wiring; Twilio Console live validation; Arabic TTS production enablement; human Arabic copy/TTS quality sign-off.
- **Arabic TTS must remain disabled** until `SUPERTONIC_ARABIC_VOICE` is configured in deployment environment, verification audio is manually approved, and n8n `fallback_to_text` branching is live.
