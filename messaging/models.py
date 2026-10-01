import uuid

from django.db import models
from django.db.models import Q

from core.models import AuditedModel, SoftDeleteModel, TimestampedModel


class WhatsAppConnectionStatus(models.TextChoices):
    CONNECTED = "CONNECTED", "Connected"
    DISCONNECTED = "DISCONNECTED", "Disconnected"
    REAUTH_REQUIRED = "REAUTH_REQUIRED", "Reauthorization required"
    ERROR = "ERROR", "Error"


class WhatsAppTemplateCategory(models.TextChoices):
    CONFIRMATION = "CONFIRMATION", "Confirmation"
    REMINDER = "REMINDER", "Reminder"
    REVIEW_REQUEST = "REVIEW_REQUEST", "Review request"
    WIN_BACK = "WIN_BACK", "Win back"
    RETENTION = "RETENTION", "Retention"
    CUSTOM = "CUSTOM", "Custom"


class WhatsAppTemplatePurpose(models.TextChoices):
    BOOKING_CONFIRMATION = "BOOKING_CONFIRMATION", "Booking confirmation"
    BOOKING_CONFIRMED = "BOOKING_CONFIRMED", "Booking confirmed"
    BOOKING_RESCHEDULED = "BOOKING_RESCHEDULED", "Booking rescheduled"
    BOOKING_CANCELLED = "BOOKING_CANCELLED", "Booking cancelled"
    REVIEW_REQUEST = "REVIEW_REQUEST", "Review request"
    APPOINTMENT_REMINDER = "APPOINTMENT_REMINDER", "Appointment reminder"
    RETENTION_DUE_RETURN = "RETENTION_DUE_RETURN", "Retention due for return"


class WhatsAppTemplateStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    DISABLED = "DISABLED", "Disabled"


class WhatsAppMessageType(models.TextChoices):
    TEXT = "TEXT", "Text"
    TEMPLATE = "TEMPLATE", "Template"


class WhatsAppMessageStatus(models.TextChoices):
    QUEUED = "QUEUED", "Queued"
    SENT = "SENT", "Sent"
    DELIVERED = "DELIVERED", "Delivered"
    READ = "READ", "Read"
    FAILED = "FAILED", "Failed"
    CANCELLED = "CANCELLED", "Cancelled"


class WhatsAppAccount(SoftDeleteModel, AuditedModel, TimestampedModel):
    """Business-owned WhatsApp Business connection. Tokens stay encrypted."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="whatsapp_accounts",
    )
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.PROTECT,
        related_name="whatsapp_accounts",
    )
    phone_number_id = models.CharField(max_length=64, blank=True, default="")
    business_account_id = models.CharField(max_length=64, blank=True, default="")
    display_phone_number = models.CharField(max_length=20, blank=True, default="")
    verified_name = models.CharField(max_length=255, blank=True, default="")
    access_token_encrypted = models.TextField(blank=True, default="")
    token_expires_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=32,
        choices=WhatsAppConnectionStatus.choices,
        default=WhatsAppConnectionStatus.DISCONNECTED,
    )
    last_error_code = models.CharField(max_length=64, blank=True, default="")
    last_error_message = models.CharField(max_length=500, blank=True, default="")
    connected_at = models.DateTimeField(null=True, blank=True)
    disconnected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["organization", "business"]),
            models.Index(fields=["status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["business"],
                condition=Q(deleted_at__isnull=True),
                name="unique_whatsapp_account_business_alive",
            ),
        ]

    def __str__(self) -> str:
        return f"WhatsAppAccount({self.business_id}, {self.status})"

    def __repr__(self) -> str:
        return f"<WhatsAppAccount id={self.id} business_id={self.business_id} status={self.status}>"


class MessageTemplate(SoftDeleteModel, AuditedModel, TimestampedModel):
    """Business-scoped WhatsApp template definition. Not an approved Meta object by itself."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="whatsapp_message_templates",
    )
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.PROTECT,
        related_name="whatsapp_message_templates",
    )
    name = models.CharField(max_length=128)
    purpose = models.CharField(
        max_length=32,
        choices=WhatsAppTemplatePurpose.choices,
        blank=True,
        default="",
    )
    language = models.CharField(max_length=16, default="en")
    category = models.CharField(
        max_length=32,
        choices=WhatsAppTemplateCategory.choices,
        default=WhatsAppTemplateCategory.CUSTOM,
    )
    provider_template_id = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(
        max_length=32,
        choices=WhatsAppTemplateStatus.choices,
        default=WhatsAppTemplateStatus.DRAFT,
    )
    provider_status = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="Meta status from sync or submission. Local status is not Meta approval.",
    )
    body = models.TextField(blank=True, default="")
    variables = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name", "language"]
        indexes = [
            models.Index(fields=["organization", "business"]),
            models.Index(fields=["business", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "name", "language"],
                condition=Q(deleted_at__isnull=True),
                name="unique_whatsapp_template_business_name_language_alive",
            ),
            models.UniqueConstraint(
                fields=["business", "purpose", "language"],
                condition=Q(deleted_at__isnull=True) & ~Q(purpose=""),
                name="unique_whatsapp_template_business_purpose_language_alive",
            ),
        ]

    def __str__(self) -> str:
        return f"MessageTemplate({self.business_id}, {self.name}, {self.language})"


class WhatsAppMessage(AuditedModel, TimestampedModel):
    """Outbound WhatsApp log. Preserved (not soft-deleted)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="whatsapp_messages",
    )
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.PROTECT,
        related_name="whatsapp_messages",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="whatsapp_messages",
    )
    appointment = models.ForeignKey(
        "booking.Appointment",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="whatsapp_messages",
    )
    phone_number = models.CharField(max_length=20)
    purpose = models.CharField(max_length=32, blank=True, default="")
    message_type = models.CharField(
        max_length=16,
        choices=WhatsAppMessageType.choices,
        default=WhatsAppMessageType.TEMPLATE,
    )
    template_name = models.CharField(max_length=128, blank=True, default="")
    template_language = models.CharField(max_length=16, blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    provider_message_id = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=WhatsAppMessageStatus.choices,
        default=WhatsAppMessageStatus.QUEUED,
    )
    failure_code = models.CharField(max_length=64, blank=True, default="")
    failure_message = models.CharField(max_length=500, blank=True, default="")
    idempotency_key = models.CharField(max_length=255, blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    delivery_attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "created_at"]),
            models.Index(fields=["business", "created_at"]),
            models.Index(fields=["customer", "created_at"]),
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["business", "purpose"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["provider_message_id"],
                condition=~Q(provider_message_id=""),
                name="unique_whatsapp_message_provider_id",
            ),
            models.UniqueConstraint(
                fields=["business", "idempotency_key"],
                condition=~Q(idempotency_key=""),
                name="unique_whatsapp_message_business_idempotency",
            ),
        ]

    def __str__(self) -> str:
        return f"WhatsAppMessage({self.id}, {self.status})"


class AppointmentReminderStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    QUEUED = "QUEUED", "Queued"
    SENT = "SENT", "Sent"
    CANCELLED = "CANCELLED", "Cancelled"
    FAILED = "FAILED", "Failed"
    SKIPPED = "SKIPPED", "Skipped"


class AppointmentReminderType(models.TextChoices):
    APPOINTMENT_REMINDER_24H = "APPOINTMENT_REMINDER_24H", "24-hour reminder"
    APPOINTMENT_REMINDER_1H = "APPOINTMENT_REMINDER_1H", "1-hour reminder"
    REVIEW_REQUEST = "REVIEW_REQUEST", "Review request"


class AppointmentReminder(TimestampedModel):
    """Durable schedule for one appointment reminder. Not a copy of the appointment."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="appointment_reminders",
    )
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.PROTECT,
        related_name="appointment_reminders",
    )
    appointment = models.ForeignKey(
        "booking.Appointment",
        on_delete=models.PROTECT,
        related_name="whatsapp_reminders",
    )
    whatsapp_message = models.ForeignKey(
        WhatsAppMessage,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reminders",
    )
    notification_type = models.CharField(
        max_length=64,
        choices=AppointmentReminderType.choices,
        default=AppointmentReminderType.APPOINTMENT_REMINDER_24H,
    )
    schedule_version = models.PositiveIntegerField(default=1)
    scheduled_for = models.DateTimeField()
    status = models.CharField(
        max_length=16,
        choices=AppointmentReminderStatus.choices,
        default=AppointmentReminderStatus.PENDING,
    )
    idempotency_key = models.CharField(max_length=255)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    last_error_code = models.CharField(max_length=64, blank=True, default="")
    last_error_message = models.CharField(max_length=500, blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["scheduled_for"]
        indexes = [
            models.Index(fields=["status", "scheduled_for"]),
            models.Index(fields=["organization", "business", "status"]),
            models.Index(fields=["appointment", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["appointment", "notification_type", "schedule_version"],
                name="unique_appointment_reminder_version",
            ),
            models.UniqueConstraint(
                fields=["idempotency_key"],
                name="unique_appointment_reminder_idempotency",
            ),
        ]

    def __str__(self) -> str:
        return f"AppointmentReminder({self.notification_type}, {self.status})"


class WhatsAppInboundProcessingStatus(models.TextChoices):
    RECEIVED = "RECEIVED", "Received"
    IGNORED = "IGNORED", "Ignored"


class WhatsAppInboundMessage(TimestampedModel):
    """Inbound WhatsApp text stored for a business. No replies and no tokens."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="whatsapp_inbound_messages",
    )
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.PROTECT,
        related_name="whatsapp_inbound_messages",
    )
    whatsapp_account = models.ForeignKey(
        WhatsAppAccount,
        on_delete=models.PROTECT,
        related_name="inbound_messages",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="whatsapp_inbound_messages",
    )
    provider_message_id = models.CharField(max_length=128)
    phone_number = models.CharField(max_length=20)
    message_type = models.CharField(max_length=32)
    text = models.CharField(max_length=1000, blank=True, default="")
    provider_timestamp = models.DateTimeField(null=True, blank=True)
    processing_status = models.CharField(
        max_length=16,
        choices=WhatsAppInboundProcessingStatus.choices,
        default=WhatsAppInboundProcessingStatus.RECEIVED,
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider_message_id"],
                name="unique_whatsapp_inbound_provider_message",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "business", "created_at"]),
            models.Index(fields=["business", "phone_number"]),
        ]

    def __str__(self) -> str:
        return f"WhatsAppInboundMessage({self.provider_message_id})"
