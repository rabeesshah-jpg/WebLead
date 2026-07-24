# n8n ↔ WAHA WhatsApp transport (post-Twilio)

## Purpose

Replace Twilio Trigger / Twilio send / Content SID nodes with WAHA. Django still owns qualification (`/api/internal/qualification/extract/`). Interactive pickers (language, menu, referral_source, business_type) are sent by **Django via WAHA**; n8n sends normal text and voice replies.

## Target flow

```text
WhatsApp → WAHA → POST /api/webhooks/waha/whatsapp-inbound/
  → Django maps to extract JSON → N8N_WEBHOOK_URL
  → n8n: MessageSid dedupe (use message_sid) → Call Django Qualification API
  → IF status === awaiting_language_selection → Stop
  → IF option_template set → Skip Content/template send (Django already sent)
  → Else send reply_text / render-audio via WAHA or Django send proxy
```

## Inbound

1. Point the WAHA session webhook at:

```text
https://<django-public-host>/api/webhooks/waha/whatsapp-inbound/
```

2. Configure WAHA to send the `X-Api-Key` header matching `WAHA_WEBHOOK_SECRET` (or `WAHA_API_KEY` when the dedicated secret is empty).

3. Django forwards **JSON** to `N8N_WEBHOOK_URL` with `X-Internal-Webhook-Secret`. Shape matches extract:

```json
{
  "whatsapp_number": "+9233…",
  "message": "…",
  "message_sid": "true_9233…@c.us_…",
  "button_payload": "lang_en",
  "button_text": "English",
  "input_channel": "whatsapp_text",
  "media_url": null,
  "media_content_type": null
}
```

4. In n8n, replace “Normalize Twilio Message” with a pass-through (see stub [`waha-whatsapp-inbound.json`](../../../waha-whatsapp-inbound.json)). Keep MessageSid dedupe using `message_sid`.

## Call Django Qualification API

Unchanged endpoint:

```text
POST {{BASE_WEBHOOK_URL}}/api/internal/qualification/extract/
Header: X-Internal-Webhook-Secret: {{N8N_QUALIFICATION_API_SECRET}}
```

Body: the normalized JSON above.

## Language selector branch

Keep IF node:

```text
={{ $json.status === "awaiting_language_selection" }}
```

On true → stop (Django already sent language buttons via WAHA).

## option_template branch

When extract returns `option_template` (`referral_source` or `business_type`) and `should_send_text === false`:

- **Do not** send Twilio Content / WAHA list again.
- Skip plain-text Body for that turn.
- Continue lead Data Table updates from `accepted_fields` as before.

## Outbound text (n8n)

### Option A — Django proxy (recommended)

```text
POST {{BASE_WEBHOOK_URL}}/api/internal/whatsapp/send/
Header: X-Internal-Webhook-Secret: {{N8N_QUALIFICATION_API_SECRET}}
Content-Type: application/json

{
  "phone_number": "{{ $json.whatsapp_number }}",
  "message": "{{ $json.whatsapp_text || $json.reply_text }}"
}
```

### Option B — Direct WAHA

```text
POST {{WAHA_BASE_URL}}/api/sendText
Header: X-Api-Key: {{WAHA_API_KEY}}
Content-Type: application/json

{
  "session": "default",
  "chatId": "{{ $json.whatsapp_number.replace('+','') }}@c.us",
  "text": "{{ $json.whatsapp_text || $json.reply_text }}"
}
```

Only send when `should_send_text === true` and `status !== "awaiting_language_selection"`.

## Outbound voice

1. Keep `POST /api/internal/qualification/render-audio/` when `should_send_audio`.
2. Send the returned media URL with WAHA:

```text
POST {{WAHA_BASE_URL}}/api/sendVoice
Header: X-Api-Key: {{WAHA_API_KEY}}

{
  "session": "default",
  "chatId": "<digits>@c.us",
  "file": { "url": "<public media_url from render-audio>" },
  "convert": true
}
```

(Engine support varies; `sendFile` is an alternative.)

## Nodes to remove

- Twilio Trigger / Twilio WhatsApp inbound
- Twilio send message / Content Template nodes
- ContentSid Switch cases for referral_source / business_type / language

## Nodes to keep

- MessageSid (now WAHA id) dedupe
- Call Django Qualification API
- Language Selector Already Sent?
- Lead Data Table updates
- Error fallback branches (see T3-6/T3-7 docs)

## Stub workflow

Import [`waha-whatsapp-inbound.json`](../../../waha-whatsapp-inbound.json) as a starting point (inbound + normalize only; not a full production workflow).
