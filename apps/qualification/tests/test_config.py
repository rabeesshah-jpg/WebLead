"""Tests for shared qualification configuration."""

from __future__ import annotations

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from apps.qualification.config import get_qualification_confidence_threshold


def test_default_threshold_is_075():
    assert settings.QUALIFICATION_CONFIDENCE_THRESHOLD == 0.75
    assert get_qualification_confidence_threshold() == 0.75


@override_settings(QUALIFICATION_CONFIDENCE_THRESHOLD=0.9)
def test_valid_overridden_value_can_be_read():
    assert get_qualification_confidence_threshold() == 0.9


@pytest.mark.parametrize(
    "invalid_value",
    [0, -0.1, 1.1, 2.0, "not-a-number"],
)
def test_invalid_values_outside_open_closed_range_are_rejected(invalid_value):
    with override_settings(QUALIFICATION_CONFIDENCE_THRESHOLD=invalid_value):
        with pytest.raises(ImproperlyConfigured):
            get_qualification_confidence_threshold()
