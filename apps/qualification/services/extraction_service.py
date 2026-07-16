"""Post-provider extraction pipeline for qualification turns."""

from __future__ import annotations

from apps.qualification.extractor import parse_extraction_json
from apps.qualification.filtering import filter_qualification_fields
from apps.qualification.models import QualificationFieldFilterResult
from apps.qualification.phone_confirmation import apply_phone_confirmation_guard


class ExtractionService:
    """Convert raw LLM output into validated, filtered qualification fields."""

    def extract_from_provider_text(
        self,
        provider_text: str,
        *,
        customer_message: str,
        known_whatsapp_number: str,
        phone_confirmation_question_asked: bool = False,
        message_sid: str | None = None,
    ) -> QualificationFieldFilterResult:
        """
        Convert raw LLM output into the existing validated qualification
        extraction result using the existing domain modules.
        """
        extraction = parse_extraction_json(
            provider_text,
            message_sid=message_sid,
        )
        guarded_extraction = apply_phone_confirmation_guard(
            extraction,
            customer_message,
            known_whatsapp_number,
            phone_confirmation_question_asked=phone_confirmation_question_asked,
        )
        return filter_qualification_fields(guarded_extraction)
