from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("qualification", "0010_whatsappconversationsession_onboarding_intro_sent"),
    ]

    operations = [
        migrations.AddField(
            model_name="whatsappconversationsession",
            name="last_onboarding_intro_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
