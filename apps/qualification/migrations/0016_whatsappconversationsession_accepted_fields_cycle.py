# Generated manually for durable accepted_fields + conversation_cycle.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("qualification", "0015_whatsappconversationsession_business_type_picker_sent"),
    ]

    operations = [
        migrations.AddField(
            model_name="whatsappconversationsession",
            name="accepted_fields",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="whatsappconversationsession",
            name="conversation_cycle",
            field=models.PositiveIntegerField(db_index=True, default=1),
        ),
    ]
