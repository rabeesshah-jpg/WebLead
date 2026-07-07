# Voice-call completion webhook — implementation report

**Date:** 2026-06-30

## Summary

Added a post-call internal API so the LiveKit Worker can deliver completed qualification data after a voice call ends. WebLead persists lead fields and optionally sends a booking-link WhatsApp message via Twilio. The endpoint is outside the real-time audio loop.

## Endpoint added

| Method | Path | Auth header | Env var |
|--------|------|-------------|---------|
| `POST` | `/api/internal/qualification/voice-call-completed/` | `X-WebLead-Secret` | `WEBLEAD_VOICE_EVENT_SECRET` |

**Request body (all fields required unless noted):**

- `event` — must be `voice_call.completed`
- `event_id` — idempotency key
- `call_id`
- `customer_phone` — E.164
- `whatsapp_number` — E.164 (conversation key)
- `project_type` — `new_website` \| `website_upgrade`
- `requirements`
- `referral_source`
- `whatsapp_confirmed` — boolean
- `preferred_phone` — optional E.164 or null
- `send_booking_link` — boolean

**Success response (200):**

```json
{
  "status": "accepted",
  "event_id": "...",
  "call_id": "...",
  "accepted_fields": { ... },
  "qualification_status": "completed",
  "send_booking_link": true,
  "booking_link_sent": true,
  "booking_link": "https://..."
}
```

Duplicate `event_id` replays return `status: "duplicate"` with the original `call_id` and booking flags; no second WhatsApp send.

**Errors:** `400` invalid payload, `403` bad secret, `502` Twilio send failure, `503` secret not configured.

## Changed files

| File | Change |
|------|--------|
| `apps/qualification/api/views.py` | `VoiceCallCompletedAPIView` |
| `apps/qualification/api/urls.py` | **New** — internal qualification routes (extract, render-audio, voice-call-completed) |
| `apps/qualification/urls.py` | Re-exports `api/urls.py` |
| `apps/qualification/api/serializers.py` | Request/response serializers |
| `apps/qualification/api/permissions.py` | `VoiceEventSecretPermission` |
| `apps/qualification/voice_event_auth.py` | **New** — `X-WebLead-Secret` validation |
| `apps/qualification/voice_call_event_idempotency.py` | **New** — `event_id` cache helpers |
| `apps/qualification/services/voice_call_completed_service.py` | **New** — persist + booking send orchestration |
| `apps/qualification/integrations/twilio_whatsapp_message.py` | **New** — outbound WhatsApp text send |
| `apps/qualification/tests/test_voice_call_completed_api.py` | **New** — endpoint tests |
| `config/settings.py` | `WEBLEAD_VOICE_EVENT_SECRET` |
| `config/settings_test.py` | Test secret + `TWILIO_WHATSAPP_FROM_NUMBER` |
| `.env.example` | `WEBLEAD_VOICE_EVENT_SECRET`, `TWILIO_WHATSAPP_FROM_NUMBER` |

## Env vars added

| Variable | Purpose |
|----------|---------|
| `WEBLEAD_VOICE_EVENT_SECRET` | Shared secret for LiveKit Worker (`X-WebLead-Secret`) |

**Also documented in `.env.example` (existing, required for send):**

- `TWILIO_WHATSAPP_FROM_NUMBER` — WhatsApp sender for booking-link messages
- `BOOKING_LINK` — URL embedded in completion text (existing)

## Idempotency approach

- Reuses the qualification persistence idempotency layer (`begin_idempotent_turn` / `cache_turn_response`) with keys prefixed `voice-call-event:{event_id}`.
- First successful processing caches the full response; duplicates return `status: "duplicate"` and do not call Twilio again.
- In production with Redis, concurrent duplicate `event_id` requests follow the same exclusive-slot + poll pattern as WhatsApp `MessageSid` idempotency.

## Booking-link flow

1. `save_accepted_fields(whatsapp_number, …)` — same Redis/in-memory store as WhatsApp qualification.
2. `get_or_create_conversation_session` — ensures DB session row exists for language lookup.
3. When `send_booking_link=true` and `BOOKING_LINK` is set: `build_booking_completion_reply()` (shared with WhatsApp extract completion) builds localized text; `send_whatsapp_text_message()` sends it via Twilio.
4. `booking_link_sent=true` only when a link is configured and the WhatsApp send succeeds.

When `send_booking_link=false`, data is saved only; no Twilio call.

Invalid `whatsapp_number` is rejected at serializer validation with structured log field `whatsapp_number_invalid=true`.

## Tests run

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
DJANGO_SETTINGS_MODULE=config.settings_test \
.venv/bin/python -m pytest -p pytest_django.plugin -q
```

**Result:** `628 passed` (includes 7 new voice-call-completed tests).

New test coverage:

- Valid event accepted (persist + booking send mocked)
- Invalid secret rejected
- Duplicate `event_id` ignored safely
- Invalid `whatsapp_number` rejected
- `send_booking_link=false` does not send link
- Booking link sent exactly once across replays

## Remaining risks

1. **Twilio session window** — Outbound WhatsApp requires an active 24-hour session or approved template; plain-text send may fail for cold numbers. Monitor `voice_call_completed_booking_send_failed` logs.
2. **No `BOOKING_LINK`** — Request with `send_booking_link=true` still completes persistence but `booking_link_sent=false` and no message is sent; worker should treat that as partial success.
3. **Failed send before cache** — A 502 on Twilio failure leaves no cached response, so a retry with the same `event_id` may attempt send again (acceptable for at-least-once delivery).
4. **Language** — Booking text uses the WhatsApp session language when set; defaults to English for new voice-only leads.
5. **Separate secret** — `WEBLEAD_VOICE_EVENT_SECRET` is independent of `N8N_QUALIFICATION_API_SECRET`; both must be configured in their respective environments.
