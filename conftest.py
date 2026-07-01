"""Pytest configuration."""

import os
from unittest.mock import patch

import pytest

from config.sqlite_compat import enable_pysqlite3_fallback

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings_test")
enable_pysqlite3_fallback()


@pytest.fixture(autouse=True)
def _disable_language_gate_unless_marked(request):
    """Keep existing qualification tests on the English path unless explicitly testing the gate."""
    if request.node.get_closest_marker("language_gate") is not None:
        yield
        return

    from apps.qualification.services.language_gate_service import LanguageGateResult, LanguageGateService

    with (
        patch.object(
            LanguageGateService,
            "evaluate_turn",
            return_value=LanguageGateResult(handled=False),
        ),
        patch(
            "apps.qualification.services.extract_service.get_conversation_language",
            return_value="en",
        ),
        patch(
            "apps.qualification.qualification_turn.get_conversation_language",
            return_value="en",
        ),
    ):
        yield
