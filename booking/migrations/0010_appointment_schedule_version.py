from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("booking", "0009_booking_plan_mvp"),
    ]

    operations = [
        migrations.AddField(
            model_name="appointment",
            name="schedule_version",
            field=models.PositiveIntegerField(
                default=1,
                help_text="Increments on reschedule so older reminders cannot send.",
            ),
        ),
    ]
