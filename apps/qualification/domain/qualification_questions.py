"""Natural qualification question wording with lightweight repeat variations."""

from __future__ import annotations

from apps.qualification.conversation_state import get_recent_conversation_history
from apps.qualification.domain.messages import get_customer_message

_PROJECT_TYPE_REPEAT_KEYS: tuple[str, ...] = (
    "project_type_variant_2",
    "project_type_variant_1",
    "project_type_variant_3",
)


def get_qualification_question_text(
    *,
    language: str,
    field: str,
    repeat: bool = False,
    whatsapp_number: str | None = None,
) -> str:
    """Return qualification question copy, using natural variants when re-asking."""
    if field == "project_type" and repeat:
        history_len = 0
        if whatsapp_number:
            history_len = len(get_recent_conversation_history(whatsapp_number))
        variant_key = _PROJECT_TYPE_REPEAT_KEYS[history_len % len(_PROJECT_TYPE_REPEAT_KEYS)]
        return get_customer_message(language=language, key=variant_key)
    return get_customer_message(language=language, key=field)
