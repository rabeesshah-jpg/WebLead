# Arabic Supertonic TTS and Text Fallback Report

## Scope Completed
- Language-aware TTS routing from persisted `WhatsAppConversationSession.language`
- Arabic TTS configuration (`SUPERTONIC_ARABIC_ENABLED`, `SUPERTONIC_ARABIC_VOICE`)
- English TTS configuration (`SUPERTONIC_ENGLISH_VOICE`)
- Arabic voice verification management command
- Controlled HTTP 200 text-fallback responses for expected TTS failures
- n8n branching requirements documented
- Render-audio `request_id` idempotency cache
- Focused and full regression tests

## Architecture Used
- **Persisted conversation language source:** `get_conversation_language(whatsapp_number)` in `apps/qualification/domain/language.py`
- **Render-audio API:** `RenderAudioAPIView` → `RenderAudioService`
- **Supertonic renderer:** `render_whatsapp_voice_reply_safe` → `synthesize_wav`
- **Voice configuration resolver:** `get_supertonic_voice_config()` in `apps/qualification/domain/supertonic_config.py`
- **Idempotency:** `apps/qualification/render_audio_idempotency.py` (memory + Redis when configured)
- **n8n voice/text branch:** documented in `docs/integrations/n8n/T3-11-whatsapp-text-voice-reply-routing.md`

## Files Changed
| File | Purpose |
| --- | --- |
| `apps/qualification/domain/supertonic_config.py` | `SupertonicVoiceConfig` dataclass and language-aware voice resolver |
| `apps/qualification/services/render_audio_service.py` | Language resolution, TTS routing, text fallback, structured logging |
| `apps/qualification/render_audio_idempotency.py` | `request_id` response cache |
| `apps/qualification/api/serializers.py` | Extended render-audio request/response contract |
| `apps/qualification/api/views.py` | Return HTTP 200 for service-level text fallback |
| `apps/qualification/render_audio_views.py` | Legacy parser parity for new optional fields |
| `apps/qualification/management/commands/verify_arabic_supertonic_voice.py` | Developer-only Arabic sample render |
| `config/settings.py` | Supertonic English/Arabic settings |
| `config/settings_test.py` | Test defaults for new settings |
| `.env.example` | Documented Supertonic voice variables |
| `docs/integrations/n8n/T3-11-whatsapp-text-voice-reply-routing.md` | n8n payload and TTS fallback IF branch |
| `apps/qualification/tests/test_supertonic_config.py` | Config resolver tests |
| `apps/qualification/tests/test_arabic_supertonic_tts.py` | Arabic routing, fallback, idempotency tests |
| `apps/qualification/tests/test_render_audio_service.py` | Updated service contract tests |
| `apps/qualification/tests/test_render_audio_api_view.py` | Updated API view tests |
| `apps/qualification/tests/test_render_audio_endpoint.py` | English fallback integration tests |
| `apps/qualification/tests/test_render_audio_serializers.py` | Serializer contract tests |
| `apps/qualification/tests/test_api_error_contracts.py` | TTS failure → text fallback contract |
| `apps/qualification/tests/internal_api_test_helpers.py` | Updated success field names |

## Configuration
### English voice configuration
```env
SUPERTONIC_ENGLISH_VOICE=F1
```

### Arabic voice configuration
```env
SUPERTONIC_ARABIC_ENABLED=false
SUPERTONIC_ARABIC_VOICE=
```

### Required production environment values
- Existing: `SUPERTONIC_BASE_URL`, `PUBLIC_MEDIA_BASE_URL` (or `BASE_WEBHOOK_URL`), `N8N_QUALIFICATION_API_SECRET`
- New: `SUPERTONIC_ENGLISH_VOICE` (defaults to `F1`)
- Arabic (after manual verification): `SUPERTONIC_ARABIC_ENABLED=true` and `SUPERTONIC_ARABIC_VOICE=<verified-voice-id>`

### Backward compatibility behavior
- Render-audio requests **without** `whatsapp_number` continue on the English legacy path (`conversation_language=en`).
- Legacy response fields `media_url`, `content_type`, and `request_id` are preserved.
- New fields (`status`, `fallback_to_text`, `conversation_language`, `audio_url`, `audio_content_type`) are additive.
- Incoming `lang` is a hint only; persisted session language wins when `whatsapp_number` is provided.

## Arabic Voice Verification
- **Command:** `python manage.py verify_arabic_supertonic_voice`
- **Sample phrase:** `مرحبًا، شكرًا لتواصلك معنا. كيف يمكننا مساعدتك؟`
- **Generated audio location:** `media/arabic_supertonic_verification/arabic_supertonic_{voice}_{timestamp}.wav` and `.ogg`
- **Manual listening requirement:** A developer must listen to the generated sample and confirm pronunciation is understandable before setting `SUPERTONIC_ARABIC_ENABLED=true`.
- **Verification state:** Arabic TTS remains **disabled by default** (`SUPERTONIC_ARABIC_ENABLED=false`). Automated verification was not run against a live Supertonic instance in CI.

## Render Response Contract
### Successful voice-render response
```json
{
  "status": "rendered",
  "fallback_to_text": false,
  "conversation_language": "ar",
  "media_url": "https://.../media/whatsapp_voice_replies/{uuid}/",
  "content_type": "audio/ogg",
  "audio_url": "https://.../media/whatsapp_voice_replies/{uuid}/",
  "audio_content_type": "audio/ogg",
  "request_id": "MM..."
}
```

### Text-fallback response
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
  "request_id": "MM..."
}
```

### HTTP status behavior
- **200** for successful render and expected text fallback
- **400** for malformed/invalid requests
- **403** for auth failures
- **500** for unexpected internal errors
- **503** only when `N8N_QUALIFICATION_API_SECRET` is not configured (startup gate)

### Safe fallback reasons
| Reason | When |
| --- | --- |
| `arabic_tts_unavailable` | Arabic disabled, voice missing, Supertonic/ffmpeg/validation failure for Arabic |
| `english_tts_unavailable` | English Supertonic/ffmpeg/validation failure |
| `unsupported_language` | Unsupported persisted language code |

## n8n Workflow Changes Required
### Render-audio request payload
```json
{
  "text": "={{ $json.reply_text }}",
  "voice": "={{ $json.voice || '' }}",
  "request_id": "={{ $json.message_sid }}",
  "whatsapp_number": "={{ $json.whatsapp_number }}",
  "conversation_language": "={{ $json.conversation_language }}"
}
```

Do not hardcode `"lang": "en"` or `"lang": "ar"`.

### TTS fallback IF node
- **Name:** `TTS Fallback Required?`
- **Condition:** `={{ $json.fallback_to_text }}` equals `true`

### Text fallback branch
- Route to existing **Send WhatsApp Text Reply** using the original qualification `reply_text`.

### Voice success branch
- Send voice only when `fallback_to_text=false` and `media_url` / `audio_url` is present with `audio/ogg` content type.

## Tests and Results
### Commands run
```bash
python manage.py makemigrations --check --dry-run
# No changes detected

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 DJANGO_SETTINGS_MODULE=config.settings_test \
  .venv/bin/python -m pytest -p pytest_django \
  apps/qualification/tests/test_supertonic_config.py \
  apps/qualification/tests/test_arabic_supertonic_tts.py \
  apps/qualification/tests/test_render_audio_service.py \
  apps/qualification/tests/test_render_audio_api_view.py \
  apps/qualification/tests/test_render_audio_endpoint.py \
  apps/qualification/tests/test_render_audio_serializers.py \
  apps/qualification/tests/test_api_error_contracts.py \
  apps/qualification/tests/test_internal_auth.py \
  apps/qualification/tests/test_arabic_deepgram_voice_routing.py \
  apps/qualification/tests/test_arabic_language_propagation.py \
  -q

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 DJANGO_SETTINGS_MODULE=config.settings_test \
  .venv/bin/python -m pytest -p pytest_django -q
```

### Results
- Focused render-audio / Arabic TTS tests: **passed**
- Full suite: **547 passed**

### Skipped tests
- None. Live Supertonic Arabic verification command was not executed (requires running Supertonic and configured `SUPERTONIC_ARABIC_VOICE`).

## Remaining Limitations
- Arabic voice quality requires manual approval via `verify_arabic_supertonic_voice` before enablement.
- No country-specific Arabic dialect routing.
- Provider Arabic support depends on the configured Supertonic voice/model; if unsupported, text fallback is used automatically.
- Legacy render-audio requests without `whatsapp_number` cannot route Arabic TTS until n8n sends the WhatsApp number.
