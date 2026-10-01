import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("booking", "0010_appointment_schedule_version"),
        ("businesses", "0001_initial"),
        ("messaging", "0002_whatsapp_transactional_automation"),
        ("organizations", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="whatsappmessage",
            name="delivery_attempts",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name="messagetemplate",
            name="purpose",
            field=models.CharField(
                blank=True,
                choices=[
                    ("BOOKING_CONFIRMATION", "Booking confirmation"),
                    ("BOOKING_CONFIRMED", "Booking confirmed"),
                    ("BOOKING_RESCHEDULED", "Booking rescheduled"),
                    ("BOOKING_CANCELLED", "Booking cancelled"),
                    ("REVIEW_REQUEST", "Review request"),
                    ("APPOINTMENT_REMINDER", "Appointment reminder"),
                ],
                default="",
                max_length=32,
            ),
        ),
        migrations.CreateModel(
            name="AppointmentReminder",
            fields=[
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True),
                ),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "notification_type",
                    models.CharField(
                        choices=[("APPOINTMENT_REMINDER_24H", "24-hour reminder")],
                        default="APPOINTMENT_REMINDER_24H",
                        max_length=64,
                    ),
                ),
                ("schedule_version", models.PositiveIntegerField(default=1)),
                ("scheduled_for", models.DateTimeField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("QUEUED", "Queued"),
                            ("SENT", "Sent"),
                            ("CANCELLED", "Cancelled"),
                            ("FAILED", "Failed"),
                            ("SKIPPED", "Skipped"),
                        ],
                        default="PENDING",
                        max_length=16,
                    ),
                ),
                ("idempotency_key", models.CharField(max_length=255)),
                ("attempt_count", models.PositiveSmallIntegerField(default=0)),
                ("last_error_code", models.CharField(blank=True, default="", max_length=64)),
                ("last_error_message", models.CharField(blank=True, default="", max_length=500)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                (
                    "appointment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="whatsapp_reminders",
                        to="booking.appointment",
                    ),
                ),
                (
                    "business",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="appointment_reminders",
                        to="businesses.business",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="appointment_reminders",
                        to="organizations.organization",
                    ),
                ),
                (
                    "whatsapp_message",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reminders",
                        to="messaging.whatsappmessage",
                    ),
                ),
            ],
            options={
                "ordering": ["scheduled_for"],
            },
        ),
        migrations.AddIndex(
            model_name="appointmentreminder",
            index=models.Index(fields=["status", "scheduled_for"], name="messaging_a_status_8ce409_idx"),
        ),
        migrations.AddIndex(
            model_name="appointmentreminder",
            index=models.Index(
                fields=["organization", "business", "status"],
                name="messaging_a_organiz_3998fc_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="appointmentreminder",
            index=models.Index(
                fields=["appointment", "status"],
                name="messaging_a_appoint_9d1a9e_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="appointmentreminder",
            constraint=models.UniqueConstraint(
                fields=("appointment", "notification_type", "schedule_version"),
                name="unique_appointment_reminder_version",
            ),
        ),
        migrations.AddConstraint(
            model_name="appointmentreminder",
            constraint=models.UniqueConstraint(
                fields=("idempotency_key",),
                name="unique_appointment_reminder_idempotency",
            ),
        ),
    ]
