import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from core.models import AuditedModel, SoftDeleteModel, TimestampedModel


class BusinessVertical(models.TextChoices):
    SALON = "SALON", "Salon"
    SPA = "SPA", "Spa"
    BARBER = "BARBER", "Barber"
    CLINIC = "CLINIC", "Clinic"
    DENTAL = "DENTAL", "Dental"
    GYM = "GYM", "Gym"
    RESTAURANT = "RESTAURANT", "Restaurant"
    OTHER = "OTHER", "Other"


class WebsiteTemplateKey(models.TextChoices):
    SALON_MODERN = "SALON_MODERN", "Salon Modern"
    SALON_CLASSIC = "SALON_CLASSIC", "Salon Classic"
    SALON_LUXURY = "SALON_LUXURY", "Salon Luxury"


class DomainStatus(models.TextChoices):
    NOT_CONFIGURED = "NOT_CONFIGURED", "Not configured"
    PROVISIONING = "PROVISIONING", "Provisioning"
    SUBDOMAIN_ACTIVE = "SUBDOMAIN_ACTIVE", "Subdomain active"
    FAILED = "FAILED", "Failed"
    CUSTOM_DOMAIN_PENDING = "CUSTOM_DOMAIN_PENDING", "Custom domain pending"
    CUSTOM_DOMAIN_ACTIVE = "CUSTOM_DOMAIN_ACTIVE", "Custom domain active"


class GoogleBusinessStatus(models.TextChoices):
    NOT_STARTED = "NOT_STARTED", "Not started"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    READY = "READY", "Ready"
    VERIFIED = "VERIFIED", "Verified (owner-claimed)"


class WhatsAppSetupStatus(models.TextChoices):
    NOT_CONFIGURED = "NOT_CONFIGURED", "Not configured"
    CONFIGURED = "CONFIGURED", "Configured"
    ACTIVE = "ACTIVE", "Active"


class WebsiteStatus(models.TextChoices):
    NOT_STARTED = "NOT_STARTED", "Not started"
    DRAFT = "DRAFT", "Draft"
    READY = "READY", "Ready"
    PUBLISHED = "PUBLISHED", "Published"
    UNPUBLISHED = "UNPUBLISHED", "Unpublished"


class LaunchStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    READY = "READY", "Ready"
    LIVE = "LIVE", "Live"


class BusinessPaymentMode(models.TextChoices):
    NONE = "NONE", "No online payment"
    FULL = "FULL", "Full prepaid"
    DEPOSIT = "DEPOSIT", "Deposit"


class GoogleConnectionStatus(models.TextChoices):
    NOT_CONNECTED = "NOT_CONNECTED", "Not connected"
    CONNECTED = "CONNECTED", "Connected"
    LOCATION_SELECTION_REQUIRED = (
        "LOCATION_SELECTION_REQUIRED",
        "Google location selection required",
    )
    SYNCING = "SYNCING", "Syncing"
    REAUTH_REQUIRED = "REAUTH_REQUIRED", "Reauthorization required"
    ERROR = "ERROR", "Error"
    DISCONNECTED = "DISCONNECTED", "Disconnected"


class GoogleSyncStatus(models.TextChoices):
    NEVER = "NEVER", "Never synced"
    SUCCESS = "SUCCESS", "Success"
    FAILED = "FAILED", "Failed"
    SKIPPED = "SKIPPED", "Skipped"


class GoogleProviderKind(models.TextChoices):
    MOCK = "mock", "Mock"
    GOOGLE = "google", "Google"
    DEFERRED = "deferred", "Deferred"


class Business(SoftDeleteModel, AuditedModel, TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="businesses",
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    vertical = models.CharField(
        max_length=32,
        choices=BusinessVertical.choices,
        default=BusinessVertical.SALON,
    )
    description = models.TextField(blank=True)
    logo_url = models.URLField(max_length=500, blank=True)
    primary_domain = models.CharField(max_length=255, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    payment_mode = models.CharField(
        max_length=16,
        choices=BusinessPaymentMode.choices,
        default=BusinessPaymentMode.NONE,
        help_text="NONE (default), FULL prepaid, or DEPOSIT. Opt-in online collection.",
    )

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["organization", "is_active"]),
            models.Index(fields=["vertical"]),
            models.Index(fields=["primary_domain"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "slug"],
                condition=Q(deleted_at__isnull=True),
                name="unique_business_org_slug_alive",
            ),
            models.UniqueConstraint(
                fields=["primary_domain"],
                condition=Q(deleted_at__isnull=True) & Q(primary_domain__isnull=False),
                name="unique_business_primary_domain_alive",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class BusinessLaunchProfile(SoftDeleteModel, AuditedModel, TimestampedModel):
    """Per-location launch configuration. Does not duplicate Business/Location/catalog data."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="launch_profiles",
    )
    business = models.ForeignKey(
        Business,
        on_delete=models.PROTECT,
        related_name="launch_profiles",
    )
    location = models.ForeignKey(
        "locations.Location",
        on_delete=models.PROTECT,
        related_name="launch_profiles",
    )
    template_key = models.CharField(
        max_length=64,
        choices=WebsiteTemplateKey.choices,
        blank=True,
        default="",
    )
    subdomain = models.SlugField(max_length=63, blank=True, default="")
    custom_domain = models.CharField(max_length=255, blank=True, default="")
    domain_status = models.CharField(
        max_length=32,
        choices=DomainStatus.choices,
        default=DomainStatus.NOT_CONFIGURED,
    )
    google_business_url = models.URLField(max_length=500, blank=True, default="")
    google_review_url = models.URLField(max_length=500, blank=True, default="")
    google_business_status = models.CharField(
        max_length=32,
        choices=GoogleBusinessStatus.choices,
        default=GoogleBusinessStatus.NOT_STARTED,
    )
    whatsapp_setup_status = models.CharField(
        max_length=32,
        choices=WhatsAppSetupStatus.choices,
        default=WhatsAppSetupStatus.NOT_CONFIGURED,
    )
    website_status = models.CharField(
        max_length=32,
        choices=WebsiteStatus.choices,
        default=WebsiteStatus.NOT_STARTED,
    )
    launch_status = models.CharField(
        max_length=32,
        choices=LaunchStatus.choices,
        default=LaunchStatus.DRAFT,
    )

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["organization", "business"]),
            models.Index(fields=["business", "location"]),
            models.Index(fields=["launch_status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "location"],
                condition=Q(deleted_at__isnull=True),
                name="unique_launch_profile_business_location_alive",
            ),
            models.UniqueConstraint(
                fields=["subdomain"],
                condition=Q(deleted_at__isnull=True) & ~Q(subdomain=""),
                name="unique_launch_profile_subdomain_alive",
            ),
            models.UniqueConstraint(
                fields=["custom_domain"],
                condition=Q(deleted_at__isnull=True) & ~Q(custom_domain=""),
                name="unique_launch_profile_custom_domain_alive",
            ),
        ]

    def __str__(self) -> str:
        return f"LaunchProfile({self.business_id}, {self.location_id})"


class GoogleBusinessConnection(SoftDeleteModel, AuditedModel, TimestampedModel):
    """Per-location Google Business Profile connection + encrypted OAuth credentials."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="google_business_connections",
    )
    business = models.ForeignKey(
        Business,
        on_delete=models.PROTECT,
        related_name="google_business_connections",
    )
    location = models.ForeignKey(
        "locations.Location",
        on_delete=models.PROTECT,
        related_name="google_business_connections",
    )
    provider = models.CharField(
        max_length=32,
        choices=GoogleProviderKind.choices,
        default=GoogleProviderKind.DEFERRED,
        blank=True,
    )
    status = models.CharField(
        max_length=32,
        choices=GoogleConnectionStatus.choices,
        default=GoogleConnectionStatus.NOT_CONNECTED,
    )
    google_location_id = models.CharField(max_length=255, blank=True, default="")
    google_business_account_name = models.CharField(max_length=255, blank=True, default="")
    google_location_display_name = models.CharField(max_length=255, blank=True, default="")
    google_account_id = models.CharField(max_length=255, blank=True, default="")
    google_email = models.EmailField(max_length=255, blank=True, default="")
    access_token_encrypted = models.TextField(blank=True, default="")
    refresh_token_encrypted = models.TextField(blank=True, default="")
    token_expires_at = models.DateTimeField(null=True, blank=True)
    scopes = models.CharField(max_length=500, blank=True, default="")
    connected_at = models.DateTimeField(null=True, blank=True)
    last_synced_booking_url = models.URLField(max_length=500, blank=True, default="")
    last_sync_status = models.CharField(
        max_length=32,
        choices=GoogleSyncStatus.choices,
        default=GoogleSyncStatus.NEVER,
    )
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=64, blank=True, default="")
    last_error_message = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["organization", "business"]),
            models.Index(fields=["business", "location"]),
            models.Index(fields=["status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "location"],
                condition=Q(deleted_at__isnull=True),
                name="unique_google_connection_business_location_alive",
            ),
        ]

    def __str__(self) -> str:
        return f"GoogleBusinessConnection({self.location_id}, {self.status})"

    def __repr__(self) -> str:
        return (
            f"<GoogleBusinessConnection id={self.id} location_id={self.location_id} "
            f"status={self.status}>"
        )


class GoogleOAuthState(TimestampedModel):
    """Single-use OAuth state binding (stores hash only)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    state_hash = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="google_oauth_states",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="google_oauth_states",
    )
    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="google_oauth_states",
    )
    location = models.ForeignKey(
        "locations.Location",
        on_delete=models.CASCADE,
        related_name="google_oauth_states",
    )
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["expires_at"]),
            models.Index(fields=["user", "business"]),
        ]

    def __str__(self) -> str:
        return f"GoogleOAuthState({self.business_id}, {self.location_id})"
