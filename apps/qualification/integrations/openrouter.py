"""OpenRouter HTTP transport for lead-qualification completions."""

from __future__ import annotations

import hashlib
import json
import socket
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from django.conf import settings

from apps.qualification.domain.latency_profiling import elapsed_ms_since, log_latency_step
from apps.qualification.persistence.cache_backend import (
    default_cache_ttl_seconds,
    get_qualification_cache_backend,
    openrouter_cache_key,
)
from apps.qualification.prompts import build_extraction_system_prompt, build_extraction_user_message

OPENROUTER_CACHE_PREFIX = "openrouter:"


class OpenRouterConfigurationError(Exception):
    """Raised when OpenRouter client settings are incomplete."""


class OpenRouterRequestError(Exception):
    """Raised when the OpenRouter HTTP request fails."""


class OpenRouterTimeoutError(OpenRouterRequestError):
    """Raised when the OpenRouter HTTP request times out."""


class OpenRouterResponseError(Exception):
    """Raised when the OpenRouter response cannot be used."""


def clear_openrouter_completion_cache() -> None:
    """Clear cached OpenRouter completion entries. Intended for tests."""
    get_qualification_cache_backend().delete_by_prefix(OPENROUTER_CACHE_PREFIX)


def _validate_configuration() -> None:
    if not settings.OPENROUTER_API_KEY:
        raise OpenRouterConfigurationError("OpenRouter API key is not configured")
    if not settings.OPENROUTER_MODEL:
        raise OpenRouterConfigurationError("OpenRouter model is not configured")


def _normalize_customer_message(customer_message: str) -> str:
    return " ".join(customer_message.split())


def _build_completion_cache_key(
    *,
    message_sid: str | None,
    customer_message: str,
    known_whatsapp_number: str,
    phone_confirmation_question_asked: bool,
) -> str | None:
    if not message_sid:
        return None
    normalized_message = _normalize_customer_message(customer_message)
    payload = (
        f"{message_sid}\n{known_whatsapp_number}\n"
        f"{phone_confirmation_question_asked}\n{normalized_message}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_request_payload(
    *,
    customer_message: str,
    known_whatsapp_number: str,
    phone_confirmation_question_asked: bool = False,
    collected_fields: dict[str, Any] | None = None,
    recent_history: list[dict[str, str]] | None = None,
    conversation_language: str = "en",
) -> dict[str, Any]:
    normalized_message = _normalize_customer_message(customer_message)
    system_prompt = build_extraction_system_prompt(
        conversation_language=conversation_language,
    )
    user_content = build_extraction_user_message(
        customer_message=normalized_message,
        known_whatsapp_number=known_whatsapp_number,
        phone_confirmation_question_asked=phone_confirmation_question_asked,
        collected_fields=collected_fields,
        recent_history=recent_history,
    )
    max_tokens = settings.OPENROUTER_COMPLETION_MAX_TOKENS
    return {
        "model": settings.OPENROUTER_MODEL,
        "stream": False,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }


def _extract_assistant_content(response_payload: dict[str, Any]) -> str:
    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise OpenRouterResponseError("OpenRouter response is missing choices")

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise OpenRouterResponseError("OpenRouter response is missing message content")

    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise OpenRouterResponseError("OpenRouter response is missing message content")

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise OpenRouterResponseError("OpenRouter response is missing message content")

    return content


def _is_timeout_reason(reason: object) -> bool:
    """Return whether a URL error reason represents a request timeout."""
    if isinstance(reason, TimeoutError | socket.timeout):
        return True
    if isinstance(reason, str):
        normalized = reason.strip().lower()
        return normalized in {"timed out", "timeout"}
    return False


def request_openrouter_completion(
    customer_message: str,
    known_whatsapp_number: str,
    *,
    phone_confirmation_question_asked: bool = False,
    message_sid: str | None = None,
    collected_fields: dict[str, Any] | None = None,
    conversation_history: list[dict[str, str]] | None = None,
    conversation_language: str = "en",
    urlopen: Callable[..., Any] | None = None,
) -> str:
    """
    Send the existing request to OpenRouter and return only the raw assistant
    content text exactly as received after provider envelope extraction.
    """
    import time

    if urlopen is None:
        urlopen = urllib.request.urlopen

    _validate_configuration()

    history = list(conversation_history or [])
    recent_history = history[-6:]
    history_messages_count = len(history)

    cache_digest = _build_completion_cache_key(
        message_sid=message_sid,
        customer_message=customer_message,
        known_whatsapp_number=known_whatsapp_number,
        phone_confirmation_question_asked=phone_confirmation_question_asked,
    )
    cache = get_qualification_cache_backend()
    if cache_digest is not None:
        cached_content = cache.get(openrouter_cache_key(cache_digest))
        if isinstance(cached_content, str):
            request_openrouter_completion.last_elapsed_ms = 0  # type: ignore[attr-defined]
            step = (
                "openrouter_cache_hit_redis"
                if cache.backend_name == "redis"
                else "openrouter_cache_hit_memory"
            )
            log_latency_step(step, 0, message_sid=message_sid)
            return cached_content

    payload = _build_request_payload(
        customer_message=customer_message,
        known_whatsapp_number=known_whatsapp_number,
        phone_confirmation_question_asked=phone_confirmation_question_asked,
        collected_fields=collected_fields,
        recent_history=recent_history,
        conversation_language=conversation_language,
    )
    encoded_body = json.dumps(payload).encode("utf-8")
    system_prompt_length = len(payload["messages"][0]["content"])
    prompt_length = len(encoded_body)
    max_tokens = payload["max_tokens"]
    log_latency_step(
        "openrouter_prompt_optimized",
        0,
        message_sid=message_sid,
        system_prompt_length=system_prompt_length,
        history_messages_count=history_messages_count,
        recent_history_messages_count=len(recent_history),
        prompt_length=prompt_length,
        max_tokens=max_tokens,
    )

    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "Connection": "keep-alive",
    }
    url = f"{settings.OPENROUTER_BASE_URL}/chat/completions"
    request = urllib.request.Request(url, data=encoded_body, method="POST", headers=headers)

    started = time.perf_counter()
    input_length = len(customer_message)
    model_name = settings.OPENROUTER_MODEL
    try:
        with urlopen(
            request,
            timeout=settings.OPENROUTER_TIMEOUT_SECONDS,
        ) as response:
            if response.status >= 400:
                raise OpenRouterRequestError("OpenRouter request failed")
            raw_body = response.read()
    except urllib.error.HTTPError as exc:
        log_latency_step(
            "openrouter_call",
            elapsed_ms_since(started),
            message_sid=message_sid,
            model=model_name,
            input_length=input_length,
            prompt_length=prompt_length,
            response_length=None,
            status="failure",
            error_type=type(exc).__name__,
        )
        raise OpenRouterRequestError("OpenRouter request failed") from exc
    except urllib.error.URLError as exc:
        if _is_timeout_reason(exc.reason):
            log_latency_step(
                "openrouter_call",
                elapsed_ms_since(started),
                message_sid=message_sid,
                model=model_name,
                input_length=input_length,
                prompt_length=prompt_length,
                response_length=None,
                status="failure",
                error_type="OpenRouterTimeoutError",
            )
            raise OpenRouterTimeoutError("OpenRouter request timed out") from exc
        log_latency_step(
            "openrouter_call",
            elapsed_ms_since(started),
            message_sid=message_sid,
            model=model_name,
            input_length=input_length,
            prompt_length=prompt_length,
            response_length=None,
            status="failure",
            error_type=type(exc).__name__,
        )
        raise OpenRouterRequestError("OpenRouter request failed") from exc
    except TimeoutError as exc:
        log_latency_step(
            "openrouter_call",
            elapsed_ms_since(started),
            message_sid=message_sid,
            model=model_name,
            input_length=input_length,
            prompt_length=prompt_length,
            response_length=None,
            status="failure",
            error_type="OpenRouterTimeoutError",
        )
        raise OpenRouterTimeoutError("OpenRouter request timed out") from exc
    except socket.timeout as exc:
        log_latency_step(
            "openrouter_call",
            elapsed_ms_since(started),
            message_sid=message_sid,
            model=model_name,
            input_length=input_length,
            prompt_length=prompt_length,
            response_length=None,
            status="failure",
            error_type="OpenRouterTimeoutError",
        )
        raise OpenRouterTimeoutError("OpenRouter request timed out") from exc
    finally:
        request_openrouter_completion.last_elapsed_ms = int(  # type: ignore[attr-defined]
            (time.perf_counter() - started) * 1000,
        )

    try:
        response_payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        log_latency_step(
            "openrouter_call",
            elapsed_ms_since(started),
            message_sid=message_sid,
            model=model_name,
            input_length=input_length,
            prompt_length=prompt_length,
            response_length=None,
            status="failure",
            error_type=type(exc).__name__,
        )
        raise OpenRouterResponseError("OpenRouter response is not valid JSON") from exc

    if not isinstance(response_payload, dict):
        log_latency_step(
            "openrouter_call",
            elapsed_ms_since(started),
            message_sid=message_sid,
            model=model_name,
            input_length=input_length,
            prompt_length=prompt_length,
            response_length=None,
            status="failure",
            error_type="OpenRouterResponseError",
        )
        raise OpenRouterResponseError("OpenRouter response is not valid JSON")

    try:
        content = _extract_assistant_content(response_payload)
    except OpenRouterResponseError as exc:
        log_latency_step(
            "openrouter_call",
            elapsed_ms_since(started),
            message_sid=message_sid,
            model=model_name,
            input_length=input_length,
            prompt_length=prompt_length,
            response_length=None,
            status="failure",
            error_type=type(exc).__name__,
        )
        raise

    log_latency_step(
        "openrouter_call",
        elapsed_ms_since(started),
        message_sid=message_sid,
        model=model_name,
        input_length=input_length,
        prompt_length=prompt_length,
        response_length=len(content),
        status="success",
    )
    if cache_digest is not None:
        cache.set(
            openrouter_cache_key(cache_digest),
            content,
            default_cache_ttl_seconds(),
        )
    return content


request_openrouter_completion.last_elapsed_ms = 0
