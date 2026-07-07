"""Add last-menu delivery state to WhatsApp conversation sessions."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("qualification", "0007_whatsappconversationsession_human_handoff_requested_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="whatsappconversationsession",
            name="last_menu_id",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="whatsappconversationsession",
            name="last_menu_sent",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="whatsappconversationsession",
            name="last_menu_timestamp",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
