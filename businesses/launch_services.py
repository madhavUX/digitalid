"""Business launch profile + readiness (extends setup status; OWNER/MANAGER)."""

from __future__ import annotations

import re

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils.text import slugify
from rest_framework.exceptions import ValidationError

from businesses.launch_templates import is_valid_template_key, list_website_templates
from businesses.models import (
    BusinessLaunchProfile,
    DomainStatus,
    GoogleBusinessStatus,
    LaunchStatus,
    WebsiteStatus,
    WhatsAppSetupStatus,
)
from businesses.services import get_business_for_organization
from businesses.setup_services import get_business_setup_status, resolve_dashboard_location
from locations.services import get_location_for_business

# Blocking for launch-ready (Google / WhatsApp / custom domain do not block).
LAUNCH_BLOCKING_KEYS = (
    "business",
    "location",
    "services",
    "staff",
    "availability",
    "quickcard",
    "booking",
    "template",
)

LAUNCH_PROGRESS_KEYS = (
    *LAUNCH_BLOCKING_KEYS,
    "domain",
    "google_business",
    "whatsapp",
    "website",
)

LAUNCH_BLOCKING_MESSAGES = {
    "business": "Add a business name.",
    "location": "Add at least one location.",
    "services": "Add at least one active bookable service at this location.",
    "staff": "Add at least one active bookable staff member assigned to a service.",
    "availability": "Configure staff availability for at least one staff member.",
    "quickcard": "Create and publish a QuickCard for this location.",
    "booking": (
        "Booking is not ready until services, staff, availability, "
        "and QuickCard publish are complete."
    ),
    "template": "Select a website template.",
}

_SUBDOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def site_root_domain() -> str:
    return getattr(settings, "BOOKANYTHING_SITE_DOMAIN", "bookanything.in").strip().lower()


def subdomain_hostname(subdomain: str) -> str | None:
    value = (subdomain or "").strip().lower()
    if not value:
        return None
    return f"{value}.{site_root_domain()}"


def resolve_platform_whatsapp_status() -> str:
    """Derive platform WhatsApp readiness from env — never expose secrets."""
    if not getattr(settings, "WHATSAPP_ENABLED", False):
        return WhatsAppSetupStatus.NOT_CONFIGURED
    provider = getattr(settings, "WHATSAPP_PROVIDER", "mock")
    if provider == "meta":
        token = getattr(settings, "META_WHATSAPP_ACCESS_TOKEN", "") or ""
        phone_id = getattr(settings, "META_WHATSAPP_PHONE_NUMBER_ID", "") or ""
        if token.strip() and phone_id.strip():
            return WhatsAppSetupStatus.ACTIVE
        return WhatsAppSetupStatus.CONFIGURED
    return WhatsAppSetupStatus.ACTIVE


def _normalize_subdomain(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    slug = slugify(raw.replace(".", "-"))[:63]
    if slug and not _SUBDOMAIN_RE.match(slug):
        raise ValidationError({"subdomain": "Enter a valid subdomain (letters, numbers, hyphens)."})
    return slug


def _normalize_custom_domain(value: str | None) -> str:
    raw = (value or "").strip().lower().rstrip(".")
    if not raw:
        return ""
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    raw = raw.split("/", 1)[0]
    if not raw or " " in raw or "." not in raw:
        raise ValidationError({"custom_domain": "Enter a valid domain such as www.example.com."})
    return raw[:255]


def _normalize_google_url(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    return raw[:500]


def _normalize_review_url(value: str | None) -> str:
    from urllib.parse import urlparse

    raw = (value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValidationError({"google_review_url": "Enter an https URL."})
    return raw[:500]


def compute_domain_status(
    *,
    subdomain: str,
    custom_domain: str,
    requested_status: str | None = None,
) -> str:
    if custom_domain:
        if requested_status == DomainStatus.CUSTOM_DOMAIN_ACTIVE:
            return DomainStatus.CUSTOM_DOMAIN_ACTIVE
        if requested_status in {
            DomainStatus.CUSTOM_DOMAIN_PENDING,
            DomainStatus.CUSTOM_DOMAIN_ACTIVE,
        }:
            return requested_status
        return DomainStatus.CUSTOM_DOMAIN_PENDING
    if subdomain:
        return DomainStatus.SUBDOMAIN_ACTIVE
    return DomainStatus.NOT_CONFIGURED


def _default_subdomain_for_location(location) -> str:
    base = slugify(location.slug or location.name)[:63] or "business"
    candidate = base
    suffix = 1
    while BusinessLaunchProfile.objects.filter(subdomain=candidate).exists():
        suffix += 1
        trimmed = base[: max(1, 63 - len(str(suffix)) - 1)]
        candidate = f"{trimmed}-{suffix}"
    return candidate


@transaction.atomic
def get_or_create_launch_profile(
    *,
    organization,
    business_id,
    location_id,
    actor=None,
) -> BusinessLaunchProfile:
    business = get_business_for_organization(
        organization=organization,
        business_id=business_id,
    )
    location = get_location_for_business(
        organization=organization,
        business=business,
        location_id=location_id,
    )
    existing = (
        BusinessLaunchProfile.objects.filter(
            organization=organization,
            business=business,
            location=location,
        )
        .select_related("business", "location")
        .first()
    )
    if existing is not None:
        return _sync_profile_derived_fields(existing)

    subdomain = _default_subdomain_for_location(location)
    profile = BusinessLaunchProfile(
        organization=organization,
        business=business,
        location=location,
        subdomain=subdomain,
        domain_status=DomainStatus.SUBDOMAIN_ACTIVE,
        whatsapp_setup_status=resolve_platform_whatsapp_status(),
        created_by=actor,
        updated_by=actor,
    )
    try:
        profile.save()
    except IntegrityError as exc:
        raise ValidationError({"subdomain": "This subdomain is already in use."}) from exc
    return profile


def _sync_profile_derived_fields(profile: BusinessLaunchProfile) -> BusinessLaunchProfile:
    platform_wa = resolve_platform_whatsapp_status()
    update_fields: list[str] = []
    # Prefer platform truth when more advanced than stored tracking status.
    rank = {
        WhatsAppSetupStatus.NOT_CONFIGURED: 0,
        WhatsAppSetupStatus.CONFIGURED: 1,
        WhatsAppSetupStatus.ACTIVE: 2,
    }
    if rank[platform_wa] > rank.get(profile.whatsapp_setup_status, 0):
        profile.whatsapp_setup_status = platform_wa
        update_fields.append("whatsapp_setup_status")

    domain_status = compute_domain_status(
        subdomain=profile.subdomain,
        custom_domain=profile.custom_domain,
        requested_status=profile.domain_status,
    )
    if domain_status != profile.domain_status:
        profile.domain_status = domain_status
        update_fields.append("domain_status")

    if update_fields:
        profile.save(update_fields=[*update_fields, "updated_at"])
    return profile


@transaction.atomic
def update_launch_profile(
    *,
    organization,
    business_id,
    location_id,
    actor,
    data: dict,
) -> BusinessLaunchProfile:
    profile = get_or_create_launch_profile(
        organization=organization,
        business_id=business_id,
        location_id=location_id,
        actor=actor,
    )
    requested_launch_status = data.get("launch_status") if "launch_status" in data else None

    if "template_key" in data:
        key = (data.get("template_key") or "").strip()
        if key and not is_valid_template_key(key):
            raise ValidationError({"template_key": "Unknown template key."})
        profile.template_key = key
        if key and profile.website_status in {
            WebsiteStatus.NOT_STARTED,
            WebsiteStatus.DRAFT,
        }:
            profile.website_status = WebsiteStatus.READY

    if "subdomain" in data:
        profile.subdomain = _normalize_subdomain(data.get("subdomain"))

    if "custom_domain" in data:
        profile.custom_domain = _normalize_custom_domain(data.get("custom_domain"))

    requested_domain_status = data.get("domain_status")
    profile.domain_status = compute_domain_status(
        subdomain=profile.subdomain,
        custom_domain=profile.custom_domain,
        requested_status=requested_domain_status or profile.domain_status,
    )

    if "google_business_url" in data:
        profile.google_business_url = _normalize_google_url(data.get("google_business_url"))
        if (
            profile.google_business_url
            and profile.google_business_status == GoogleBusinessStatus.NOT_STARTED
        ):
            profile.google_business_status = GoogleBusinessStatus.IN_PROGRESS

    if "google_review_url" in data:
        profile.google_review_url = _normalize_review_url(data.get("google_review_url"))

    if "google_business_status" in data:
        status_value = data.get("google_business_status") or GoogleBusinessStatus.NOT_STARTED
        if status_value not in GoogleBusinessStatus.values:
            raise ValidationError({"google_business_status": "Invalid status."})
        # VERIFIED is owner-claimed tracking only — BookAnything does not verify with Google.
        profile.google_business_status = status_value

    if "whatsapp_setup_status" in data:
        status_value = data.get("whatsapp_setup_status")
        if status_value not in WhatsAppSetupStatus.values:
            raise ValidationError({"whatsapp_setup_status": "Invalid status."})
        platform = resolve_platform_whatsapp_status()
        if (
            status_value == WhatsAppSetupStatus.ACTIVE
            and platform == WhatsAppSetupStatus.NOT_CONFIGURED
        ):
            raise ValidationError(
                {"whatsapp_setup_status": "WhatsApp is not configured on the platform."}
            )
        profile.whatsapp_setup_status = status_value

    should_publish = False
    if "website_status" in data:
        status_value = data.get("website_status")
        if status_value not in WebsiteStatus.values:
            raise ValidationError({"website_status": "Invalid status."})
        if status_value == WebsiteStatus.PUBLISHED:
            should_publish = True
        else:
            profile.website_status = status_value

    profile.updated_by = actor
    try:
        profile.save()
    except IntegrityError as exc:
        raise ValidationError(
            {"detail": "Domain or subdomain conflicts with another launch profile."}
        ) from exc

    profile = _sync_profile_derived_fields(profile)

    wants_live = requested_launch_status == LaunchStatus.LIVE or should_publish
    if wants_live:
        from sites.provisioning_services import publish_website as publish_website_service

        publish_website_service(
            organization=organization,
            business_id=business_id,
            location_id=location_id,
            actor=actor,
        )
        return (
            BusinessLaunchProfile.objects.select_related("location", "business")
            .filter(
                organization=organization,
                business_id=business_id,
                location_id=location_id,
            )
            .get()
        )

    if requested_launch_status is not None:
        if requested_launch_status not in LaunchStatus.values:
            raise ValidationError({"launch_status": "Invalid status."})
        profile.launch_status = requested_launch_status
        profile.updated_by = actor
        profile.save(update_fields=["launch_status", "updated_by", "updated_at"])

    return profile


def serialize_launch_profile(profile: BusinessLaunchProfile) -> dict:
    from sites.provisioning_services import provisioned_public_url

    return {
        "id": str(profile.id),
        "business_id": str(profile.business_id),
        "location_id": str(profile.location_id),
        "template_key": profile.template_key or None,
        "subdomain": profile.subdomain or None,
        "subdomain_hostname": subdomain_hostname(profile.subdomain),
        "public_url": (provisioned_public_url(profile.subdomain) if profile.subdomain else None),
        "custom_domain": profile.custom_domain or None,
        "domain_status": profile.domain_status,
        "google_business_url": profile.google_business_url or None,
        "google_review_url": profile.google_review_url or None,
        "google_business_status": profile.google_business_status,
        "whatsapp_setup_status": profile.whatsapp_setup_status,
        "website_status": profile.website_status,
        "launch_status": profile.launch_status,
        "created_at": profile.created_at.isoformat().replace("+00:00", "Z"),
        "updated_at": profile.updated_at.isoformat().replace("+00:00", "Z"),
    }


def get_business_launch_status(
    *,
    organization,
    business_id,
    location_id=None,
) -> dict:
    setup = get_business_setup_status(
        organization=organization,
        business_id=business_id,
        location_id=location_id,
    )
    business = get_business_for_organization(
        organization=organization,
        business_id=business_id,
    )

    location = None
    profile = None
    if setup["location"] is not None:
        location = resolve_dashboard_location(
            organization=organization,
            business=business,
            location_id=setup["location"]["id"],
        )
        profile = get_or_create_launch_profile(
            organization=organization,
            business_id=business_id,
            location_id=location.id,
        )

    steps_setup = setup["steps"]
    booking_ready = bool(setup["ready"])
    template_selected = bool(profile and profile.template_key)
    domain_configured = bool(
        profile
        and profile.domain_status
        in {
            DomainStatus.SUBDOMAIN_ACTIVE,
            DomainStatus.CUSTOM_DOMAIN_PENDING,
            DomainStatus.CUSTOM_DOMAIN_ACTIVE,
        }
    )
    if profile and profile.google_business_status in {
        GoogleBusinessStatus.READY,
        GoogleBusinessStatus.VERIFIED,
    }:
        google_configured = True
    elif profile and profile.google_business_status == GoogleBusinessStatus.IN_PROGRESS:
        google_configured = bool(profile.google_business_url)
    else:
        google_configured = False

    whatsapp_status = (
        profile.whatsapp_setup_status if profile else resolve_platform_whatsapp_status()
    )
    whatsapp_configured = whatsapp_status in {
        WhatsAppSetupStatus.CONFIGURED,
        WhatsAppSetupStatus.ACTIVE,
    }
    website_status = profile.website_status if profile else WebsiteStatus.NOT_STARTED
    website_started = website_status != WebsiteStatus.NOT_STARTED

    checklist = {
        "business": steps_setup["business"],
        "location": steps_setup["location"],
        "services": steps_setup["services"],
        "staff": steps_setup["staff"],
        "availability": steps_setup["availability"],
        "quickcard": steps_setup["quickcard"] and steps_setup["publish"],
        "booking": booking_ready,
        "template": template_selected,
        "domain": domain_configured,
        "google_business": google_configured,
        "whatsapp": whatsapp_configured,
        "website": website_started,
    }

    blocking = [LAUNCH_BLOCKING_MESSAGES[key] for key in LAUNCH_BLOCKING_KEYS if not checklist[key]]
    ready = len(blocking) == 0
    # Progress is launch-blocking only so ready ⇒ 100%. Soft items remain in checklist.
    completed = sum(1 for key in LAUNCH_BLOCKING_KEYS if checklist[key])
    progress = int(round((completed / len(LAUNCH_BLOCKING_KEYS)) * 100))
    soft_completed = sum(1 for key in LAUNCH_PROGRESS_KEYS if checklist[key])

    # Authoritative launch_status: LIVE sticks if set; else READY/DRAFT from readiness.
    stored_launch = profile.launch_status if profile else LaunchStatus.DRAFT
    if stored_launch == LaunchStatus.LIVE and ready:
        launch_status = LaunchStatus.LIVE
    elif ready:
        launch_status = LaunchStatus.READY
        if profile and profile.launch_status == LaunchStatus.DRAFT:
            profile.launch_status = LaunchStatus.READY
            profile.save(update_fields=["launch_status", "updated_at"])
    else:
        launch_status = LaunchStatus.DRAFT
        if profile and profile.launch_status == LaunchStatus.READY:
            profile.launch_status = LaunchStatus.DRAFT
            profile.save(update_fields=["launch_status", "updated_at"])

    remaining = sum(1 for key in LAUNCH_BLOCKING_KEYS if not checklist[key])

    return {
        "ready": ready,
        "progress": progress,
        "completed_steps": completed,
        "total_steps": len(LAUNCH_BLOCKING_KEYS),
        "soft_completed_steps": soft_completed,
        "soft_total_steps": len(LAUNCH_PROGRESS_KEYS),
        "remaining_blocking": remaining,
        "launch_status": launch_status,
        "checklist": checklist,
        "blocking_reasons": blocking,
        "template": {
            "selected": template_selected,
            "key": profile.template_key if profile and profile.template_key else None,
            "options": list_website_templates(),
        },
        "domain": {
            "configured": domain_configured,
            "status": profile.domain_status if profile else DomainStatus.NOT_CONFIGURED,
            "subdomain": profile.subdomain if profile else None,
            "subdomain_hostname": (subdomain_hostname(profile.subdomain) if profile else None),
            "custom_domain": profile.custom_domain if profile else None,
            "site_root_domain": site_root_domain(),
        },
        "google_business": {
            "configured": google_configured,
            "status": (
                profile.google_business_status if profile else GoogleBusinessStatus.NOT_STARTED
            ),
            "url": profile.google_business_url if profile else None,
            "review_url": profile.google_review_url if profile else None,
        },
        "whatsapp": {
            "configured": whatsapp_configured,
            "status": whatsapp_status,
            "platform_status": resolve_platform_whatsapp_status(),
        },
        "website": {
            "status": website_status,
        },
        "quickcard": {
            "created": bool(steps_setup["quickcard"]),
            "published": bool(steps_setup["publish"]),
        },
        "booking": {
            "ready": booking_ready,
        },
        "profile": serialize_launch_profile(profile) if profile else None,
        "business": setup["business"],
        "location": setup["location"],
        "locations": setup["locations"],
    }
