from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("qualification", "0013_whatsappconversationsession_existing_customer_followup"),
    ]

    operations = [
        migrations.AddField(
            model_name="whatsappconversationsession",
            name="existing_customer_noura_sent_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
