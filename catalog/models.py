import uuid

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from core.models import AuditedModel, SoftDeleteModel, TimestampedModel


class ServiceCategory(SoftDeleteModel, AuditedModel, TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="service_categories",
    )
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.PROTECT,
        related_name="service_categories",
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "name"]
        indexes = [
            models.Index(fields=["organization", "business"]),
            models.Index(fields=["business", "display_order"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "slug"],
                condition=Q(deleted_at__isnull=True),
                name="unique_service_category_business_slug_alive",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Service(SoftDeleteModel, AuditedModel, TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="services",
    )
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.PROTECT,
        related_name="services",
    )
    category = models.ForeignKey(
        ServiceCategory,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="services",
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    description = models.TextField(blank=True)
    duration_minutes = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    buffer_before_minutes = models.PositiveIntegerField(default=0)
    buffer_after_minutes = models.PositiveIntegerField(default=0)
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    currency = models.CharField(max_length=3, default="INR")
    is_bookable_online = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["organization", "is_active"]),
            models.Index(fields=["business", "category"]),
            models.Index(fields=["business", "is_bookable_online"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "slug"],
                condition=Q(deleted_at__isnull=True),
                name="unique_service_business_slug_alive",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class ServiceLocation(TimestampedModel, AuditedModel):
    """Junction: a Business service offered at a specific Location.

    Not soft-deleted (junction row). Unique (service, location).
    Optional overrides for duration and price at that location.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="service_locations",
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name="service_locations",
    )
    location = models.ForeignKey(
        "locations.Location",
        on_delete=models.CASCADE,
        related_name="service_locations",
    )
    duration_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="Optional location-specific duration override.",
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Optional location-specific price override.",
    )
    currency = models.CharField(max_length=3, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["organization", "service"]),
            models.Index(fields=["organization", "location"]),
            models.Index(fields=["service", "location"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["service", "location"],
                name="unique_service_location_assignment",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.service} @ {self.location}"
