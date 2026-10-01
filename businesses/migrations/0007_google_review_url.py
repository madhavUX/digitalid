from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("businesses", "0006_google_location_selection_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="businesslaunchprofile",
            name="google_review_url",
            field=models.URLField(blank=True, default="", max_length=500),
        ),
    ]
