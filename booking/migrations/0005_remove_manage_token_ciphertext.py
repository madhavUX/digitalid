from django.db import migrations


class Migration(migrations.Migration):
    """Remove short-lived token_ciphertext experiment (never used in production)."""

    dependencies = [
        ("booking", "0004_notification_delivery_whatsapp"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE booking_appointmentmanagetoken "
                        "DROP COLUMN IF EXISTS token_ciphertext;"
                    ),
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
