# Preferred Phone Local Validation Fix Report

## Root Cause
- After a customer declined WhatsApp-number confirmation (`whatsapp_confirmed = false`), the next missing field became `preferred_phone`.
- A bare valid E.164 reply such as `+923246271156` still went through OpenRouter extraction.
- The LLM often omitted `preferred_phone`, so filtering rejected it as `value_missing` and Django asked for the same number again.
- `apply_phone_confirmation_guard()` only accepts embedded numbers inside explicit rejection phrases; a bare phone reply was cleared and never persisted locally.

## Architecture Used
- **Current qualification field detection:** `get_active_next_field()` / `_next_missing_field()` in `conversation_flow.py`
- **Local normalization:** `collapse_phone_formatting()` and `normalize_preferred_phone_input()` in `domain/validators.py`
- **E.164 validation:** existing `is_valid_e164_phone_number()` contract unchanged
- **State persistence:** `save_accepted_fields()` via `try_handle_preferred_phone_turn()`
- **OpenRouter bypass rule:** when `next_field == preferred_phone` and the reply is not a free-text sentence embedding an E.164 number, handle locally in `qualification_turn.py` before `extract_qualification_from_openrouter()`

## Customer Behavior Before and After

### Valid number path
| Step | Before | After |
|---|---|---|
| Customer sends `No` to WhatsApp confirmation | Ask for preferred phone | Same |
| Customer sends `+923246271156` | Re-ask for phone (`value_missing`) | Save phone, complete qualification |
| Customer sends `+92 324 627 1156` | Re-ask | Normalize and accept |
| Customer sends `(0324) 6271156` | Re-ask | Convert local trunk `0…` using `+92` from WhatsApp number and accept |

### Invalid number path
| Input | Result |
|---|---|
| `abc`, `123`, `+12`, `not a phone` | Localized `invalid_phone` message, stay on `preferred_phone`, no OpenRouter |
| Arabic session + invalid reply | Arabic `invalid_phone` message |

### English and Arabic behavior
- Completion and invalid-phone messages use existing `get_customer_message()` catalog keys.
- Structured response fields (`accepted_fields`, `preferred_phone`, `qualification_status`) are unchanged.

## Files Changed
| File | Purpose |
|---|---|
| `apps/qualification/domain/validators.py` | Shared phone formatting collapse, preferred-phone normalization, direct-reply / OpenRouter routing helpers |
| `apps/qualification/conversation_flow.py` | `try_handle_preferred_phone_turn()` local accept/reject path |
| `apps/qualification/qualification_turn.py` | Invoke local preferred-phone handler before OpenRouter |
| `apps/qualification/phone_confirmation.py` | Reuse shared `collapse_phone_formatting()` |
| `apps/qualification/tests/test_preferred_phone_local_validation.py` | Focused end-to-end tests for local phone acceptance |
| `apps/qualification/tests/test_domain_validators.py` | Unit tests for normalization helpers |
| `apps/qualification/tests/test_arabic_language_propagation.py` | Invalid-phone tests updated for local path (no OpenRouter mock required) |

## Tests Run
| Command | Result |
|---|---|
| `.venv/bin/python manage.py makemigrations --check --dry-run` | No changes detected |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 DJANGO_SETTINGS_MODULE=config.settings_test .venv/bin/python -m pytest -p pytest_django.plugin -q` | **613 passed** |

## n8n Contract
- **Required inbound message field:** n8n must continue forwarding the customer `Body` as `message` unchanged (existing contract).
- **No new n8n routing required:** the fix is entirely in Django qualification turn handling after the existing extract endpoint receives the message.
