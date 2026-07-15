from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("qualification", "0012_whatsappconversationsession_qualified_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="whatsappconversationsession",
            name="existing_customer_connecting_sent_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="whatsappconversationsession",
            name="existing_customer_followup_due_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="whatsappconversationsession",
            name="existing_customer_followup_sent_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
