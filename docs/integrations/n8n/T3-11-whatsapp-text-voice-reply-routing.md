# WhatsApp text and voice reply routing

This note describes how n8n should route Django qualification replies for WhatsApp text and voice-note conversations.

## Django request fields

Send these fields to `POST /api/internal/qualification/extract/`:

| Field | Text | Voice note |
| --- | --- | --- |
| `whatsapp_number` | required | required |
| `input_channel` | `whatsapp_text` | `whatsapp_voice_note` |
| `message` | required | optional if `media_url` is provided |
| `message_sid` | recommended | recommended |
| `media_url` | omit | required (`MediaUrl0`) |
| `media_content_type` | omit | optional (`MediaContentType0`, default `audio/ogg`) |

Django downloads and transcribes voice notes server-side, then runs the same qualification conversation flow used for text.

## Django response fields

Every successful response includes:

- `reply_mode`: `text` or `voice` based on the latest inbound `input_channel`
- `reply_text`: channel-facing copy (for voice, this matches `spoken_text` and never contains a URL)
- `spoken_text`: what TTS / the voice agent should say (never contains a URL)
- `whatsapp_text`: text body for Twilio when `should_send_text` is true
- `should_send_text`: when true, n8n may send `whatsapp_text` as a WhatsApp text message
- `should_send_audio`: when true, n8n should call render-audio and send voice media
- `text_fallback_reply`: longer text copy used only when render-audio returns `fallback_to_text=true`
- `contains_booking_link`: true when the booking URL is present in outbound text fields
- `actions`: reserved list (currently empty)
- `conversation_language`: `en` or `ar` from persisted session state
- `send_booking_link`: `true` for voice completion when a booking URL should be delivered as WhatsApp text
- `booking_link`: booking URL when completed, otherwise `null`
- `transcript`: present for voice-note input only

Optional realtime/LiveKit request fields:

- `call_sid`, `utterance_id`, `is_final` — when `is_final=false`, partial STT is ignored; duplicate finals for the same call+utterance (or transcript hash within ~2.5s) return `duplicate_detected=true` and `tts_enqueued=false`

When `qualification_status` is `completed` on a **voice** turn:

- `spoken_text` / `reply_text`: `Perfect, thank you. I've sent the booking link above. You can choose a time whenever you're ready.`
- `whatsapp_text`: `Perfect, thank you. Please book a time here: <BOOKING_LINK>`
- `should_send_text`: `true` (booking link text only, once per session)
- `should_send_audio`: `true`
- `send_booking_link`: `false` (URL is already in `whatsapp_text`)

When completed on a **text** turn, `reply_text` remains the single WhatsApp message that already includes the booking URL, `should_send_text` is `true`, and `should_send_audio` is `false`.

## n8n routing

### Text route (`reply_mode = "text"`)

1. **Only when** `should_send_text = true`: send `whatsapp_text` (or `reply_text`) via the Twilio WhatsApp text node.
2. Do **not** call render-audio when `should_send_audio = false`.

### Voice route (`reply_mode = "voice"`)

1. **Only when** `should_send_audio = true`: call `POST /api/internal/qualification/render-audio/` with:

```json
{
  "text": "={{ $json.spoken_text || $json.reply_text }}",
  "voice": "={{ $json.voice || '' }}",
  "request_id": "={{ $json.message_sid }}",
  "whatsapp_number": "={{ $json.whatsapp_number }}",
  "conversation_language": "={{ $json.conversation_language }}"
}
```

Do **not** pass a booking URL into render-audio. Django sanitizes URLs out of TTS input if one is passed by mistake.

2. Branch on the render-audio response:

```text
TTS Fallback Required?
  condition: {{ $json.fallback_to_text }} equals true
  ├── true  → Send WhatsApp Text Reply using text_fallback_reply or whatsapp_text
  └── false → Send WhatsApp Voice Reply using media_url / audio_url
```

3. **Only when** `should_send_text = true`: send `whatsapp_text` as a separate Twilio text message (first-time booking link on voice completion).

4. For normal voice turns (`should_send_text = false`), do **not** send `reply_text` or `whatsapp_text` as text.

- `fallback_to_text = false`
- `should_send_audio = true`
- `media_url` or `audio_url` is present
- `content_type` / `audio_content_type` is `audio/ogg`

### Booking link on voice completion

When `should_send_text = true` and `contains_booking_link = true`:

1. Send rendered voice first (when `should_send_audio = true`).
2. Send one Twilio text message with `whatsapp_text` (includes the booking URL).
3. Do not pass the booking URL to render-audio.

Post-booking voice turns use `should_send_text = false` and audio-only replies that reference the link above.

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

### Render-audio text-fallback response

Returned with HTTP `200` when Arabic or English TTS is unavailable or fails:

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

Use `text_fallback_reply` or `whatsapp_text` for the text fallback message. The render-audio endpoint does not generate or replace translated reply text.

### Render-audio success response

Always pass Twilio `MessageSid` as `message_sid`.

Django caches the full successful response per `MessageSid`. Replays of the same inbound webhook do not create duplicate conversation turns or duplicate qualification processing.

Keep the existing n8n `Allow New MessageSid` / `Record MessageSid` nodes upstream of the Django call.

## Example voice workflow branch

```text
Twilio inbound
→ Allow New MessageSid
→ IF NumMedia > 0
   → POST Django extract with input_channel=whatsapp_voice_note and media_url=MediaUrl0
   → IF should_send_audio = true
      → POST Django render-audio(spoken_text, whatsapp_number, message_sid)
      → IF fallback_to_text = true
         → Twilio send text_fallback_reply or whatsapp_text
      → ELSE
         → Twilio send media_url
   → IF should_send_text = true
      → Twilio send whatsapp_text as text
→ ELSE
   → POST Django extract with input_channel=whatsapp_text and message=Body
   → IF should_send_text = true
      → Twilio send reply_text or whatsapp_text
```

## Operational notes

- Voice and text turns share the same in-memory qualification state keyed by `whatsapp_number`.
- If a customer switches between text and voice during a conversation, Django uses the latest inbound `input_channel` for the next `reply_mode`.
- Configure Django with `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `DEEPGRAM_API_KEY`, and related settings before enabling the voice branch in production.
- Set the n8n HTTP Request node timeout to `60000` ms (60 seconds), not `30000` ms, because one extract call may download Twilio media, transcribe audio, and call OpenRouter.
