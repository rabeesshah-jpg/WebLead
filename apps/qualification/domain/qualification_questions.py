"""Natural qualification question wording with lightweight repeat variations."""

from __future__ import annotations

from apps.qualification.domain.messages import get_customer_message
from apps.qualification.domain.numbered_qualification import (
    format_numbered_question,
    is_numbered_qualification_field,
)


def get_qualification_question_text(
    *,
    language: str,
    field: str,
    repeat: bool = False,
    whatsapp_number: str | None = None,
) -> str:
    """Return qualification question copy for the active field."""
    del repeat, whatsapp_number  # Numbered questions always use the same full prompt.
    if is_numbered_qualification_field(field):
        return format_numbered_question(field=field, language=language)
    return get_customer_message(language=language, key=field)
