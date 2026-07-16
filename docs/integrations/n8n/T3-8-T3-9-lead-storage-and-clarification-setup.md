# T3.8 / T3.9 — n8n lead storage and clarification setup

## Purpose

Complete the remaining Phase 3 n8n work for:

- **T3.8** — store multiple `accepted_fields` from one customer message safely
- **T3.9** — do not store low-confidence/missing fields and trigger the next
  clarification question

Django already returns safe `accepted_fields` / `rejected_fields`. This guide
configures the live n8n workflow only.

## Why this is a manual guide

`twilio-whatsapp-inbound.json` in this repository is a 2-node stub. It does not
contain `Call Django Qualification API`, lead lookup/update nodes, or Data Table
configuration. Apply the steps below in n8n Cloud. Do not import an invented full
workflow JSON from this repo.

## Target workflow after setup

```text
WhatsApp Inbound Webhook
→ Normalize Twilio Message
→ Allow New MessageSid
→ Record MessageSid
→ Call Django Qualification API [success]
→ Prepare Accepted Lead Updates
→ Lookup Lead by WhatsApp
→ Lead Exists?
   ├─ yes → Update Existing Lead (accepted fields only)
   └─ no  → Create New Lead (base + accepted fields only)
→ Select Next Clarification Question
→ Clarification Needed?
   ├─ yes → Set Clarification State and Message
   │         → Send Clarification WhatsApp Reply
   └─ no  → Send WhatsApp reply (existing normal success message)
```

The T3.6/T3.7 error branch from `Call Django Qualification API` remains unchanged
and must still bypass all lead update nodes.

---

## Step 1 — Inspect Data Table columns

1. Open n8n Cloud → **Data Tables** (or your existing leads table).
2. Open the table used by `Lookup Lead by WhatsApp`.
3. Confirm these columns exist (create any that are missing):

| Column | Type | Purpose |
| --- | --- | --- |
| `whatsapp_number` | string | Lead key (E.164, no `whatsapp:` prefix) |
| `project_type` | string | `new_website` or `website_upgrade` only |
| `requirements` | string | Customer requirements text |
| `referral_source` | string | How the customer heard about you |
| `conversation_state` | string | Clarification wait state |

4. Do **not** add `whatsapp_confirmed` or `preferred_phone` columns in this task
   unless they already exist for later work. This task must not store phone
   confirmation fields from rejected Django output.

---

## Step 2 — Add `Prepare Accepted Lead Updates`

Place this node immediately after `Call Django Qualification API` **success**
output and before `Lookup Lead by WhatsApp`.

1. Add a **Code** node (or **Edit Fields (Set)** if you prefer, but Code is
   clearer for conditional field building).
2. Name it exactly:

```text
Prepare Accepted Lead Updates
```

3. Use this JavaScript:

```javascript
const django = $('Call Django Qualification API').first().json;
const accepted = django.accepted_fields ?? {};

const allowedKeys = ['project_type', 'requirements', 'referral_source'];
const leadPatch = {};

for (const key of allowedKeys) {
  if (Object.prototype.hasOwnProperty.call(accepted, key)) {
    const value = accepted[key];
    if (value !== null && value !== undefined && String(value).trim() !== '') {
      leadPatch[key] = value;
    }
  }
}

return [
  {
    json: {
      accepted_fields: accepted,
      rejected_fields: django.rejected_fields ?? {},
      human_handoff_requested: django.human_handoff_requested === true,
      lead_patch: leadPatch,
    },
  },
];
```

### Safety rules enforced here

- Reads only `project_type`, `requirements`, `referral_source` from
  `accepted_fields`.
- Ignores `whatsapp_confirmed` and `preferred_phone` even if they appear in the
  Django response.
- Never writes `null`, blank strings, or `rejected_fields` reason codes.
- Omits absent keys from `lead_patch` entirely.

---

## Step 3 — Configure existing lead update (accepted fields only)

### `Update Existing Lead`

1. Open the node named `Update Existing Lead`.
2. Map columns **only** from `{{ $json.lead_patch }}` keys that exist.
3. Use conditional / partial update behavior:
   - Update `project_type` only when `lead_patch.project_type` is present.
   - Update `requirements` only when `lead_patch.requirements` is present.
   - Update `referral_source` only when `lead_patch.referral_source` is present.
4. Do **not** map `whatsapp_confirmed`, `preferred_phone`, `rejected_fields`, or
   empty values.
5. Do **not** clear existing column values when a key is missing from
   `lead_patch`.

Example expression pattern for one field:

```javascript
{{ $json.lead_patch.project_type ? $json.lead_patch.project_type : undefined }}
```

Use your Data Table node’s “update only defined fields” option if available.

### `Create New Lead`

1. Open `Create New Lead`.
2. Always set base identity from normalized inbound data, for example:
   - `whatsapp_number` from `Normalize Twilio Message`
3. Add accepted qualification fields from `lead_patch` only.
4. Leave `project_type`, `requirements`, and `referral_source` empty when not
   present in `lead_patch`.

---

## Step 4 — Add `Select Next Clarification Question`

Place this node after lead create/update and before outbound messaging.

1. Add a **Code** node named exactly:

```text
Select Next Clarification Question
```

2. Use this JavaScript:

```javascript
const accepted = $('Prepare Accepted Lead Updates').first().json.accepted_fields ?? {};
const lead = $input.first().json;

function isValidProjectType(value) {
  return value === 'new_website' || value === 'website_upgrade';
}

function isValidText(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

function resolvedProjectType() {
  return isValidProjectType(accepted.project_type) || isValidProjectType(lead.project_type);
}

function resolvedRequirements() {
  return isValidText(accepted.requirements) || isValidText(lead.requirements);
}

function resolvedReferralSource() {
  return isValidText(accepted.referral_source) || isValidText(lead.referral_source);
}

let nextField = null;
let conversationState = null;
let clarificationMessage = null;

if (!resolvedProjectType()) {
  nextField = 'project_type';
  conversationState = 'WAITING_FOR_PROJECT_TYPE';
  clarificationMessage =
    'Are you looking for a new website or an upgrade to your existing website?';
} else if (!resolvedRequirements()) {
  nextField = 'requirements';
  conversationState = 'WAITING_FOR_REQUIREMENTS';
  clarificationMessage = 'What are you specifically looking for?';
} else if (!resolvedReferralSource()) {
  nextField = 'referral_source';
  conversationState = 'WAITING_FOR_REFERRAL_SOURCE';
  clarificationMessage = 'How did you hear about us?';
}

return [
  {
    json: {
      ...lead,
      clarification_needed: Boolean(nextField),
      next_field: nextField,
      conversation_state: conversationState,
      clarification_message: clarificationMessage,
    },
  },
];
```

### Priority order (one question at a time)

1. `project_type`
2. `requirements`
3. `referral_source`

A field is unresolved when it is **not** in `accepted_fields` with a valid value
**and** the lead does not already have a valid stored value.

---

## Step 5 — Add clarification branch nodes

### `Clarification Needed?`

1. Add an **IF** node named exactly:

```text
Clarification Needed?
```

2. Condition:

```text
{{ $json.clarification_needed }} is true
```

### `Set Clarification State and Message`

On the **true** branch:

1. Add a **Data Table → Update** node (or reuse lead update node) named:

```text
Set Clarification State and Message
```

2. Update only:

```text
conversation_state = {{ $json.conversation_state }}
```

3. Do not overwrite `project_type`, `requirements`, or `referral_source` here.

### `Send Clarification WhatsApp Reply`

1. Add a **Twilio** node named exactly:

```text
Send Clarification WhatsApp Reply
```

2. Reuse the existing Twilio credential. Do not change credentials.
3. **To**:

```javascript
{{ $('Normalize Twilio Message').first().json.from.startsWith('whatsapp:') ? $('Normalize Twilio Message').first().json.from : 'whatsapp:' + $('Normalize Twilio Message').first().json.from }}
```

4. **Message**:

```javascript
{{ $json.clarification_message }}
```

5. Do not expose confidence scores, rejected reasons, or Django errors.

### Normal success route

On the **false** branch of `Clarification Needed?`, connect to the existing
`Send WhatsApp reply` node unchanged.

---

## Step 6 — Question and state mappings

| Unresolved field | `conversation_state` | Customer message |
| --- | --- | --- |
| `project_type` | `WAITING_FOR_PROJECT_TYPE` | Are you looking for a new website or an upgrade to your existing website? |
| `requirements` | `WAITING_FOR_REQUIREMENTS` | What are you specifically looking for? |
| `referral_source` | `WAITING_FOR_REFERRAL_SOURCE` | How did you hear about us? |

---

## Step 7 — Test T3.8 (mocked successful Django output)

Use n8n test execution or pin data. Do not call real OpenRouter.

### Mock Django `200` body

```json
{
  "accepted_fields": {
    "project_type": "new_website",
    "requirements": "I need a new website for my restaurant",
    "referral_source": "Facebook"
  },
  "rejected_fields": {
    "whatsapp_confirmed": "value_missing",
    "preferred_phone": "value_missing"
  },
  "human_handoff_requested": false
}
```

### Representative inbound message

```text
I need a new website for my restaurant. I found you on Facebook.
```

### Verify

- [ ] `lead_patch` contains only the three accepted qualification fields
- [ ] `project_type = new_website`
- [ ] `requirements = I need a new website for my restaurant`
- [ ] `referral_source = Facebook`
- [ ] `whatsapp_confirmed` and `preferred_phone` are not stored
- [ ] `Clarification Needed?` is false when all three fields are accepted
- [ ] existing normal `Send WhatsApp reply` runs

Run without real Twilio outbound if Sandbox restrictions apply; inspect execution
data instead.

---

## Step 8 — Test T3.9 (mocked low-confidence Django output)

### Mock Django `200` body

```json
{
  "accepted_fields": {
    "requirements": "I need a website for my restaurant",
    "referral_source": "Facebook"
  },
  "rejected_fields": {
    "project_type": "low_confidence"
  },
  "human_handoff_requested": false
}
```

### Verify

- [ ] `project_type` is **not** stored on the lead
- [ ] `requirements` and `referral_source` may be stored
- [ ] `conversation_state` becomes `WAITING_FOR_PROJECT_TYPE`
- [ ] only the project-type question is selected
- [ ] clarification message is:
  `Are you looking for a new website or an upgrade to your existing website?`
- [ ] normal success reply does **not** run on this branch
- [ ] no confidence score or `low_confidence` text is sent to the customer

---

## Step 9 — Preserve existing valid lead values

### Regression check for existing lead

1. Start with a lead that already has `referral_source = Friend`.
2. Mock Django output where `referral_source` is rejected/low-confidence and
   absent from `accepted_fields`.
3. Verify `referral_source` remains `Friend`.
4. Verify only unresolved fields trigger clarification.

---

## Out of scope for this task

- Phone confirmation questions
- Alternative phone handling
- Booking links
- Human handoff routing
- Retry counters
- Full qualification completion logic
- Changing Django code, credentials, or `.env`
