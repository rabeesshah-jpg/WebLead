from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("qualification", "0011_whatsappconversationsession_last_onboarding_intro_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="whatsappconversationsession",
            name="qualified_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
