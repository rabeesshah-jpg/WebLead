"""Add short-lived menu pending state to WhatsApp conversation sessions."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("qualification", "0004_whatsappconversationsession_language_picker_pending_until"),
    ]

    operations = [
        migrations.AddField(
            model_name="whatsappconversationsession",
            name="menu_pending_until",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
