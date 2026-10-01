"""Website subdomain provisioning over BusinessLaunchProfile (no duplicated domain data)."""

from __future__ import annotations

import logging
import re

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils.text import slugify
from rest_framework.exceptions import ValidationError

from businesses.launch_services import get_business_launch_status, get_or_create_launch_profile
from businesses.launch_templates import is_valid_template_key
from businesses.models import (
    BusinessLaunchProfile,
    DomainStatus,
    LaunchStatus,
    WebsiteStatus,
)
from businesses.services import get_business_for_organization
from locations.services import get_location_for_business
from sites.models import QuickCard

logger = logging.getLogger(__name__)

_SUBDOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_RESERVED_SUBDOMAINS = frozenset(
    {
        "www",
        "app",
        "api",
        "admin",
        "owner",
        "book",
        "booking",
        "static",
        "assets",
        "mail",
        "ftp",
        "cdn",
        "status",
        "help",
        "support",
    }
)


def site_root_domain() -> str:
    return getattr(settings, "BOOKANYTHING_SITE_DOMAIN", "bookanything.in").strip().lower()


def _public_app_base_url() -> str:
    return (getattr(settings, "PUBLIC_APP_URL", "") or "http://localhost:3000").rstrip("/")


def normalize_subdomain_label(value: str | None) -> str:
    raw = (value or "").strip().lower()
    slug = slugify(raw.replace(".", "-").replace("&", " and "))[:63]
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    if not slug:
        return "business"
    if slug in _RESERVED_SUBDOMAINS:
        slug = f"{slug}-site"
    if not _SUBDOMAIN_RE.match(slug):
        raise ValidationError({"subdomain": "Enter a valid subdomain (letters, numbers, hyphens)."})
    return slug[:63]


def provisioned_public_url(subdomain: str) -> str:
    """Canonical public website URL for a provisioned subdomain."""
    label = (subdomain or "").strip().lower()
    root = site_root_domain()
    if not label:
        return ""
    # Local/dev: path-based fallback (hosts/DNS for subdomains often unavailable).
    if root in {"localhost", "127.0.0.1"} or root.endswith(".localhost"):
        return f"{_public_app_base_url()}/site/{label}"
    return f"https://{label}.{root}"


def internal_site_path(subdomain: str | None, location_slug: str) -> str:
    if subdomain:
        return f"/site/{subdomain}"
    return f"/site/{location_slug}"


def serialize_website_status(profile: BusinessLaunchProfile) -> dict:
    public_url = provisioned_public_url(profile.subdomain) if profile.subdomain else None
    return {
        "location_id": str(profile.location_id),
        "business_id": str(profile.business_id),
        "template_key": profile.template_key or None,
        "website_status": profile.website_status,
        "domain_status": profile.domain_status,
        "launch_status": profile.launch_status,
        "subdomain": profile.subdomain or None,
        "subdomain_hostname": (
            f"{profile.subdomain}.{site_root_domain()}" if profile.subdomain else None
        ),
        "public_url": public_url,
        "internal_path": internal_site_path(profile.subdomain, profile.location.slug),
        "custom_domain": profile.custom_domain or None,
    }


def _base_subdomain_candidate(*, location, business) -> str:
    source = location.slug or business.slug or business.name or location.name
    return normalize_subdomain_label(source)


def allocate_unique_subdomain(
    *,
    location,
    business,
    preferred: str | None = None,
    exclude_profile_id=None,
) -> str:
    """Deterministic collision strategy: base, base-2, base-3, …"""
    base = (
        normalize_subdomain_label(preferred)
        if preferred
        else _base_subdomain_candidate(
            location=location,
            business=business,
        )
    )
    candidate = base
    suffix = 2
    while True:
        qs = BusinessLaunchProfile.objects.filter(subdomain=candidate)
        if exclude_profile_id is not None:
            qs = qs.exclude(pk=exclude_profile_id)
        if not qs.exists():
            return candidate
        trimmed = base[: max(1, 63 - len(str(suffix)) - 1)]
        candidate = f"{trimmed}-{suffix}"
        suffix += 1
        if suffix > 10_000:
            raise ValidationError({"subdomain": "Unable to allocate a unique subdomain."})


@transaction.atomic
def provision_website(
    *,
    organization,
    business_id,
    location_id,
    actor=None,
    preferred_subdomain: str | None = None,
) -> BusinessLaunchProfile:
    """
    Ensure a unique BookAnything subdomain for the location.

    Idempotent: returns the existing subdomain when already provisioned.
    """
    business = get_business_for_organization(
        organization=organization,
        business_id=business_id,
    )
    location = get_location_for_business(
        organization=organization,
        business=business,
        location_id=location_id,
    )
    profile = get_or_create_launch_profile(
        organization=organization,
        business_id=business_id,
        location_id=location_id,
        actor=actor,
    )
    profile = (
        BusinessLaunchProfile.objects.select_for_update()
        .select_related("location", "business")
        .get(pk=profile.pk)
    )

    if profile.subdomain and profile.domain_status in {
        DomainStatus.SUBDOMAIN_ACTIVE,
        DomainStatus.CUSTOM_DOMAIN_PENDING,
        DomainStatus.CUSTOM_DOMAIN_ACTIVE,
    }:
        return profile

    # Retry after FAILED, or finish incomplete provisioning.
    if profile.subdomain and profile.domain_status == DomainStatus.FAILED:
        profile.domain_status = DomainStatus.PROVISIONING
        profile.save(update_fields=["domain_status", "updated_at"])
        if profile.custom_domain:
            profile.domain_status = DomainStatus.CUSTOM_DOMAIN_PENDING
        else:
            profile.domain_status = DomainStatus.SUBDOMAIN_ACTIVE
        profile.updated_by = actor
        profile.save(update_fields=["domain_status", "updated_by", "updated_at"])
        return profile

    profile.domain_status = DomainStatus.PROVISIONING
    profile.updated_by = actor
    profile.save(update_fields=["domain_status", "updated_by", "updated_at"])

    try:
        if not profile.subdomain:
            profile.subdomain = allocate_unique_subdomain(
                location=location,
                business=business,
                preferred=preferred_subdomain,
                exclude_profile_id=profile.pk,
            )
        else:
            # Normalize / reserve existing label; collide → allocate with suffix.
            desired = normalize_subdomain_label(profile.subdomain)
            conflict = (
                BusinessLaunchProfile.objects.filter(subdomain=desired)
                .exclude(pk=profile.pk)
                .exists()
            )
            profile.subdomain = (
                allocate_unique_subdomain(
                    location=location,
                    business=business,
                    preferred=desired,
                    exclude_profile_id=profile.pk,
                )
                if conflict
                else desired
            )

        if profile.custom_domain:
            profile.domain_status = DomainStatus.CUSTOM_DOMAIN_PENDING
        else:
            profile.domain_status = DomainStatus.SUBDOMAIN_ACTIVE
        profile.updated_by = actor
        profile.save(update_fields=["subdomain", "domain_status", "updated_by", "updated_at"])
    except Exception:
        logger.exception(
            "website.provisioning_failed business_id=%s location_id=%s",
            business_id,
            location_id,
        )
        profile.domain_status = DomainStatus.FAILED
        profile.updated_by = actor
        profile.save(update_fields=["domain_status", "updated_by", "updated_at"])
        raise ValidationError(
            {"domain_status": "Website provisioning failed. Please try again."}
        ) from None

    return profile


def _sync_quickcard_website_url(*, profile: BusinessLaunchProfile) -> None:
    public_url = provisioned_public_url(profile.subdomain)
    if not public_url:
        return
    card = (
        QuickCard.objects.filter(
            organization=profile.organization,
            business=profile.business,
            location=profile.location,
            deleted_at__isnull=True,
        )
        .order_by("created_at")
        .first()
    )
    if card is None:
        return
    if card.website_url:
        return
    card.website_url = public_url
    card.save(update_fields=["website_url", "updated_at"])


@transaction.atomic
def publish_website(
    *,
    organization,
    business_id,
    location_id,
    actor,
) -> dict:
    """Validate readiness, provision subdomain, mark website published / LIVE."""
    status_payload = get_business_launch_status(
        organization=organization,
        business_id=business_id,
        location_id=location_id,
    )
    if not status_payload["ready"]:
        raise ValidationError(
            {
                "website_status": "Cannot publish until launch requirements are met.",
                "blocking_reasons": status_payload["blocking_reasons"],
            }
        )
    if not is_valid_template_key(status_payload.get("template", {}).get("key")):
        raise ValidationError({"template_key": "Select a website template before publishing."})

    try:
        profile = provision_website(
            organization=organization,
            business_id=business_id,
            location_id=location_id,
            actor=actor,
        )
    except ValidationError:
        raise
    except Exception:
        logger.exception(
            "website.publish_failed business_id=%s location_id=%s",
            business_id,
            location_id,
        )
        raise ValidationError(
            {"website_status": "Website publishing failed. Please try again."}
        ) from None

    if profile.domain_status == DomainStatus.FAILED or not profile.subdomain:
        raise ValidationError({"domain_status": "Website provisioning failed. Please try again."})

    profile.website_status = WebsiteStatus.PUBLISHED
    profile.launch_status = LaunchStatus.LIVE
    if not profile.custom_domain:
        profile.domain_status = DomainStatus.SUBDOMAIN_ACTIVE
    profile.updated_by = actor
    try:
        profile.save(
            update_fields=[
                "website_status",
                "launch_status",
                "domain_status",
                "updated_by",
                "updated_at",
            ]
        )
    except IntegrityError as exc:
        raise ValidationError({"subdomain": "This subdomain is already in use."}) from exc

    _sync_quickcard_website_url(profile=profile)
    return serialize_website_status(profile)


@transaction.atomic
def unpublish_website(
    *,
    organization,
    business_id,
    location_id,
    actor,
) -> dict:
    """Hide the public site; keep subdomain reserved for the location."""
    profile = get_or_create_launch_profile(
        organization=organization,
        business_id=business_id,
        location_id=location_id,
        actor=actor,
    )
    profile = (
        BusinessLaunchProfile.objects.select_for_update()
        .select_related("location", "business")
        .get(pk=profile.pk)
    )
    profile.website_status = WebsiteStatus.UNPUBLISHED
    if profile.launch_status == LaunchStatus.LIVE:
        profile.launch_status = LaunchStatus.READY
    # Subdomain remains; domain stays ACTIVE / reserved.
    if profile.subdomain and profile.domain_status not in {
        DomainStatus.CUSTOM_DOMAIN_PENDING,
        DomainStatus.CUSTOM_DOMAIN_ACTIVE,
    }:
        profile.domain_status = DomainStatus.SUBDOMAIN_ACTIVE
    profile.updated_by = actor
    profile.save(
        update_fields=[
            "website_status",
            "launch_status",
            "domain_status",
            "updated_by",
            "updated_at",
        ]
    )
    return serialize_website_status(profile)


def get_website_status(
    *,
    organization,
    business_id,
    location_id,
) -> dict:
    profile = get_or_create_launch_profile(
        organization=organization,
        business_id=business_id,
        location_id=location_id,
    )
    return serialize_website_status(profile)
