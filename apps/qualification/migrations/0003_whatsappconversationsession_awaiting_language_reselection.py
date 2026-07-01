from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("qualification", "0002_backfill_conversation_language_en"),
    ]

    operations = [
        migrations.AddField(
            model_name="whatsappconversationsession",
            name="awaiting_language_reselection",
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
