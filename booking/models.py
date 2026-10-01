import secrets
import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Func, Q

from core.models import AuditedModel, SoftDeleteModel, TimestampedModel


class AppointmentStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    CONFIRMED = "CONFIRMED", "Confirmed"
    CHECKED_IN = "CHECKED_IN", "Checked in"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"
    NO_SHOW = "NO_SHOW", "No show"


OCCUPYING_STATUSES = frozenset(
    {
        AppointmentStatus.PENDING,
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.CHECKED_IN,
    }
)

ALLOWED_STATUS_TRANSITIONS = {
    AppointmentStatus.PENDING: {
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.CANCELLED,
    },
    AppointmentStatus.CONFIRMED: {
        AppointmentStatus.CHECKED_IN,
        AppointmentStatus.COMPLETED,
        AppointmentStatus.CANCELLED,
        AppointmentStatus.NO_SHOW,
    },
    AppointmentStatus.CHECKED_IN: {
        AppointmentStatus.COMPLETED,
        AppointmentStatus.CANCELLED,
        AppointmentStatus.NO_SHOW,
    },
    AppointmentStatus.COMPLETED: frozenset(),
    AppointmentStatus.CANCELLED: frozenset(),
    AppointmentStatus.NO_SHOW: frozenset(),
}


class AppointmentSource(models.TextChoices):
    ONLINE = "ONLINE", "Online"
    WHATSAPP = "WHATSAPP", "WhatsApp"
    PHONE = "PHONE", "Phone"
    WALK_IN = "WALK_IN", "Walk-in"
    DASHBOARD = "DASHBOARD", "Dashboard"


def generate_public_reference() -> str:
    return secrets.token_urlsafe(12)[:16]


class TsTzRange(Func):
    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


class Appointment(SoftDeleteModel, AuditedModel, TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    location = models.ForeignKey(
        "locations.Location",
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    staff_profile = models.ForeignKey(
        "staff.StaffProfile",
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    starts_at = models.DateTimeField(help_text="Customer-visible start (UTC).")
    ends_at = models.DateTimeField(help_text="Customer-visible end (UTC).")
    occupancy_starts_at = models.DateTimeField(
        help_text="Staff occupancy start including buffer_before (UTC).",
    )
    occupancy_ends_at = models.DateTimeField(
        help_text="Staff occupancy end including buffer_after (UTC).",
    )
    status = models.CharField(
        max_length=32,
        choices=AppointmentStatus.choices,
        default=AppointmentStatus.CONFIRMED,
    )
    source = models.CharField(
        max_length=32,
        choices=AppointmentSource.choices,
        default=AppointmentSource.DASHBOARD,
    )
    total_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    currency = models.CharField(max_length=3, default="INR")
    deposit_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0)],
    )
    deposit_paid = models.BooleanField(default=False)
    payment_status = models.CharField(
        max_length=32,
        default="NOT_REQUIRED",
        help_text=(
            "Lightweight payment state maintained by payments services. "
            "NOT_REQUIRED|PENDING|PAID|PARTIALLY_PAID|REFUNDED. "
            "Payment records remain the source of truth."
        ),
    )
    notes = models.TextField(blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="UTC time the appointment first transitioned to COMPLETED.",
    )
    cancellation_reason = models.CharField(max_length=255, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cancelled_appointments",
    )
    public_reference = models.CharField(
        max_length=32,
        unique=True,
        default=generate_public_reference,
        editable=False,
    )
    schedule_version = models.PositiveIntegerField(
        default=1,
        help_text="Increments on reschedule so older reminders cannot send.",
    )
    acquisition_source = models.CharField(
        max_length=32,
        null=True,
        blank=True,
        help_text="How the guest arrived: QUICKCARD or RETENTION. Null for direct bookings.",
    )
    acquisition_reference = models.UUIDField(
        null=True,
        blank=True,
        help_text=(
            "QuickCard id when QUICKCARD; CustomerRetentionMessage id when RETENTION. "
            "Not a cascading foreign key."
        ),
    )
    booking_plan = models.ForeignKey(
        "booking.BookingPlan",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="appointments",
    )
    plan_occurrence_date = models.DateField(
        null=True,
        blank=True,
        help_text="Local calendar date of the BookingPlan occurrence (when linked).",
    )

    class Meta:
        ordering = ["starts_at"]
        indexes = [
            models.Index(fields=["organization", "starts_at"]),
            models.Index(fields=["location", "starts_at", "status"]),
            models.Index(fields=["staff_profile", "starts_at", "status"]),
            models.Index(fields=["customer", "starts_at"]),
            models.Index(fields=["status", "starts_at"]),
            models.Index(fields=["staff_profile", "occupancy_starts_at", "occupancy_ends_at"]),
            models.Index(fields=["booking_plan", "starts_at"]),
            models.Index(
                fields=["acquisition_source", "created_at"],
                name="appt_qc_acq_created_idx",
                condition=Q(acquisition_source="QUICKCARD"),
            ),
            models.Index(
                fields=["acquisition_source", "created_at"],
                name="appt_ret_acq_created_idx",
                condition=Q(acquisition_source="RETENTION"),
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=models.F("starts_at")),
                name="appointment_ends_after_starts",
            ),
            models.CheckConstraint(
                condition=Q(occupancy_ends_at__gt=models.F("occupancy_starts_at")),
                name="appointment_occupancy_ends_after_starts",
            ),
            models.UniqueConstraint(
                fields=["booking_plan", "plan_occurrence_date"],
                condition=Q(
                    booking_plan__isnull=False,
                    plan_occurrence_date__isnull=False,
                    deleted_at__isnull=True,
                ),
                name="unique_booking_plan_occurrence_alive",
            ),
            ExclusionConstraint(
                name="excl_appointment_staff_occupancy",
                expressions=[
                    ("staff_profile", RangeOperators.EQUAL),
                    (
                        TsTzRange("occupancy_starts_at", "occupancy_ends_at"),
                        RangeOperators.OVERLAPS,
                    ),
                ],
                condition=Q(
                    status__in=sorted(OCCUPYING_STATUSES),
                    deleted_at__isnull=True,
                ),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.public_reference} ({self.status})"

    @property
    def is_occupying(self) -> bool:
        return self.deleted_at is None and self.status in OCCUPYING_STATUSES


class AppointmentItem(TimestampedModel, AuditedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.CASCADE,
        related_name="items",
    )
    service = models.ForeignKey(
        "catalog.Service",
        on_delete=models.PROTECT,
        related_name="appointment_items",
    )
    staff_profile = models.ForeignKey(
        "staff.StaffProfile",
        on_delete=models.PROTECT,
        related_name="appointment_items",
    )
    service_name = models.CharField(max_length=255)
    duration_minutes = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    buffer_before_minutes = models.PositiveIntegerField(default=0)
    buffer_after_minutes = models.PositiveIntegerField(default=0)
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    currency = models.CharField(max_length=3, default="INR")

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["appointment"]),
            models.Index(fields=["service"]),
        ]

    def __str__(self) -> str:
        return f"{self.service_name} ({self.duration_minutes}m)"


class IdempotencyRecord(TimestampedModel):
    """Reusable request-idempotency store (public booking create first consumer)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope = models.CharField(max_length=64)
    key = models.CharField(max_length=255)
    request_hash = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField()
    response_body = models.JSONField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["scope", "key"],
                name="unique_idempotency_scope_key",
            ),
        ]
        indexes = [
            models.Index(fields=["scope", "key"]),
        ]

    def __str__(self) -> str:
        return f"{self.scope}:{self.key}"


class BookingPlanFrequency(models.TextChoices):
    WEEK = "WEEK", "Week"
    MONTH = "MONTH", "Month"


class BookingPlanStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    PAUSED = "PAUSED", "Paused"
    CANCELLED = "CANCELLED", "Cancelled"


class BookingPlanStaffPreference(models.TextChoices):
    SAME_STAFF = "SAME_STAFF", "Same staff"
    ANY_STAFF = "ANY_STAFF", "Any staff"


ALLOWED_BOOKING_PLAN_TRANSITIONS = {
    BookingPlanStatus.ACTIVE: {
        BookingPlanStatus.PAUSED,
        BookingPlanStatus.CANCELLED,
    },
    BookingPlanStatus.PAUSED: {
        BookingPlanStatus.ACTIVE,
        BookingPlanStatus.CANCELLED,
    },
    BookingPlanStatus.CANCELLED: frozenset(),
}


class BookingPlan(SoftDeleteModel, AuditedModel, TimestampedModel):
    """Recurring booking intent — not a subscription; each visit is a separate Appointment."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="booking_plans",
    )
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.PROTECT,
        related_name="booking_plans",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="booking_plans",
    )
    location = models.ForeignKey(
        "locations.Location",
        on_delete=models.PROTECT,
        related_name="booking_plans",
    )
    service = models.ForeignKey(
        "catalog.Service",
        on_delete=models.PROTECT,
        related_name="booking_plans",
    )
    staff_profile = models.ForeignKey(
        "staff.StaffProfile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="booking_plans",
    )
    staff_preference = models.CharField(
        max_length=16,
        choices=BookingPlanStaffPreference.choices,
        default=BookingPlanStaffPreference.ANY_STAFF,
    )
    frequency = models.CharField(max_length=16, choices=BookingPlanFrequency.choices)
    interval = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    preferred_time = models.TimeField()
    timezone = models.CharField(max_length=64)
    start_date = models.DateField()
    next_due_at = models.DateTimeField(
        help_text="Next intended occurrence start in UTC (preferred local time).",
    )
    status = models.CharField(
        max_length=16,
        choices=BookingPlanStatus.choices,
        default=BookingPlanStatus.ACTIVE,
    )
    needs_action = models.BooleanField(default=False)
    needs_action_code = models.CharField(max_length=64, blank=True, default="")
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["next_due_at"]
        indexes = [
            models.Index(fields=["organization", "status", "next_due_at"]),
            models.Index(fields=["business", "status"]),
            models.Index(fields=["status", "next_due_at", "needs_action"]),
            models.Index(fields=["customer", "status"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(interval__gte=1),
                name="booking_plan_interval_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"BookingPlan:{self.id}:{self.status}"


class BookingPlanManageToken(TimestampedModel):
    """Secure public management capability for one BookingPlan (hash-at-rest)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking_plan = models.OneToOneField(
        BookingPlan,
        on_delete=models.CASCADE,
        related_name="manage_token",
    )
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self) -> str:
        return f"plan-manage-token:{self.booking_plan_id}"


class AppointmentManageToken(TimestampedModel):
    """Secure public management capability for one appointment.

    Only the SHA-256 hash of the raw token is stored. The raw token is shown
    once (create response / manage link) and may be passed in-process to
    post-commit notification handlers. It is never stored as a dedicated
    database field and is never recoverable from the hash.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment = models.OneToOneField(
        Appointment,
        on_delete=models.CASCADE,
        related_name="manage_token",
    )
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self) -> str:
        return f"manage-token:{self.appointment_id}"


class NotificationChannel(models.TextChoices):
    WHATSAPP = "WHATSAPP", "WhatsApp"
    SMS = "SMS", "SMS"
    EMAIL = "EMAIL", "Email"


class NotificationType(models.TextChoices):
    BOOKING_CONFIRMATION = "BOOKING_CONFIRMATION", "Booking confirmation"
    BOOKING_CANCELLATION = "BOOKING_CANCELLATION", "Booking cancellation"
    REMINDER_24H = "REMINDER_24H", "24-hour reminder"
    REMINDER_1H = "REMINDER_1H", "1-hour reminder"


class NotificationStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    SENT = "SENT", "Sent"
    FAILED = "FAILED", "Failed"


class NotificationProviderStatus(models.TextChoices):
    SENT = "sent", "Sent"
    DELIVERED = "delivered", "Delivered"
    READ = "read", "Read"
    FAILED = "failed", "Failed"


class NotificationDelivery(TimestampedModel):
    """Persisted outbound notification attempt for an appointment."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.CASCADE,
        related_name="notification_deliveries",
    )
    channel = models.CharField(max_length=16, choices=NotificationChannel.choices)
    notification_type = models.CharField(
        max_length=32,
        choices=NotificationType.choices,
    )
    recipient = models.CharField(
        max_length=64,
        help_text="Delivery address (E.164 phone or email).",
    )
    status = models.CharField(
        max_length=16,
        choices=NotificationStatus.choices,
        default=NotificationStatus.PENDING,
    )
    provider_status = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="Provider transport status (sent/delivered/read/failed).",
    )
    provider_message_id = models.CharField(max_length=128, blank=True, default="")
    attempt_count = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    error_class = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="TRANSIENT or PERMANENT when failed.",
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    payload_version = models.PositiveSmallIntegerField(default=1)
    payload_snapshot = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Frozen customer-facing message for retries. May include manage_url; "
            "not an auth credential store."
        ),
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["appointment", "channel", "notification_type"],
                name="unique_notification_delivery_appointment_channel_type",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "channel"]),
            models.Index(fields=["notification_type", "status"]),
            models.Index(fields=["appointment", "status"]),
            models.Index(fields=["provider_message_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.notification_type}:{self.channel}:{self.status}"


class WhatsAppWebhookEvent(TimestampedModel):
    """Idempotency ledger for Meta WhatsApp status callbacks."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider_message_id = models.CharField(max_length=128)
    provider_status = models.CharField(max_length=32)
    meta_timestamp = models.BigIntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider_message_id", "provider_status"],
                name="unique_whatsapp_webhook_message_status",
            ),
        ]
        indexes = [
            models.Index(fields=["provider_message_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.provider_message_id}:{self.provider_status}"
