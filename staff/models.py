import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from core.models import AuditedModel, SoftDeleteModel, TimestampedModel


class StaffProfile(SoftDeleteModel, AuditedModel, TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="staff_profiles",
    )
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.PROTECT,
        related_name="staff_profiles",
    )
    location = models.ForeignKey(
        "locations.Location",
        on_delete=models.PROTECT,
        related_name="staff_profiles",
        help_text="Primary location for this staff member.",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="staff_profiles",
        help_text="Optional login account; staff may exist without a user.",
    )
    display_name = models.CharField(max_length=255)
    title = models.CharField(max_length=255, blank=True)
    bio = models.TextField(blank=True)
    photo_url = models.URLField(max_length=500, blank=True)
    is_bookable = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["display_name"]
        indexes = [
            models.Index(fields=["organization", "is_active"]),
            models.Index(fields=["location", "is_bookable"]),
            models.Index(fields=["business", "is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"],
                condition=Q(deleted_at__isnull=True) & Q(user__isnull=False),
                name="unique_staff_profile_org_user_alive",
            ),
        ]

    def __str__(self) -> str:
        return self.display_name


class StaffService(TimestampedModel, AuditedModel):
    """Junction: which services a staff member can perform.

    Not soft-deleted. Optional duration/price overrides per staff capability.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="staff_services",
    )
    staff_profile = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name="staff_services",
    )
    service = models.ForeignKey(
        "catalog.Service",
        on_delete=models.CASCADE,
        related_name="staff_services",
    )
    duration_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="Optional staff-specific duration override.",
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Optional staff-specific price override.",
    )
    currency = models.CharField(max_length=3, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["organization", "staff_profile"]),
            models.Index(fields=["organization", "service"]),
            models.Index(fields=["staff_profile", "service"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["staff_profile", "service"],
                name="unique_staff_service_assignment",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.staff_profile} → {self.service}"


class Weekday(models.IntegerChoices):
    MONDAY = 0, "Monday"
    TUESDAY = 1, "Tuesday"
    WEDNESDAY = 2, "Wednesday"
    THURSDAY = 3, "Thursday"
    FRIDAY = 4, "Friday"
    SATURDAY = 5, "Saturday"
    SUNDAY = 6, "Sunday"


class StaffAvailability(TimestampedModel, AuditedModel):
    """Recurring weekly working hours for a staff member at a location.

    starts_at / ends_at are local wall-clock times interpreted in Location.timezone.
    Not soft-deleted. Overlaps for the same staff+location+weekday are rejected
    in the service layer (booking slot calculation is deferred).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="staff_availabilities",
    )
    staff_profile = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name="availabilities",
    )
    location = models.ForeignKey(
        "locations.Location",
        on_delete=models.PROTECT,
        related_name="staff_availabilities",
    )
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    starts_at = models.TimeField(
        help_text="Local start time in the Location's timezone.",
    )
    ends_at = models.TimeField(
        help_text="Local end time in the Location's timezone.",
    )

    class Meta:
        ordering = ["weekday", "starts_at"]
        verbose_name_plural = "staff availabilities"
        indexes = [
            models.Index(fields=["staff_profile", "weekday"]),
            models.Index(fields=["organization", "staff_profile"]),
            models.Index(fields=["staff_profile", "location", "weekday"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="staff_availability_ends_after_starts",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.staff_profile} @ {self.location} "
            f"{self.get_weekday_display()} {self.starts_at}-{self.ends_at}"
        )


class StaffTimeOff(TimestampedModel, AuditedModel):
    """Dated absence for a staff member (hours or multi-day).

    starts_at / ends_at are timezone-aware UTC timestamps.
    Not soft-deleted. Not location-scoped (org-wide for the staff member).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="staff_time_offs",
    )
    staff_profile = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name="time_offs",
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-starts_at"]
        verbose_name_plural = "staff time offs"
        indexes = [
            models.Index(fields=["staff_profile", "starts_at", "ends_at"]),
            models.Index(fields=["organization", "staff_profile"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="staff_time_off_ends_after_starts",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.staff_profile} off {self.starts_at} → {self.ends_at}"
