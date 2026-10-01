import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from core.models import AuditedModel, SoftDeleteModel, TimestampedModel


def validate_iana_timezone(value: str) -> None:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, KeyError, TypeError) as exc:
        raise ValidationError(f"{value!r} is not a valid IANA timezone.") from exc


class Location(SoftDeleteModel, AuditedModel, TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="locations",
    )
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.PROTECT,
        related_name="locations",
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    address_line1 = models.CharField(max_length=255, blank=True)
    address_line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=2, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    timezone = models.CharField(max_length=64, validators=[validate_iana_timezone])
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    is_primary = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["organization", "is_active"]),
            models.Index(fields=["business", "is_active"]),
            models.Index(fields=["city", "country"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "slug"],
                condition=Q(deleted_at__isnull=True),
                name="unique_location_business_slug_alive",
            ),
            models.UniqueConstraint(
                fields=["business"],
                condition=Q(deleted_at__isnull=True) & Q(is_primary=True),
                name="unique_location_primary_per_business",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.business})"
