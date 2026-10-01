# Generated manually for Phase 5.5 retention booking attribution.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("booking", "0012_appointment_completed_at"),
    ]

    operations = [
        migrations.AlterField(
            model_name="appointment",
            name="acquisition_source",
            field=models.CharField(
                blank=True,
                help_text="How the guest arrived: QUICKCARD or RETENTION. Null for direct bookings.",
                max_length=32,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="appointment",
            name="acquisition_reference",
            field=models.UUIDField(
                blank=True,
                help_text=(
                    "QuickCard id when QUICKCARD; CustomerRetentionMessage id when RETENTION. "
                    "Not a cascading foreign key."
                ),
                null=True,
            ),
        ),
        migrations.AddIndex(
            model_name="appointment",
            index=models.Index(
                condition=models.Q(("acquisition_source", "RETENTION")),
                fields=["acquisition_source", "created_at"],
                name="appt_ret_acq_created_idx",
            ),
        ),
    ]
