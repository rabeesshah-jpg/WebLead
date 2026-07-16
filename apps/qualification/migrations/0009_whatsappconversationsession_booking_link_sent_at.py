from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("qualification", "0008_whatsappconversationsession_last_menu_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="whatsappconversationsession",
            name="booking_link_sent_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
