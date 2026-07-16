"""Repair helpers for malformed LLM extraction JSON."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_PATTERN = re.compile(
    r"^```(?:json)?\s*\n?(.*?)\n?```\s*$",
    flags=re.DOTALL | re.IGNORECASE,
)


def strip_markdown_code_fences(text: str) -> str:
    """Remove optional markdown ``` / ```json fences around model output."""
    stripped = text.strip()
    match = _FENCE_PATTERN.match(stripped)
    if match:
        return match.group(1).strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def extract_first_json_object(text: str) -> str | None:
    """Return the first balanced JSON object substring, if one exists."""
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            parsed, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        if isinstance(parsed, dict):
            return text[start:end]
        start = text.find("{", start + 1)
    return None


def build_llm_json_parse_candidates(raw_text: str) -> list[str]:
    """Build ordered parse candidates from raw provider text."""
    candidates: list[str] = []
    seen: set[str] = set()

    def _add(candidate: str) -> None:
        normalized = candidate.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)

    _add(raw_text)
    stripped = strip_markdown_code_fences(raw_text)
    _add(stripped)
    extracted = extract_first_json_object(stripped)
    if extracted:
        _add(extracted)
    if stripped != raw_text.strip():
        extracted_from_raw = extract_first_json_object(raw_text.strip())
        if extracted_from_raw:
            _add(extracted_from_raw)
    return candidates


def safe_raw_response_prefix(raw_text: str, *, limit: int = 160) -> str:
    """Return a short, log-safe prefix of raw provider text."""
    compact = " ".join(raw_text.split())
    return compact[:limit]
