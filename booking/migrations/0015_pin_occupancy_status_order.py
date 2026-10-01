# Generated manually for Phase 6.0.1 — pin exclusion-constraint status list order.
# Database semantics are unchanged (same status set). Only Django migration state is
# updated so `makemigrations --check` is stable. No DROP/CREATE on the live constraint.

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators
from django.db import migrations, models

import booking.models


class Migration(migrations.Migration):

    dependencies = [
        ("booking", "0014_phase6_payments"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="appointment",
                    name="excl_appointment_staff_occupancy",
                ),
                migrations.AddConstraint(
                    model_name="appointment",
                    constraint=ExclusionConstraint(
                        condition=models.Q(
                            ("deleted_at__isnull", True),
                            (
                                "status__in",
                                ["CHECKED_IN", "CONFIRMED", "PENDING"],
                            ),
                        ),
                        expressions=[
                            ("staff_profile", RangeOperators.EQUAL),
                            (
                                booking.models.TsTzRange(
                                    "occupancy_starts_at", "occupancy_ends_at"
                                ),
                                RangeOperators.OVERLAPS,
                            ),
                        ],
                        name="excl_appointment_staff_occupancy",
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
