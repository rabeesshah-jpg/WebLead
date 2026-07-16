# Generated manually for Arabic language foundation.

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies: list[tuple[str, str]] = []

    operations = [
        migrations.CreateModel(
            name="WhatsAppConversationSession",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("whatsapp_number", models.CharField(db_index=True, max_length=32, unique=True)),
                (
                    "language",
                    models.CharField(
                        blank=True,
                        choices=[("en", "English"), ("ar", "Arabic")],
                        db_index=True,
                        max_length=5,
                        null=True,
                    ),
                ),
                ("language_selected_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "verbose_name": "WhatsApp conversation session",
                "verbose_name_plural": "WhatsApp conversation sessions",
                "db_table": "qualification_whatsapp_conversation_session",
            },
        ),
    ]
