import uuid

from django.db import models
from django.db.models import Q
from django.utils.text import slugify

from core.models import AuditedModel, SoftDeleteModel, TimestampedModel


class QuickCard(SoftDeleteModel, AuditedModel, TimestampedModel):
    """Shareable public digital identity for a Location (presentation only)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="quickcards",
    )
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.PROTECT,
        related_name="quickcards",
    )
    location = models.OneToOneField(
        "locations.Location",
        on_delete=models.PROTECT,
        related_name="quickcard",
    )
    slug = models.SlugField(max_length=255)
    headline = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")
    logo_url = models.URLField(blank=True, default="")
    cover_image_url = models.URLField(blank=True, default="")
    phone = models.CharField(max_length=32, blank=True, default="")
    whatsapp = models.CharField(max_length=32, blank=True, default="")
    website_url = models.URLField(blank=True, default="")
    google_maps_url = models.URLField(blank=True, default="")
    instagram_url = models.URLField(blank=True, default="")
    facebook_url = models.URLField(blank=True, default="")
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    view_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["slug"]
        indexes = [
            models.Index(fields=["organization", "is_published"]),
            models.Index(fields=["slug"]),
            models.Index(fields=["business", "is_published"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["slug"],
                condition=Q(deleted_at__isnull=True),
                name="unique_quickcard_slug_alive",
            ),
        ]

    def __str__(self) -> str:
        return f"QuickCard:{self.slug}"


def suggest_quickcard_slug(*, location_name: str, location_slug: str) -> str:
    base = slugify(location_slug) or slugify(location_name) or "quickcard"
    return base[:255]


class QuickCardEventType(models.TextChoices):
    PAGE_VIEW = "PAGE_VIEW", "Page view"
    CTA_CLICK = "CTA_CLICK", "CTA click"


class QuickCardCtaType(models.TextChoices):
    BOOK = "BOOK", "Book"
    WHATSAPP = "WHATSAPP", "WhatsApp"
    CALL = "CALL", "Call"
    DIRECTIONS = "DIRECTIONS", "Directions"
    REVIEW = "REVIEW", "Review"
    SHARE = "SHARE", "Share"


class QuickCardEvent(TimestampedModel):
    """Anonymous QuickCard view or CTA click. Not a visitor profile."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="quickcard_events",
    )
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.PROTECT,
        related_name="quickcard_events",
    )
    location = models.ForeignKey(
        "locations.Location",
        on_delete=models.PROTECT,
        related_name="quickcard_events",
    )
    quickcard = models.ForeignKey(
        QuickCard,
        on_delete=models.PROTECT,
        related_name="events",
    )
    event_type = models.CharField(max_length=16, choices=QuickCardEventType.choices)
    cta_type = models.CharField(
        max_length=16,
        choices=QuickCardCtaType.choices,
        blank=True,
        default="",
    )
    occurred_at = models.DateTimeField()
    referrer = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["business", "occurred_at"], name="qc_event_biz_time_idx"),
            models.Index(
                fields=["quickcard", "event_type", "occurred_at"],
                name="qc_event_card_type_idx",
            ),
            models.Index(
                fields=["business", "cta_type", "occurred_at"],
                name="qc_event_cta_time_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"QuickCardEvent:{self.event_type}"
