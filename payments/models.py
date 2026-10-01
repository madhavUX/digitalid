"""Payment domain models. Provider state is authoritative only after verified response/webhook."""

from __future__ import annotations

import secrets
import uuid
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from core.models import TimestampedModel


def generate_payment_public_reference() -> str:
    return secrets.token_urlsafe(12)[:16]


def generate_order_public_reference() -> str:
    return secrets.token_urlsafe(12)[:16]


class PaymentProviderKind(models.TextChoices):
    RAZORPAY = "razorpay", "Razorpay"
    MOCK = "mock", "Mock"


class PaymentOrderStatus(models.TextChoices):
    CREATED = "CREATED", "Created"
    ATTEMPTED = "ATTEMPTED", "Attempted"
    PAID = "PAID", "Paid"
    FAILED = "FAILED", "Failed"
    EXPIRED = "EXPIRED", "Expired"
    CANCELLED = "CANCELLED", "Cancelled"


class PaymentStatus(models.TextChoices):
    CREATED = "CREATED", "Created"
    PENDING = "PENDING", "Pending"
    AUTHORIZED = "AUTHORIZED", "Authorized"
    PAID = "PAID", "Paid"
    FAILED = "FAILED", "Failed"
    CANCELLED = "CANCELLED", "Cancelled"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED", "Partially refunded"
    REFUNDED = "REFUNDED", "Refunded"


class AppointmentPaymentStatus(models.TextChoices):
    NOT_REQUIRED = "NOT_REQUIRED", "Not required"
    PENDING = "PENDING", "Pending"
    PAID = "PAID", "Paid"
    PARTIALLY_PAID = "PARTIALLY_PAID", "Partially paid"
    REFUNDED = "REFUNDED", "Refunded"


class RefundStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    PROCESSED = "PROCESSED", "Processed"
    FAILED = "FAILED", "Failed"
    CANCELLED = "CANCELLED", "Cancelled"


class WebhookEventStatus(models.TextChoices):
    RECEIVED = "RECEIVED", "Received"
    PROCESSED = "PROCESSED", "Processed"
    IGNORED = "IGNORED", "Ignored"
    FAILED = "FAILED", "Failed"


class PaymentOrder(TimestampedModel):
    """One checkout attempt for an appointment. Retries create new orders."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="payment_orders",
    )
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.PROTECT,
        related_name="payment_orders",
    )
    location = models.ForeignKey(
        "locations.Location",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_orders",
    )
    appointment = models.ForeignKey(
        "booking.Appointment",
        on_delete=models.PROTECT,
        related_name="payment_orders",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="payment_orders",
    )
    provider = models.CharField(
        max_length=32,
        choices=PaymentProviderKind.choices,
        default=PaymentProviderKind.RAZORPAY,
    )
    status = models.CharField(
        max_length=32,
        choices=PaymentOrderStatus.choices,
        default=PaymentOrderStatus.CREATED,
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    currency = models.CharField(max_length=3, default="INR")
    provider_order_id = models.CharField(max_length=128, null=True, blank=True)
    public_reference = models.CharField(
        max_length=32,
        unique=True,
        default=generate_order_public_reference,
        editable=False,
    )
    idempotency_key = models.CharField(max_length=255)
    expires_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "business", "status"]),
            models.Index(fields=["appointment", "status"]),
            models.Index(fields=["status", "created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="unique_payment_order_org_idempotency",
            ),
            models.UniqueConstraint(
                fields=["provider", "provider_order_id"],
                condition=Q(provider_order_id__isnull=False) & ~Q(provider_order_id=""),
                name="unique_payment_order_provider_order_id",
            ),
        ]

    def __str__(self) -> str:
        return f"PaymentOrder({self.public_reference}, {self.status})"


class Payment(TimestampedModel):
    """Verified payment outcome for an appointment. Source of truth for money state."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="payments",
    )
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.PROTECT,
        related_name="payments",
    )
    location = models.ForeignKey(
        "locations.Location",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    appointment = models.ForeignKey(
        "booking.Appointment",
        on_delete=models.PROTECT,
        related_name="payments",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="payments",
    )
    payment_order = models.ForeignKey(
        PaymentOrder,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    provider = models.CharField(
        max_length=32,
        choices=PaymentProviderKind.choices,
        default=PaymentProviderKind.RAZORPAY,
    )
    status = models.CharField(
        max_length=32,
        choices=PaymentStatus.choices,
        default=PaymentStatus.CREATED,
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    currency = models.CharField(max_length=3, default="INR")
    amount_paid = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    amount_refunded = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    provider_order_id = models.CharField(max_length=128, null=True, blank=True)
    provider_payment_id = models.CharField(max_length=128, null=True, blank=True)
    provider_signature = models.CharField(max_length=255, blank=True, default="")
    public_reference = models.CharField(
        max_length=32,
        unique=True,
        default=generate_payment_public_reference,
        editable=False,
    )
    idempotency_key = models.CharField(max_length=255, blank=True, default="")
    failure_code = models.CharField(max_length=64, blank=True, default="")
    failure_reason = models.CharField(max_length=255, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "business", "status"]),
            models.Index(fields=["appointment", "status"]),
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["provider_order_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_payment_id"],
                condition=Q(provider_payment_id__isnull=False) & ~Q(provider_payment_id=""),
                name="unique_payment_provider_payment_id",
            ),
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                condition=~Q(idempotency_key=""),
                name="unique_payment_org_idempotency",
            ),
        ]

    def __str__(self) -> str:
        return f"Payment({self.public_reference}, {self.status})"

    @property
    def refundable_amount(self) -> Decimal:
        return max(self.amount_paid - self.amount_refunded, Decimal("0.00"))


class Refund(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="payment_refunds",
    )
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.PROTECT,
        related_name="payment_refunds",
    )
    payment = models.ForeignKey(
        Payment,
        on_delete=models.PROTECT,
        related_name="refunds",
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    currency = models.CharField(max_length=3, default="INR")
    status = models.CharField(
        max_length=32,
        choices=RefundStatus.choices,
        default=RefundStatus.PENDING,
    )
    provider_refund_id = models.CharField(max_length=128, null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True, default="")
    idempotency_key = models.CharField(max_length=255)
    processed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["payment", "status"]),
            models.Index(fields=["organization", "business", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="unique_refund_org_idempotency",
            ),
            models.UniqueConstraint(
                fields=["provider_refund_id"],
                condition=Q(provider_refund_id__isnull=False) & ~Q(provider_refund_id=""),
                name="unique_refund_provider_refund_id",
            ),
        ]

    def __str__(self) -> str:
        return f"Refund({self.id}, {self.status})"


class PaymentWebhookEvent(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.CharField(max_length=32, choices=PaymentProviderKind.choices)
    provider_event_id = models.CharField(max_length=255)
    event_type = models.CharField(max_length=128)
    payload_hash = models.CharField(max_length=64)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=32,
        choices=WebhookEventStatus.choices,
        default=WebhookEventStatus.RECEIVED,
    )
    error_message = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["provider", "event_type", "received_at"]),
            models.Index(fields=["status", "received_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_event_id"],
                name="unique_payment_webhook_provider_event",
            ),
        ]

    def __str__(self) -> str:
        return f"PaymentWebhookEvent({self.provider}, {self.event_type})"
