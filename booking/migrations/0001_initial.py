import booking.models
import django.contrib.postgres.constraints
import django.core.validators
import django.db.models.deletion
import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.operations import CreateExtension
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("businesses", "0001_initial"),
        ("catalog", "0001_initial"),
        ("customers", "0001_initial"),
        ("locations", "0001_initial"),
        ("organizations", "0002_remove_super_admin_role"),
        ("staff", "0002_staff_availability_time_off"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        CreateExtension("btree_gist"),
        migrations.CreateModel(
            name="Appointment",
            fields=[
                ("deleted_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("starts_at", models.DateTimeField(help_text="Customer-visible start (UTC).")),
                ("ends_at", models.DateTimeField(help_text="Customer-visible end (UTC).")),
                (
                    "occupancy_starts_at",
                    models.DateTimeField(
                        help_text="Staff occupancy start including buffer_before (UTC)."
                    ),
                ),
                (
                    "occupancy_ends_at",
                    models.DateTimeField(
                        help_text="Staff occupancy end including buffer_after (UTC)."
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("CONFIRMED", "Confirmed"),
                            ("CHECKED_IN", "Checked in"),
                            ("COMPLETED", "Completed"),
                            ("CANCELLED", "Cancelled"),
                            ("NO_SHOW", "No show"),
                        ],
                        default="CONFIRMED",
                        max_length=32,
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("ONLINE", "Online"),
                            ("WHATSAPP", "WhatsApp"),
                            ("PHONE", "Phone"),
                            ("WALK_IN", "Walk-in"),
                            ("DASHBOARD", "Dashboard"),
                        ],
                        default="DASHBOARD",
                        max_length=32,
                    ),
                ),
                (
                    "total_price",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=10,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                ("currency", models.CharField(default="INR", max_length=3)),
                (
                    "deposit_amount",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.00"),
                        max_digits=10,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                ("deposit_paid", models.BooleanField(default=False)),
                ("notes", models.TextField(blank=True)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                ("cancellation_reason", models.CharField(blank=True, max_length=255)),
                (
                    "public_reference",
                    models.CharField(
                        default=booking.models.generate_public_reference,
                        editable=False,
                        max_length=32,
                        unique=True,
                    ),
                ),
                (
                    "business",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="appointments",
                        to="businesses.business",
                    ),
                ),
                (
                    "cancelled_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="cancelled_appointments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)s_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "customer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="appointments",
                        to="customers.customer",
                    ),
                ),
                (
                    "deleted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)s_deletions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "location",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="appointments",
                        to="locations.location",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="appointments",
                        to="organizations.organization",
                    ),
                ),
                (
                    "staff_profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="appointments",
                        to="staff.staffprofile",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)s_updated",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["starts_at"],
            },
        ),
        migrations.CreateModel(
            name="AppointmentItem",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("service_name", models.CharField(max_length=255)),
                (
                    "duration_minutes",
                    models.PositiveIntegerField(
                        validators=[django.core.validators.MinValueValidator(1)]
                    ),
                ),
                ("buffer_before_minutes", models.PositiveIntegerField(default=0)),
                ("buffer_after_minutes", models.PositiveIntegerField(default=0)),
                (
                    "price",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=10,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                ("currency", models.CharField(default="INR", max_length=3)),
                (
                    "appointment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="booking.appointment",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)s_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "service",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="appointment_items",
                        to="catalog.service",
                    ),
                ),
                (
                    "staff_profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="appointment_items",
                        to="staff.staffprofile",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)s_updated",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="appointment",
            index=models.Index(
                fields=["organization", "starts_at"], name="booking_app_organiz_14290f_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="appointment",
            index=models.Index(
                fields=["location", "starts_at", "status"], name="booking_app_locatio_70f91e_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="appointment",
            index=models.Index(
                fields=["staff_profile", "starts_at", "status"],
                name="booking_app_staff_p_f15929_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="appointment",
            index=models.Index(
                fields=["customer", "starts_at"], name="booking_app_custome_8cf943_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="appointment",
            index=models.Index(
                fields=["status", "starts_at"], name="booking_app_status_40b6e6_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="appointment",
            index=models.Index(
                fields=["staff_profile", "occupancy_starts_at", "occupancy_ends_at"],
                name="booking_app_staff_p_767110_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="appointment",
            constraint=models.CheckConstraint(
                condition=models.Q(("ends_at__gt", models.F("starts_at"))),
                name="appointment_ends_after_starts",
            ),
        ),
        migrations.AddConstraint(
            model_name="appointment",
            constraint=models.CheckConstraint(
                condition=models.Q(("occupancy_ends_at__gt", models.F("occupancy_starts_at"))),
                name="appointment_occupancy_ends_after_starts",
            ),
        ),
        migrations.AddConstraint(
            model_name="appointment",
            constraint=django.contrib.postgres.constraints.ExclusionConstraint(
                condition=models.Q(
                    ("deleted_at__isnull", True),
                    ("status__in", ["CONFIRMED", "PENDING", "CHECKED_IN"]),
                ),
                expressions=[
                    ("staff_profile", "="),
                    (
                        booking.models.TsTzRange("occupancy_starts_at", "occupancy_ends_at"),
                        "&&",
                    ),
                ],
                name="excl_appointment_staff_occupancy",
            ),
        ),
        migrations.AddIndex(
            model_name="appointmentitem",
            index=models.Index(fields=["appointment"], name="booking_app_appoint_092f65_idx"),
        ),
        migrations.AddIndex(
            model_name="appointmentitem",
            index=models.Index(fields=["service"], name="booking_app_service_315b49_idx"),
        ),
    ]
