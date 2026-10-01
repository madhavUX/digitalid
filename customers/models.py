import secrets
import uuid
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from core.models import AuditedModel, SoftDeleteModel, TimestampedModel


def generate_retention_public_reference() -> str:
    """Opaque public ref for retention booking URLs (not a tenant/customer id)."""
    return secrets.token_urlsafe(12)[:16]


class Customer(SoftDeleteModel, AuditedModel, TimestampedModel):
    """Business-level customer record. Not a platform user; not location-scoped."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="customers",
    )
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.PROTECT,
        related_name="customers",
    )
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(
        max_length=20,
        help_text="E.164 phone; primary identity within a business.",
    )
    email = models.EmailField(max_length=254, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    marketing_opt_in = models.BooleanField(default=False)
    whatsapp_opt_in = models.BooleanField(default=False)
    first_visit_at = models.DateTimeField(null=True, blank=True)
    last_visit_at = models.DateTimeField(null=True, blank=True)
    total_visits = models.PositiveIntegerField(default=0)
    total_spend = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0)],
    )

    class Meta:
        ordering = ["last_name", "first_name"]
        indexes = [
            models.Index(fields=["organization", "business"]),
            models.Index(fields=["business", "phone"]),
            models.Index(fields=["business", "last_visit_at"]),
            models.Index(fields=["business", "email"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "phone"],
                condition=Q(deleted_at__isnull=True),
                name="unique_customer_business_phone_alive",
            ),
        ]

    def __str__(self) -> str:
        return self.full_name

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class RetentionSegment(models.TextChoices):
    NO_VISITS = "NO_VISITS", "No Visits Yet"
    NEW = "NEW", "New"
    RETURNING = "RETURNING", "Returning"
    DUE_FOR_RETURN = "DUE_FOR_RETURN", "Due for Return"
    INACTIVE = "INACTIVE", "Inactive"


class CustomerRetentionSettings(AuditedModel, TimestampedModel):
    """Business-level visit thresholds. Deterministic configuration only — not predictions."""

    DEFAULT_RETURN_AFTER_DAYS = 30
    DEFAULT_INACTIVE_AFTER_DAYS = 90
    DEFAULT_DUE_MESSAGE_DELAY_HOURS = 24

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="customer_retention_settings",
    )
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.PROTECT,
        related_name="customer_retention_settings",
    )
    return_after_days = models.PositiveIntegerField(
        default=DEFAULT_RETURN_AFTER_DAYS,
        validators=[MinValueValidator(1)],
        help_text="Configuration default for Due for Return (not a behavioral claim).",
    )
    inactive_after_days = models.PositiveIntegerField(
        default=DEFAULT_INACTIVE_AFTER_DAYS,
        validators=[MinValueValidator(1)],
        help_text="Configuration default for Inactive (not a behavioral claim).",
    )
    due_message_delay_hours = models.PositiveIntegerField(
        default=DEFAULT_DUE_MESSAGE_DELAY_HOURS,
        validators=[MinValueValidator(1)],
        help_text="Hours to wait after the due threshold before sending a retention WhatsApp.",
    )
    enabled = models.BooleanField(
        default=True,
        help_text="When false, retention automation is not scheduled or sent.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["business"],
                name="unique_customer_retention_settings_business",
            ),
            models.CheckConstraint(
                condition=models.Q(return_after_days__gte=1),
                name="customer_retention_return_after_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(inactive_after_days__gt=models.F("return_after_days")),
                name="customer_retention_inactive_after_gt_return",
            ),
            models.CheckConstraint(
                condition=models.Q(due_message_delay_hours__gte=1),
                name="customer_retention_due_delay_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"Retention settings ({self.business_id})"


class CustomerRetentionMessageStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    QUEUED = "QUEUED", "Queued"
    SENT = "SENT", "Sent"
    SKIPPED = "SKIPPED", "Skipped"
    CANCELLED = "CANCELLED", "Cancelled"
    FAILED = "FAILED", "Failed"


class CustomerRetentionMessage(TimestampedModel):
    """Due-for-Return WhatsApp schedule. One record per customer visit cycle."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="customer_retention_messages",
    )
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.PROTECT,
        related_name="customer_retention_messages",
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="retention_messages",
    )
    location = models.ForeignKey(
        "locations.Location",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="customer_retention_messages",
        help_text="Location used in the retention booking URL (set when the message is queued).",
    )
    public_reference = models.CharField(
        max_length=32,
        unique=True,
        default=generate_retention_public_reference,
        editable=False,
        help_text="Opaque ref for ?source=retention&ref=… booking URLs.",
    )
    segment = models.CharField(
        max_length=32,
        choices=RetentionSegment.choices,
        default=RetentionSegment.DUE_FOR_RETURN,
    )
    trigger_visit_at = models.DateTimeField(
        help_text="Customer last_visit_at for this retention cycle.",
    )
    scheduled_for = models.DateTimeField()
    status = models.CharField(
        max_length=16,
        choices=CustomerRetentionMessageStatus.choices,
        default=CustomerRetentionMessageStatus.PENDING,
    )
    whatsapp_message = models.ForeignKey(
        "messaging.WhatsAppMessage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="retention_messages",
    )
    idempotency_key = models.CharField(max_length=255)
    skip_reason = models.CharField(max_length=64, blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["scheduled_for"]
        indexes = [
            models.Index(fields=["status", "scheduled_for"]),
            models.Index(fields=["organization", "business", "status"]),
            models.Index(fields=["customer", "status"]),
            models.Index(fields=["location", "status"], name="cust_ret_msg_loc_status_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["idempotency_key"],
                name="unique_customer_retention_message_idempotency",
            ),
        ]

    def __str__(self) -> str:
        return f"CustomerRetentionMessage({self.customer_id}, {self.status})"


class CustomerTag(TimestampedModel, AuditedModel):
    """Business-owned label. Hard-deleted; not soft-deleted."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="customer_tags",
    )
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.PROTECT,
        related_name="customer_tags",
    )
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["organization", "business"]),
            models.Index(fields=["business", "name"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "name"],
                name="unique_customer_tag_business_name",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class CustomerTagAssignment(TimestampedModel, AuditedModel):
    """Junction: customer ↔ tag within the same business. Hard-deleted."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="customer_tag_assignments",
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="tag_assignments",
    )
    tag = models.ForeignKey(
        CustomerTag,
        on_delete=models.CASCADE,
        related_name="assignments",
    )

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["organization", "customer"]),
            models.Index(fields=["organization", "tag"]),
            models.Index(fields=["customer", "tag"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["customer", "tag"],
                name="unique_customer_tag_assignment",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.customer} → {self.tag}"
