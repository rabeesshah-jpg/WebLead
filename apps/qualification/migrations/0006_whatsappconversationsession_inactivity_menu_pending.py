"""Add session activity tracking and explicit menu-pending flag."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("qualification", "0005_whatsappconversationsession_menu_pending_until"),
    ]

    operations = [
        migrations.AddField(
            model_name="whatsappconversationsession",
            name="last_message_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="whatsappconversationsession",
            name="menu_pending",
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
