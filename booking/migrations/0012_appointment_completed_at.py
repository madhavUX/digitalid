from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("booking", "0011_appointment_quickcard_attribution"),
    ]

    operations = [
        migrations.AddField(
            model_name="appointment",
            name="completed_at",
            field=models.DateTimeField(
                blank=True,
                help_text="UTC time the appointment first transitioned to COMPLETED.",
                null=True,
            ),
        ),
    ]
