"""Add human handoff timestamp to WhatsApp conversation sessions."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("qualification", "0006_whatsappconversationsession_inactivity_menu_pending"),
    ]

    operations = [
        migrations.AddField(
            model_name="whatsappconversationsession",
            name="human_handoff_requested_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
