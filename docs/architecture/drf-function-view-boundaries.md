# DRF Function-View Boundaries

**Review date:** 2026-06-24

This document records why two production endpoints intentionally remain plain Django function views and should not be migrated to Django REST Framework (DRF) without a compelling new requirement.

---

## Decision summary

| Endpoint | Module | Route name | Decision |
|---|---|---|---|
| Twilio WhatsApp inbound webhook | `apps/webhooks/views.py` | `twilio-whatsapp-inbound` | **Remain function-based** |
| WhatsApp voice reply media | `apps/qualification/media_views.py` | `whatsapp-voice-reply-media` | **Remain function-based** |

DRF is used for internal JSON APIs requiring serializers, reusable permissions, standardized error contracts, and service orchestration. It is not mandatory for form-encoded third-party webhooks or binary streaming/file-serving endpoints.

---

## Endpoint 1 — Twilio WhatsApp inbound webhook

### Route

- **Path:** `/api/webhooks/twilio/whatsapp-inbound/`
- **Name:** `twilio-whatsapp-inbound`
- **View:** `twilio_whatsapp_inbound` in `apps/webhooks/views.py`

### Request / response contract

| Aspect | Behavior |
|---|---|
| Method | `POST` only (`405` for other methods via `@require_POST`) |
| Content type | `application/x-www-form-urlencoded` (Twilio form fields in `request.POST`) |
| Authentication | Twilio `X-Twilio-Signature` validated by `validate_twilio_signature()` using the externally visible request URL and parsed form parameters |
| Success | `200` with empty body |
| Invalid / missing signature | `403` with empty body |
| n8n forward failure | `502` with empty body |

### Why it remains function-based

1. **Third-party form contract** — Twilio sends URL-encoded form data, not the internal JSON API shape used by qualification extract/render-audio endpoints.
2. **Signature fidelity** — Validation depends on Django's raw `request.POST`, `request.build_absolute_uri()`, and Twilio's `RequestValidator`. DRF's `request.data` and JSON parser defaults do not apply and could change parameter handling or URL reconstruction assumptions.
3. **Thin adapter already** — The view validates, forwards to n8n via `forward_to_n8n()`, and maps two error paths. No JSON serialization, no reusable internal permission, no response schema.
4. **Low migration value** — DRF serializers, `JSONParser`, and `InternalWebhookSecretPermission` provide no benefit; migration risk to signature validation is non-trivial.
5. **Safe logging** — Failure logs use structured events with message SID prefixes only; bodies, phone numbers, and signature values are not logged.

### What should not be introduced

- DRF `APIView`, `GenericAPIView`, or ViewSet
- `request.data` or `JSONParser` for this route
- `InternalWebhookSecretPermission` (internal qualification secret is unrelated to Twilio)
- JSON success/error response bodies
- Broad request-body logging

### When to reconsider DRF

- Twilio changes to a JSON webhook contract with a documented, testable validation scheme that maps cleanly to DRF parsers
- A shared webhook framework is introduced that preserves byte-for-byte signature validation semantics
- Multiple form-encoded provider webhooks need shared middleware **without** altering Twilio's current validation path

Until then, keep validation in `apps/webhooks/twilio_validation.py` and forwarding in `apps/webhooks/n8n_forward.py`.

---

## Endpoint 2 — WhatsApp voice reply media

### Route

- **Path:** `/media/whatsapp_voice_replies/<uuid:audio_id>/`
- **Name:** `whatsapp-voice-reply-media`
- **View:** `whatsapp_voice_reply_media` in `apps/qualification/media_views.py`

### Request / response contract

| Aspect | Behavior |
|---|---|
| Methods | `GET`, `HEAD` only (`405` for others via `@require_http_methods`) |
| Authentication | None (public media URL returned by render-audio flow) |
| Path validation | Django `uuid` URL converter plus `is_valid_audio_id()` pattern check |
| File lookup | `find_audio_file()` under dated storage; TTL via `_file_is_expired()` |
| Success `GET` | `200`, `Content-Type: audio/ogg`, `FileResponse` stream |
| Success `HEAD` | `200`, `Content-Type: audio/ogg`, `Content-Length` set, empty body |
| Missing / invalid / expired | `404` (expired files deleted on access) |

### Why it remains function-based

1. **Binary response** — Returns OGG audio bytes via `FileResponse`, not JSON.
2. **Streaming semantics** — Direct file streaming and HEAD metadata are natural Django `HttpResponse` / `FileResponse` concerns.
3. **Small, focused view** — UUID validation, lookup, TTL check, and response selection fit in one adapter; domain rules live in `whatsapp_audio.py`.
4. **No DRF value** — Serializers and JSON renderers do not apply; permissions are intentionally absent for public playback URLs.
5. **No path leakage** — Responses expose only the public URL segment; filesystem layout and storage roots stay in domain helpers.

### What should not be introduced

- DRF serializers or `JSONRenderer`
- `APIView` with `content_negotiation_class` for binary audio
- Authentication on the public media URL unless product requirements change
- Error JSON bodies for missing media (keep `404` without internal details)

### When to reconsider DRF

- Media delivery moves to object storage with signed URLs (view may shrink or disappear)
- Multiple binary asset types need a unified download API with shared auth and caching headers
- A CDN or reverse proxy takes over all public media serving

Until then, keep storage, TTL, and lookup in `apps/qualification/whatsapp_audio.py`.

---

## Related DRF endpoints (context only)

Internal qualification JSON APIs (`ExtractAPIView`, `RenderAudioAPIView`) appropriately use DRF under `apps/qualification/api/`. The boundaries above are intentional exceptions, not gaps to close in the same style.

---

## Test coverage reference

| Endpoint | Primary test module |
|---|---|
| Twilio webhook | `apps/webhooks/tests/test_twilio_whatsapp_inbound.py` |
| Voice media | `apps/qualification/tests/test_whatsapp_audio_media.py` (focused media contract) and integration cases in `apps/qualification/tests/test_render_audio_endpoint.py` |

No migration of either endpoint to DRF is planned as of this review.
