# Generated manually for Arabic language foundation.

from __future__ import annotations

from django.db import migrations


def backfill_language_en(apps, schema_editor) -> None:
    session_model = apps.get_model("qualification", "WhatsAppConversationSession")
    session_model.objects.filter(language__isnull=True).update(language="en")


def reverse_backfill_language_en(apps, schema_editor) -> None:
    """Revert auto-backfilled English defaults only.

    Rows with language_selected_at set are left unchanged so explicit user
    choices are not cleared on reverse.
    """
    session_model = apps.get_model("qualification", "WhatsAppConversationSession")
    session_model.objects.filter(
        language="en",
        language_selected_at__isnull=True,
    ).update(language=None)


class Migration(migrations.Migration):
    dependencies = [
        ("qualification", "0001_initial_whatsapp_conversation_session"),
    ]

    operations = [
        migrations.RunPython(backfill_language_en, reverse_backfill_language_en),
    ]
