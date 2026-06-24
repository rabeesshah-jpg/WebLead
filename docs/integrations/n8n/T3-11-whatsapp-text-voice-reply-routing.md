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
- `reply_text`: the message to send back to the customer
- `send_booking_link`: `true` when `qualification_status` is `completed`
- `booking_link`: booking URL when completed, otherwise `null`
- `transcript`: present for voice-note input only

When `qualification_status` is `completed`, `reply_text` is a short voice-safe completion line:

`Thank you. I will send you a booking link now.`

Send the actual booking URL separately when `send_booking_link=true`.

## n8n routing

### Text route (`reply_mode = "text"`)

1. Use the existing Twilio WhatsApp send-message node.
2. Put `reply_text` in the Twilio message body.

### Voice route (`reply_mode = "voice"`)

1. Send `reply_text` to the Supertonic render API.
2. Receive `media_url` from Supertonic.
3. Send that `media_url` through Twilio WhatsApp using the `MediaUrl` field.

### Booking link follow-up (`send_booking_link = true`)

Regardless of reply mode:

1. Send the primary reply first (text body or rendered voice media).
2. Send a second Twilio text message containing `booking_link`.

This keeps long URLs out of voice replies and gives text customers a dedicated link message.

## MessageSid idempotency

Always pass Twilio `MessageSid` as `message_sid`.

Django caches the full successful response per `MessageSid`. Replays of the same inbound webhook do not create duplicate conversation turns or duplicate qualification processing.

Keep the existing n8n `Allow New MessageSid` / `Record MessageSid` nodes upstream of the Django call.

## Example voice workflow branch

```text
Twilio inbound
→ Allow New MessageSid
→ IF NumMedia > 0
   → POST Django extract with input_channel=whatsapp_voice_note and media_url=MediaUrl0
   → IF reply_mode = voice
      → Supertonic render(reply_text)
      → Twilio send media_url
   → IF send_booking_link = true
      → Twilio send booking_link as text
→ ELSE
   → POST Django extract with input_channel=whatsapp_text and message=Body
   → Twilio send reply_text
   → IF send_booking_link = true
      → Twilio send booking_link as text
```

## Operational notes

- Voice and text turns share the same in-memory qualification state keyed by `whatsapp_number`.
- If a customer switches between text and voice during a conversation, Django uses the latest inbound `input_channel` for the next `reply_mode`.
- Configure Django with `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `DEEPGRAM_API_KEY`, and related settings before enabling the voice branch in production.
