# Generated manually for Phase 3.4.2

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("businesses", "0005_google_oauth_credentials"),
    ]

    operations = [
        migrations.AddField(
            model_name="googlebusinessconnection",
            name="google_business_account_name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="googlebusinessconnection",
            name="google_location_display_name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
