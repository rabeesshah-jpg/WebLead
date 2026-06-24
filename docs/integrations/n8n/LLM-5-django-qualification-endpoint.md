# LLM-5: n8n → Django qualification endpoint integration contract

## Purpose

This document defines the safe integration contract for n8n to call the Django
internal qualification endpoint. It is documentation and workflow design guidance
only. It does not deploy or modify any n8n workflow, Twilio configuration, or
Django application code.

## Workflow placement

Add one HTTP Request node with this exact name:

```text
Call Django Qualification API
```

Place it after these upstream nodes:

```text
Normalize Twilio Message
→ Allow New MessageSid
→ Record MessageSid
→ Lookup/Create base lead
```

Place it before these downstream nodes:

```text
Update lead with accepted fields
→ Send next WhatsApp message
```

The qualification call must happen only after `MessageSid` deduplication and
base lead lookup/creation. Lead updates and customer replies must happen only
after a successful Django `200` response.

## Endpoint

```text
POST /api/internal/qualification/extract/
```

Full URL example:

```text
https://<django-host>/api/internal/qualification/extract/
```

Use the production Django host configured for the deployment. Do not call
localhost from production n8n unless this is an explicit local test environment.

## Authentication

### Header

```text
X-Internal-Webhook-Secret: <secret value>
```

### Django setting

The header value must match Django environment variable:

```text
N8N_QUALIFICATION_API_SECRET
```

### n8n credential storage

Store the secret in an n8n credential attached to the HTTP Request node. Do
not hardcode the secret in node parameters, expressions, or workflow JSON.

Do not reuse the Django-to-n8n forwarding secret (`N8N_WEBHOOK_SECRET`) unless
the deployment team intentionally configures both values to be the same. The
default recommendation is to keep them separate:

| Secret | Direction | Purpose |
| --- | --- | --- |
| `N8N_WEBHOOK_SECRET` | Django → n8n | Validates inbound Twilio webhook forwarding |
| `N8N_QUALIFICATION_API_SECRET` | n8n → Django | Validates internal qualification API calls |

## Request contract

### Method and content type

```text
POST
Content-Type: application/json
```

### JSON body

```json
{
  "message": "<normalized inbound customer message>",
  "whatsapp_number": "<normalized customer E.164 number>"
}
```

Only these two keys are allowed. Extra keys are rejected.

### Field rules

#### `message`

- Source: the normalized inbound customer message body from Twilio.
- Must be a non-empty string after trimming leading and trailing whitespace.
- Use the customer text exactly as normalized upstream. Do not invent,
  summarize, or append content before sending it to Django.

#### `whatsapp_number`

- Source: the incoming customer number from Twilio `From`.
- Remove the `whatsapp:` prefix before sending the value to Django.
- Do not use Twilio `To`; that field is the business or Sandbox number.
- Must be E.164 format, for example `+923001234567`.
- Pattern accepted by Django:

```text
^\+[1-9][0-9]{7,14}$
```

### Mapping example

If Twilio sends:

```text
From=whatsapp:+923001234567
Body=I need a new website for my restaurant
```

Then n8n must call Django with:

```json
{
  "message": "I need a new website for my restaurant",
  "whatsapp_number": "+923001234567"
}
```

## Successful response

HTTP status:

```text
200
```

Body shape:

```json
{
  "accepted_fields": {
    "project_type": "new_website",
    "requirements": "website for a restaurant"
  },
  "rejected_fields": {
    "referral_source": "value_missing"
  },
  "human_handoff_requested": false
}
```

### `accepted_fields`

Contains only qualification fields that passed Django confidence filtering.
Possible field names:

- `project_type`
- `requirements`
- `referral_source`
- `whatsapp_confirmed`
- `preferred_phone`

Possible `project_type` values:

- `new_website`
- `website_upgrade`

`whatsapp_confirmed` may be `true` or `false`. A confident `false` is a valid
accepted answer and must be treated as real customer data.

Confidence scores are not returned by this endpoint.

### `rejected_fields`

Object keyed by field name. Values are safe reason codes only:

| Code | Meaning |
| --- | --- |
| `value_missing` | The model returned no usable value for the field |
| `low_confidence` | A value was present but did not meet the confidence threshold |

Rejected fields are informational. They must not be written to the lead.

### `human_handoff_requested`

Boolean routing flag. It is not a lead-data field.

## Error responses

Django returns safe generic JSON only. n8n must not expose these messages to
the customer verbatim.

| HTTP status | Example body | Typical cause |
| --- | --- | --- |
| `400` | `{"error": "Invalid request."}` | Malformed JSON, missing fields, invalid E.164 |
| `403` | `{"error": "Forbidden."}` | Missing or wrong `X-Internal-Webhook-Secret` |
| `502` | `{"error": "Qualification service request failed."}` | OpenRouter or extraction failure |
| `503` | `{"error": "Qualification service is unavailable."}` | Missing Django secret or OpenRouter config |
| `500` | `{"error": "Internal server error."}` | Unexpected Django failure |

Wrong HTTP methods such as `GET` are rejected by Django and must not be used.

## Lead-update safety rules

Apply these rules in n8n after `Call Django Qualification API`:

1. Only fields inside `accepted_fields` may update the lead.
2. Missing fields must not be sent as blank values.
3. Rejected fields must not overwrite existing lead data.
4. `human_handoff_requested` is a routing flag, not a lead-data field.
5. A Django `400`, `403`, `502`, `503`, or `500` response must not update
   qualification fields.
6. On a Django failure, route to a simple safe fallback branch; do not expose
   provider errors to the customer.
7. The workflow must not send a duplicate reply when the same `MessageSid` is
   replayed.

Practical update pattern:

- Iterate only over keys present in `accepted_fields`.
- Patch the lead with those key/value pairs only.
- Leave all other lead columns unchanged.
- Branch on `human_handoff_requested` separately from lead field updates.

## Recommended n8n node configuration

Node name:

```text
Call Django Qualification API
```

Suggested settings:

- Method: `POST`
- URL: `https://<django-host>/api/internal/qualification/extract/`
- Authentication: generic credential or header credential supplying
  `X-Internal-Webhook-Secret`
- Body content type: `JSON`
- Body:

```json
{
  "message": "={{ $json.normalized_message }}",
  "whatsapp_number": "={{ $json.normalized_whatsapp_number }}"
}
```

Use the exact normalized field names produced by `Normalize Twilio Message`.
Adjust expressions only to match the real upstream item shape; do not rename
the Django contract fields.

On success, continue only when HTTP status is `200`.

On `400`, `403`, `502`, `503`, or `500`, route to the safe fallback branch and
skip lead qualification updates.

## Manual n8n test plan

Run these tests in a non-production or controlled test workflow before enabling
production traffic.

### 1. Valid message with high-confidence fields

- Send a clear inbound WhatsApp message with project type and requirements.
- Expect Django `200`.
- Expect multiple entries in `accepted_fields`.
- Verify lead updates only for returned accepted keys.

### 2. Message with some low-confidence fields

- Send an ambiguous message where some fields should be rejected.
- Expect Django `200`.
- Expect `rejected_fields` to contain `low_confidence` for uncertain fields.
- Verify accepted fields update the lead and rejected fields do not overwrite
  existing lead values.

### 3. Missing or wrong internal secret gives `403`

- Remove the header or use an incorrect credential value.
- Expect Django `403` with `{"error": "Forbidden."}`.
- Verify no lead qualification fields are updated.
- Verify no customer-facing provider error is sent.

### 4. OpenRouter unavailable gives safe failure and no lead overwrite

- Test in an environment where OpenRouter is misconfigured or unavailable.
- Expect Django `502` or `503`.
- Route to the fallback branch.
- Verify existing lead values remain unchanged.

### 5. Same `MessageSid` replay causes no duplicate update or reply

- Replay the same Twilio payload with the same `MessageSid`.
- Confirm `Allow New MessageSid` blocks the duplicate path.
- Verify Django is not called again for the replay.
- Verify no second WhatsApp reply is sent.

### 6. Existing lead keeps prior valid values when incoming fields are rejected

- Start with a lead that already has valid `referral_source`.
- Send a new message where Django rejects `referral_source`.
- Expect Django `200` with `referral_source` in `rejected_fields`.
- Verify the stored `referral_source` remains the previous valid value.

### 7. `whatsapp_confirmed=false` at high confidence is handled as a real answer

- Send a message where the customer clearly says the current WhatsApp number is
  not the best contact number.
- Expect Django `200`.
- Expect `accepted_fields.whatsapp_confirmed` to be `false`.
- Verify n8n stores `false` as a real answer and does not treat it as missing
  data.

## Out of scope for this document

- Creating or editing n8n workflows
- Creating n8n credentials in a live instance
- Twilio webhook or signature changes
- Django code changes
- Lead database schema design beyond the update safety rules above
