"""Shared qualification configuration helpers."""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

_THRESHOLD_ERROR_MESSAGE = (
    "QUALIFICATION_CONFIDENCE_THRESHOLD must be a float greater than 0 "
    "and less than or equal to 1."
)


def _validate_qualification_confidence_threshold(value: object) -> float:
    try:
        threshold = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(_THRESHOLD_ERROR_MESSAGE) from exc
    if not 0 < threshold <= 1:
        raise ImproperlyConfigured(_THRESHOLD_ERROR_MESSAGE)
    return threshold


def get_qualification_confidence_threshold() -> float:
    """Return the shared minimum confidence threshold for qualification fields."""
    return _validate_qualification_confidence_threshold(
        settings.QUALIFICATION_CONFIDENCE_THRESHOLD
    )
