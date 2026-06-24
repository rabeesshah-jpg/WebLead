# T3.6 / T3.7 — n8n qualification failure fallback setup

## Purpose

Complete the remaining Phase 3 n8n work for:

- **T3.6** — OpenRouter timeout / provider failure fallback
- **T3.7** — malformed or invalid LLM JSON fallback

The Django backend already returns safe HTTP errors (`502`, `503`, `500`) and does
not write or corrupt lead data. This guide adds the missing n8n error branch only.

## Why this is a manual guide

The repository file `twilio-whatsapp-inbound.json` is a minimal stub (webhook +
payload inspect only). It does not contain the live nodes such as
`Normalize Twilio Message`, `Call Django Qualification API`, or lead update logic.
Do **not** import a invented full workflow JSON from this repo. Apply the steps
below directly in the live n8n workflow editor.

## Target workflow routes

### Current success route (keep unchanged)

```text
WhatsApp Inbound Webhook
→ Normalize Twilio Message
→ Allow New MessageSid
→ Record MessageSid
→ Call Django Qualification API  (success output)
→ Lookup Lead by WhatsApp
→ Lead Exists?
→ Update Existing Lead / Create New Lead
→ Send WhatsApp reply
```

### New failure route (add)

```text
Call Django Qualification API  (error output)
→ Build Qualification Fallback
→ Send Qualification Fallback WhatsApp Reply
```

The error output must **never** connect to:

```text
Lookup Lead by WhatsApp
Lead Exists?
Update Existing Lead
Create New Lead
```

## Manual n8n UI steps

### Step 1 — Open the live workflow

1. Sign in to n8n.
2. Open the existing workflow that contains the node named exactly
   `Call Django Qualification API`.
3. Confirm the upstream path is still:

```text
Normalize Twilio Message
→ Allow New MessageSid
→ Record MessageSid
→ Call Django Qualification API
```

Do not change inbound deduplication.

### Step 2 — Configure `Call Django Qualification API` error handling

1. Click the node named exactly `Call Django Qualification API`.
2. Open **Settings** (gear icon) or the node settings panel.
3. Find **On Error**.
4. Set it to:

```text
Continue (using error output)
```

5. Save the node.

Expected behavior after this change:

| Output | Connected downstream |
| --- | --- |
| **Success** (main output 0) | `Lookup Lead by WhatsApp` — unchanged |
| **Error** (error output) | new fallback branch only |

This error branch must handle:

- HTTP `502` — OpenRouter timeout, provider failure, invalid assistant JSON
- HTTP `503` — qualification service unavailable
- HTTP `500` — unexpected safe server failure
- Network-level HTTP request errors (timeout, DNS, connection reset)

Do **not** change the HTTP method, URL, headers credential, or JSON body on this
node unless they were already wrong. Do not embed secrets in the workflow export.

### Step 3 — Verify the success output is still wired correctly

1. From `Call Django Qualification API`, confirm the **success** output still
   connects only to `Lookup Lead by WhatsApp`.
2. Do not move lead lookup/create/update nodes onto the error branch.

### Step 4 — Add `Build Qualification Fallback`

1. Add a new **Edit Fields (Set)** node.
2. Name it exactly:

```text
Build Qualification Fallback
```

3. Set **Mode** to **Manual Mapping** (or equivalent “define fields below”).
4. Add one field:

| Field name | Type | Value |
| --- | --- | --- |
| `fallback_message` | String | `Sorry, I'm having trouble processing your request right now. Please send it again in a moment, or a team member will follow up.` |

Use the exact message text above. Do not add customer phone numbers or error
details to this node.

5. Connect:

```text
Call Django Qualification API  (error output)
→ Build Qualification Fallback
```

### Step 5 — Add `Send Qualification Fallback WhatsApp Reply`

1. Add a **Twilio** node (WhatsApp / send message action already used elsewhere
   in the project).
2. Name it exactly:

```text
Send Qualification Fallback WhatsApp Reply
```

3. Reuse the existing Twilio credential already configured in the workflow.
   Do not create or change credentials in this task.
4. Set the **To** / recipient field to this expression:

```javascript
{{ $('Normalize Twilio Message').first().json.from.startsWith('whatsapp:') ? $('Normalize Twilio Message').first().json.from : 'whatsapp:' + $('Normalize Twilio Message').first().json.from }}
```

5. Set the **Message** / body field to:

```javascript
{{ $json.fallback_message }}
```

6. Connect:

```text
Build Qualification Fallback
→ Send Qualification Fallback WhatsApp Reply
```

7. Confirm this Twilio node sends only to the original inbound sender from
   `Normalize Twilio Message`. Do not hard-code any customer phone number.

### Step 6 — Final wiring checklist

```text
SUCCESS:
Call Django Qualification API [success]
  → Lookup Lead by WhatsApp
    → Lead Exists?
      → Update Existing Lead / Create New Lead
        → Send WhatsApp reply

FAILURE:
Call Django Qualification API [error]
  → Build Qualification Fallback
    → Send Qualification Fallback WhatsApp Reply
```

Safety checks:

- [ ] Error branch does not connect to any lead lookup/update/create node
- [ ] Success branch is unchanged
- [ ] `Allow New MessageSid` / `Record MessageSid` remain upstream of the Django call
- [ ] No HTTP status codes, stack traces, OpenRouter text, API keys, or internal URLs
      are sent to the customer
- [ ] Fallback message uses only `fallback_message`

## Testing (no real OpenRouter or customer traffic required)

### Test A — Simulated Django `502`

1. Temporarily change the `Call Django Qualification API` URL to a test path that
   returns `502`, **or** use n8n’s node test override / mock response feature if
   available in your n8n version.
2. Execute the workflow with a test inbound item that passes
   `Allow New MessageSid`.
3. Verify:
   - execution continues on the **error** output
   - `Build Qualification Fallback` runs
   - `Send Qualification Fallback WhatsApp Reply` runs
   - `Lookup Lead by WhatsApp`, `Lead Exists?`, `Update Existing Lead`, and
     `Create New Lead` do **not** run on this branch
4. Verify the outgoing message body is exactly:

```text
Sorry, I'm having trouble processing your request right now. Please send it again in a moment, or a team member will follow up.
```

5. Restore the real Django URL after testing.

### Test B — Simulated network timeout

1. Temporarily point the HTTP node to an unroutable host or use a very short
   timeout to trigger a network-level failure.
2. Confirm the same error branch runs and no lead nodes execute.
3. Restore normal settings.

### Test C — Success path regression

1. Restore the real Django endpoint.
2. Send a valid test message through the success path.
3. Confirm `Lookup Lead by WhatsApp` and downstream lead logic still run on HTTP
   `200` only.

## What this completes

| Task | n8n status after applying this guide |
| --- | --- |
| T3.6 OpenRouter timeout fallback | Customer receives safe fallback; no lead write |
| T3.7 invalid LLM JSON fallback | Customer receives safe fallback; no lead write |

Django behavior is unchanged. Lead preservation on failure is enforced because the
error branch bypasses all lead update/create nodes.

## Out of scope

- Changing Django qualification code or tests
- Changing Twilio or n8n credentials
- Creating a second MessageSid deduplication system
- Exporting a full workflow JSON from this repository (source stub is incomplete)
