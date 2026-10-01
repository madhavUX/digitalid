from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("booking", "0010_appointment_schedule_version"),
    ]

    operations = [
        migrations.AddField(
            model_name="appointment",
            name="acquisition_source",
            field=models.CharField(
                blank=True,
                help_text="How the guest arrived, such as QUICKCARD. Null for direct bookings.",
                max_length=32,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="appointment",
            name="acquisition_reference",
            field=models.UUIDField(
                blank=True,
                help_text="QuickCard id when acquisition_source is QUICKCARD. Not a cascading foreign key.",
                null=True,
            ),
        ),
        migrations.AddIndex(
            model_name="appointment",
            index=models.Index(
                condition=models.Q(acquisition_source="QUICKCARD"),
                fields=["acquisition_source", "created_at"],
                name="appt_qc_acq_created_idx",
            ),
        ),
    ]
