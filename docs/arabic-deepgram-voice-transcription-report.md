# Arabic Deepgram Voice Transcription Report

## Scope Completed
- Language-aware Deepgram configuration resolver
- English backward-compatible configuration with optional explicit overrides
- Arabic voice-note routing from persisted `WhatsAppConversationSession.language`
- Safe transcription logging with model and language context
- Controlled configuration and upstream failure handling without English fallback
- Focused unit and integration tests

## Architecture Used
- **Persisted conversation language source:** `get_conversation_language()` reads `WhatsAppConversationSession.language` after the language gate in `ExtractService`.
- **Language gate:** Unchanged; new customers without a selected language never reach media download or Deepgram.
- **Voice-note transcription service:** `VoiceNoteTranscriptionService.transcribe()` resolves Deepgram config from `conversation_language`, downloads Twilio media, then calls the existing Deepgram client.
- **Deepgram client/configuration resolver:** `get_deepgram_transcription_config()` in `apps/qualification/domain/deepgram_config.py` builds `DeepgramTranscriptionConfig`; `transcribe_audio()` sends model and language in the listen URL query string.
- **Qualification orchestration:** `ExtractService` passes `conversation_language` into transcription, then the existing Arabic/English qualification and OpenRouter flow.

## Files Changed
| File | Purpose |
| --- | --- |
| `apps/qualification/domain/deepgram_config.py` | `DeepgramTranscriptionConfig` dataclass and `get_deepgram_transcription_config()` |
| `apps/qualification/deepgram_client.py` | Accept resolved config; send `model`, `language`, `punctuate`, `smart_format` to Deepgram |
| `apps/qualification/services/transcription_service.py` | Resolve config from `conversation_language`; language-aware logging |
| `apps/qualification/services/extract_service.py` | Pass persisted language into `transcribe()` |
| `apps/qualification/voice_note_logging.py` | Optional `conversation_language`, `deepgram_model`, `deepgram_language`, `error_type` fields |
| `config/settings.py` | New Deepgram English/Arabic settings and `DEEPGRAM_LANGUAGE` |
| `config/settings_test.py` | Test defaults for Arabic Deepgram settings |
| `.env.example` | Documented English override and Arabic Deepgram variables |
| `apps/qualification/tests/test_deepgram_config.py` | Resolver unit tests |
| `apps/qualification/tests/test_arabic_deepgram_voice_routing.py` | Voice-note routing, idempotency, and failure tests |
| `apps/qualification/tests/test_transcription_service.py` | Updated transcription client call contract |
| `apps/qualification/tests/test_extract_service.py` | Updated `conversation_language` argument assertion |
| `apps/qualification/tests/test_internal_extract_endpoint.py` | Updated Deepgram mock assertion |
| `apps/qualification/tests/test_qualification_channels.py` | Updated Deepgram mock assertion |

## Configuration
### Existing English variables preserved
- `DEEPGRAM_MODEL` (also reads legacy `VOICE_AGENT_DEEPGRAM_MODEL`)
- `DEEPGRAM_LANGUAGE`
- `DEEPGRAM_API_KEY`
- `DEEPGRAM_BASE_URL`
- `DEEPGRAM_TIMEOUT_SECONDS`

### New English override variables
- `DEEPGRAM_ENGLISH_MODEL` — optional; falls back to `DEEPGRAM_MODEL`
- `DEEPGRAM_ENGLISH_LANGUAGE` — optional; falls back to `DEEPGRAM_LANGUAGE`

### New Arabic variables
- `DEEPGRAM_ARABIC_MODEL` — default `nova-3`
- `DEEPGRAM_ARABIC_LANGUAGE` — default `ar`

### Required `.env` values (production example)
```env
DEEPGRAM_MODEL=nova-2
DEEPGRAM_LANGUAGE=en

DEEPGRAM_ENGLISH_MODEL=nova-2
DEEPGRAM_ENGLISH_LANGUAGE=en

DEEPGRAM_ARABIC_MODEL=nova-3
DEEPGRAM_ARABIC_LANGUAGE=ar
```

### Fallback behavior
| Conversation language | Model | Language |
| --- | --- | --- |
| `en` | `DEEPGRAM_ENGLISH_MODEL` → `DEEPGRAM_MODEL` → `nova-2` | `DEEPGRAM_ENGLISH_LANGUAGE` → `DEEPGRAM_LANGUAGE` → `en` |
| `ar` | `DEEPGRAM_ARABIC_MODEL` only | `DEEPGRAM_ARABIC_LANGUAGE` only |
| invalid / unset normalized value | Treated as `en` via `normalize_conversation_language()` | Same English fallback chain |

Arabic never falls back to English Deepgram settings. `language=multi` is rejected for Arabic configuration.

## Voice-Note Routing
### New customer without language selection
1. Language gate sends Twilio language picker.
2. No Twilio media download.
3. No Deepgram call.
4. No OpenRouter call.

### English selected conversation
1. `conversation_language="en"`
2. Twilio media downloaded.
3. Deepgram called with English model/language (default `nova-2` / `en`).
4. Transcript enters existing English qualification flow.
5. API response includes `conversation_language: "en"`.

### Arabic selected conversation
1. `conversation_language="ar"`
2. Twilio media downloaded.
3. Deepgram called with `DEEPGRAM_ARABIC_MODEL` / `DEEPGRAM_ARABIC_LANGUAGE` (default `nova-3` / `ar`).
4. Arabic transcript enters existing Arabic OpenRouter qualification flow.
5. API response includes `conversation_language: "ar"`.

## Error Handling
### Missing Arabic configuration
- Raised as `DeepgramConfigurationError` before media download.
- API returns `503` with `{"error": "Qualification service is unavailable."}`.
- Logs `qualification_voice_deepgram_configuration_error`.
- No OpenRouter call.

### Deepgram upstream failure
- Mapped to existing `ExtractStepFailure` / `502` with `{"error": "Voice transcription failed."}`.
- Logs `deepgram_transcription_failed` with `conversation_language`, `deepgram_model`, and `deepgram_language`.
- No automatic English fallback or second Deepgram call.

### Duplicate `MessageSid`
- Cached finalized response returned on replay.
- Twilio media and Deepgram are not invoked twice for the same `MessageSid`.

### Safe logging
Logs may include: `conversation_language`, `deepgram_model`, `deepgram_language`, `message_sid_prefix`, `error_type`, `media_content_type`, `elapsed_ms`.

Logs never include: API keys, full media URLs, full transcript text, or customer audio content.

## Tests and Results
Commands run:
```bash
python manage.py makemigrations --check --dry-run
python manage.py test
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 DJANGO_SETTINGS_MODULE=config.settings_test \
  .venv/bin/python -m pytest -p pytest_django -q
```

Focused suites:
- `test_deepgram_config.py`
- `test_arabic_deepgram_voice_routing.py`
- `test_transcription_service.py`
- `test_voice_note_failures.py`
- `test_language_gate_routing.py`
- `test_qualification_channels.py`
- `test_extract_service.py`
- `test_internal_extract_endpoint.py`

Results:
- `makemigrations --check --dry-run`: **No changes detected**
- `python manage.py test`: **0 tests** (pytest is the project runner)
- Full pytest suite: **531 passed**, 6 warnings (pytest-django mark/config warnings in this environment)

## Intentionally Deferred
- Arabic TTS / Supertonic voice replies
- n8n audio rendering language routing
- Country-specific Arabic dialect selection (`ar-SA`, `ar-AE`, etc.)
- Language-change command after initial selection
- Deepgram `language=multi` auto-detection
