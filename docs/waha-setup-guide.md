# WAHA setup guide (Nora AI WhatsApp)

Business WhatsApp number for this project: **+923121363468**.

This guide covers running WAHA, linking the number via QR, pointing webhooks at Django, and smoke-testing inbound/outbound messages.

## 1. Run WAHA with Docker

From the repo root, set webhook and API key in `.env` (see `.env.example`), then:

```bash
docker compose -f docker-compose.waha.yml down
docker compose -f docker-compose.waha.yml up -d
```

Dashboard / Swagger: [http://localhost:3000](http://localhost:3000)

Default session name: `default` (matches `WAHA_SESSION`).

Recommended engine for list messages: **NOWEB** (`WHATSAPP_DEFAULT_ENGINE=NOWEB` in the compose file). Reply buttons are fragile across engines; the Django layer falls back to numbered plain text if interactive send fails.

### Local Docker networking (important)

WAHA runs **inside** a container. Inside that container, `localhost` / `127.0.0.1` means the WAHA container itself — **not** Django on your laptop.

For local development, point the hook at the Docker host:

```env
WAHA_HOOK_URL=http://host.docker.internal:8000/api/webhooks/waha/whatsapp-inbound/
```

`docker-compose.waha.yml` adds `extra_hosts: host.docker.internal:host-gateway` so this works on Linux as well as Docker Desktop.

Production: set `WAHA_HOOK_URL` to your public Django HTTPS URL (same path). Do not hardcode URLs in the compose file; use environment variables.

After changing `.env` webhook settings, recreate the container:

```bash
docker compose -f docker-compose.waha.yml down
docker compose -f docker-compose.waha.yml up -d
```

Verify the container received the hook URL:

```bash
docker compose -f docker-compose.waha.yml exec waha printenv WHATSAPP_HOOK_URL WHATSAPP_HOOK_EVENTS WHATSAPP_HOOK_CUSTOM_HEADERS
```

## 2. Configure Django `.env`

```env
WAHA_BASE_URL=http://localhost:3000
# Production: https://waha.your-domain.com
WAHA_SESSION=default
WAHA_API_KEY=choose-a-strong-secret
# Optional; when empty, inbound accepts X-Api-Key matching WAHA_API_KEY.
WAHA_WEBHOOK_SECRET=choose-a-strong-secret
# Local Docker → host Django (see networking notes above).
WAHA_HOOK_URL=http://host.docker.internal:8000/api/webhooks/waha/whatsapp-inbound/
# Production: https://<django-public-host>/api/webhooks/waha/whatsapp-inbound/
# WAHA sends this header on each webhook POST (must match Django secret above).
WAHA_HOOK_CUSTOM_HEADERS=X-Api-Key:choose-a-strong-secret
N8N_WEBHOOK_URL=https://<n8n>/webhook/whatsapp-inbound
N8N_WEBHOOK_SECRET=…
N8N_QUALIFICATION_API_SECRET=…
BASE_WEBHOOK_URL=https://<django-public-host>
```

Compose maps:

| `.env` | WAHA process env |
|--------|------------------|
| `WAHA_HOOK_URL` | `WHATSAPP_HOOK_URL` |
| `WAHA_HOOK_CUSTOM_HEADERS` | `WHATSAPP_HOOK_CUSTOM_HEADERS` |
| (fixed) | `WHATSAPP_HOOK_EVENTS=message` |

Remove any leftover Twilio WhatsApp variables (`TWILIO_*` Content SIDs / account SID / auth token / from number).

Note: if `DJANGO_SECRET_KEY` (or other unused `.env` values) contain `$…`, `docker compose` may print harmless “variable is not set” warnings while substituting the project `.env`. Those do not affect WAHA when `WAHA_*` are set.

## 3. Start session and scan QR (+923121363468)

Global webhooks from `WHATSAPP_HOOK_*` apply to all sessions. You can still attach a per-session webhook when creating the session (same URL and `X-Api-Key` header).

1. Open Swagger at `http://localhost:3000`.
2. `POST /api/sessions/` with:

```json
{
  "name": "default",
  "config": {
    "webhooks": [
      {
        "url": "http://host.docker.internal:8000/api/webhooks/waha/whatsapp-inbound/",
        "events": ["message"],
        "hmac": null,
        "customHeaders": [
          { "name": "X-Api-Key", "value": "choose-a-strong-secret" }
        ]
      }
    ]
  }
}
```

(Use your public Django HTTPS URL in production instead of `host.docker.internal`.)

3. `GET /api/default/auth/qr` (or use the Dashboard) and scan with the phone that owns **+923121363468**.
4. Confirm session status is `WORKING`.

## 4. Webhook URL checklist

| Component | URL |
|-----------|-----|
| WAHA → Django inbound | `…/api/webhooks/waha/whatsapp-inbound/` |
| Django → n8n | `N8N_WEBHOOK_URL` |
| n8n → Django extract | `https://<django>/api/internal/qualification/extract/` |
| n8n → Django send (optional) | `https://<django>/api/internal/whatsapp/send/` |

Django validates inbound with `X-Api-Key` = `WAHA_WEBHOOK_SECRET` (or `WAHA_API_KEY`). There is no Twilio signature check on this path. The view parses WAHA JSON, builds the extract-shaped payload, and forwards JSON to n8n unchanged from the prior transport contract.

## 5. Test outbound text

```bash
curl -sS -X POST "$WAHA_BASE_URL/api/sendText" \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: $WAHA_API_KEY" \
  -d '{
    "session": "default",
    "chatId": "9233XXXXXXXXX@c.us",
    "text": "Hello from WAHA"
  }'
```

Or via Django:

```bash
curl -sS -X POST "$BASE_WEBHOOK_URL/api/internal/whatsapp/send/" \
  -H "Content-Type: application/json" \
  -H "X-Internal-Webhook-Secret: $N8N_QUALIFICATION_API_SECRET" \
  -d '{"phone_number":"+9233XXXXXXXXX","message":"Hello from Django"}'
```

## 6. Test inbound

1. From another phone, send a WhatsApp text to **+923121363468**.
2. Confirm WAHA Event Monitor shows a `message` event.
3. Confirm Django returns 200 and n8n receives JSON with `whatsapp_number`, `message`, `message_sid`.
4. Confirm extract runs and a reply is sent (language picker on first contact).

## 7. Interactive messages

Django sends:

- Language buttons (`lang_en` / `lang_ar`)
- Main menu list (`continue`, `restart`, `language`, `human`)
- Referral source list (`google`, `instagram`, …)
- Business type list (`biz_*`) for existing customers

If WAHA returns 4xx/5xx for buttons/lists, Django sends numbered text instead (qualification already accepts numbers and IDs).

## 8. n8n checklist

See [docs/integrations/n8n/WAHA-whatsapp-transport.md](integrations/n8n/WAHA-whatsapp-transport.md).

- Remove Twilio nodes
- Keep extract + language-gate IF + lead updates
- Send text via Django `/api/internal/whatsapp/send/` or WAHA `/api/sendText`
- When `option_template` is set, do not send Content templates again

## 9. Voice notes

Inbound voice: WAHA stores media under `/api/files/…`; Django downloads with `X-Api-Key` and transcribes via Deepgram.

Outbound voice: n8n calls render-audio, then WAHA `sendVoice` / `sendFile` with the public media URL.
