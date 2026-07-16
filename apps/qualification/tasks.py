"""Celery tasks for qualification (existing-customer sync handoff; Celery retired for that path)."""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger("apps.qualification")


@shared_task(
    bind=True,
    name="qualification.deliver_existing_customer_handoff",
    max_retries=0,
)
def deliver_existing_customer_handoff_task(
    self,
    *,
    whatsapp_number: str,
    idempotency_key: str = "",
    expected_state: str = "",
    conversation_language: str | None = None,
) -> bool:
    """
    Retired: existing-customer connecting + Noura follow-up run inline via
    ``time.sleep(5)`` in the extract turn. Kept registered so old queued
    messages no-op safely.
    """
    del self, expected_state, conversation_language
    logger.info(
        "existing_customer_handoff_task_retired whatsapp_number_prefix=%s "
        "idempotency_key=%s",
        (whatsapp_number or "")[:6],
        idempotency_key or None,
    )
    return False
