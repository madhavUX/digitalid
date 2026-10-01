import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("businesses", "0001_initial"),
        ("customers", "0001_initial"),
        ("messaging", "0003_appointment_reminder"),
        ("organizations", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="messagetemplate",
            name="provider_status",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Meta status from sync or submission. Local status is not Meta approval.",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="appointmentreminder",
            name="notification_type",
            field=models.CharField(
                choices=[
                    ("APPOINTMENT_REMINDER_24H", "24-hour reminder"),
                    ("APPOINTMENT_REMINDER_1H", "1-hour reminder"),
                    ("REVIEW_REQUEST", "Review request"),
                ],
                default="APPOINTMENT_REMINDER_24H",
                max_length=64,
            ),
        ),
        migrations.CreateModel(
            name="WhatsAppInboundMessage",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("provider_message_id", models.CharField(max_length=128)),
                ("phone_number", models.CharField(max_length=20)),
                ("message_type", models.CharField(max_length=32)),
                ("text", models.CharField(blank=True, default="", max_length=1000)),
                ("provider_timestamp", models.DateTimeField(blank=True, null=True)),
                (
                    "processing_status",
                    models.CharField(
                        choices=[("RECEIVED", "Received"), ("IGNORED", "Ignored")],
                        default="RECEIVED",
                        max_length=16,
                    ),
                ),
                (
                    "business",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="whatsapp_inbound_messages",
                        to="businesses.business",
                    ),
                ),
                (
                    "customer",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="whatsapp_inbound_messages",
                        to="customers.customer",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="whatsapp_inbound_messages",
                        to="organizations.organization",
                    ),
                ),
                (
                    "whatsapp_account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="inbound_messages",
                        to="messaging.whatsappaccount",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="whatsappinboundmessage",
            index=models.Index(
                fields=["organization", "business", "created_at"],
                name="messaging_w_organiz_365105_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="whatsappinboundmessage",
            index=models.Index(
                fields=["business", "phone_number"],
                name="messaging_w_busines_a87469_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="whatsappinboundmessage",
            constraint=models.UniqueConstraint(
                fields=("provider_message_id",),
                name="unique_whatsapp_inbound_provider_message",
            ),
        ),
    ]
