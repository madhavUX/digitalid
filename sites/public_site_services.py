"""Public salon website payload — presentation over existing domain data."""

from __future__ import annotations

from django.conf import settings
from rest_framework.exceptions import NotFound

from businesses.launch_templates import is_valid_template_key
from businesses.models import (
    BusinessLaunchProfile,
    BusinessVertical,
    WebsiteStatus,
)
from businesses.setup_services import get_business_setup_status
from catalog.public_services import list_public_services, serialize_public_service
from locations.models import Location
from locations.public_services import resolve_public_location_by_slug
from sites.models import QuickCard
from sites.services import (
    booking_url_for_location,
    provisional_opening_hours,
    public_quickcard_path,
    public_quickcard_url,
)
from staff.public_services import list_public_staff, serialize_public_staff

VERTICAL_LABELS = {choice.value: choice.label for choice in BusinessVertical}


def _format_address(location: Location) -> str:
    parts = [
        location.address_line1,
        location.address_line2,
        location.city,
        location.state,
        location.postal_code,
        location.country,
    ]
    return ", ".join(p for p in parts if p)


def _public_app_base_url() -> str:
    return (getattr(settings, "PUBLIC_APP_URL", "") or "http://localhost:3000").rstrip("/")


def resolve_site_location_by_slug(slug: str) -> Location:
    """Resolve by location slug or launch-profile subdomain (exact one match)."""
    cleaned = (slug or "").strip().lower()
    if not cleaned:
        raise NotFound(detail="Business not found.")

    try:
        return resolve_public_location_by_slug(cleaned)
    except NotFound:
        pass

    profiles = list(
        BusinessLaunchProfile.objects.select_related(
            "location",
            "location__business",
            "business",
            "organization",
        ).filter(
            subdomain=cleaned,
            deleted_at__isnull=True,
            location__is_active=True,
            location__deleted_at__isnull=True,
            business__is_active=True,
            business__deleted_at__isnull=True,
        )[:2]
    )
    if len(profiles) != 1:
        raise NotFound(detail="Business not found.")
    return profiles[0].location


def get_launch_profile_for_location(location: Location) -> BusinessLaunchProfile | None:
    return (
        BusinessLaunchProfile.objects.filter(
            organization=location.organization,
            business=location.business,
            location=location,
            deleted_at__isnull=True,
        )
        .select_related("business", "location")
        .first()
    )


def get_quickcard_for_location_public(location: Location) -> QuickCard | None:
    return (
        QuickCard.objects.filter(
            organization=location.organization,
            business=location.business,
            location=location,
            deleted_at__isnull=True,
        )
        .select_related("location", "business")
        .first()
    )


def is_website_publicly_visible(
    *, profile: BusinessLaunchProfile | None, setup_ready: bool
) -> bool:
    if profile is None:
        return False
    if not is_valid_template_key(profile.template_key):
        return False
    if not setup_ready:
        return False
    if not profile.subdomain:
        return False
    # Unpublish must hide the site even if launch_status was previously LIVE.
    return profile.website_status == WebsiteStatus.PUBLISHED


def _site_public_path(location: Location, profile: BusinessLaunchProfile | None) -> str:
    return f"/site/{location.slug}"


def _site_public_url(location: Location, profile: BusinessLaunchProfile | None) -> str:
    return f"{_public_app_base_url()}{_site_public_path(location, profile)}"


def build_public_site_payload(
    *,
    location: Location,
    preview: bool = False,
) -> dict:
    profile = get_launch_profile_for_location(location)
    setup = get_business_setup_status(
        organization=location.organization,
        business_id=location.business_id,
        location_id=location.id,
    )
    setup_ready = bool(setup["ready"])

    if not preview and not is_website_publicly_visible(profile=profile, setup_ready=setup_ready):
        # Distinguish unfinished vs missing without leaking details.
        if profile is None or not is_valid_template_key(getattr(profile, "template_key", "")):
            raise NotFound(detail="Business not found.")
        raise NotFound(detail="This website isn't available yet.")

    if profile is None or not is_valid_template_key(profile.template_key):
        raise NotFound(detail="Business not found.")

    quickcard = get_quickcard_for_location_public(location)
    business = location.business
    services = [
        serialize_public_service(service, location=location)
        for service in list_public_services(location=location)
    ]
    staff_rows = [
        serialize_public_staff(member, location=location)
        for member in list_public_staff(location=location)
    ]
    hours = provisional_opening_hours(location=location)

    logo_url = (quickcard.logo_url if quickcard and quickcard.logo_url else "") or (
        business.logo_url or ""
    )
    cover_url = (quickcard.cover_image_url if quickcard else "") or ""
    headline = (quickcard.headline if quickcard else "") or ""
    description = (quickcard.description if quickcard and quickcard.description else "") or (
        business.description or ""
    )
    phone = (quickcard.phone if quickcard and quickcard.phone else "") or (location.phone or "")
    whatsapp = (quickcard.whatsapp if quickcard and quickcard.whatsapp else "") or phone
    maps_url = (quickcard.google_maps_url if quickcard else "") or (
        profile.google_business_url if profile else ""
    )
    instagram = (quickcard.instagram_url if quickcard else "") or ""
    facebook = (quickcard.facebook_url if quickcard else "") or ""
    website_url = (quickcard.website_url if quickcard else "") or ""

    images = []
    if logo_url:
        images.append({"type": "logo", "url": logo_url, "alt": f"{business.name} logo"})
    if cover_url:
        images.append({"type": "cover", "url": cover_url, "alt": f"{business.name} cover"})

    booking_path = f"/book/{location.slug}"
    site_path = f"/site/{location.slug}"
    site_root = getattr(settings, "BOOKANYTHING_SITE_DOMAIN", "bookanything.in")
    from sites.provisioning_services import (
        internal_site_path,
        provisioned_public_url,
    )

    canonical_path = internal_site_path(profile.subdomain, location.slug)
    public_url = (
        provisioned_public_url(profile.subdomain)
        if profile.subdomain
        else f"{_public_app_base_url()}{site_path}"
    )

    return {
        "template": profile.template_key,
        "preview": preview,
        "published": is_website_publicly_visible(profile=profile, setup_ready=setup_ready),
        "business": {
            "name": business.name,
            "slug": business.slug,
            "category": VERTICAL_LABELS.get(business.vertical, business.vertical),
            "vertical": business.vertical,
            "description": business.description or "",
            "logo_url": logo_url or None,
        },
        "location": {
            "name": location.name,
            "slug": location.slug,
            "timezone": location.timezone,
            "address": _format_address(location) or None,
            "address_parts": {
                "line1": location.address_line1 or "",
                "line2": location.address_line2 or "",
                "city": location.city or "",
                "state": location.state or "",
                "postal_code": location.postal_code or "",
                "country": location.country or "",
            },
            "city": location.city or "",
            "phone": location.phone or "",
        },
        "hero": {
            "headline": headline or business.name,
            "tagline": description[:160]
            if description
            else f"Book an appointment at {business.name}",
            "description": description,
            "cover_image_url": cover_url or None,
        },
        "contact": {
            "phone": phone or None,
            "whatsapp": whatsapp or None,
            "email": location.email or None,
        },
        "social": {
            "website": website_url or None,
            "instagram": instagram or None,
            "facebook": facebook or None,
            "google_maps": maps_url or None,
        },
        "services": [
            {
                "id": row["id"],
                "slug": row["slug"],
                "name": row["name"],
                "description": row.get("description") or "",
                "duration_minutes": row["duration_minutes"],
                "price": row["price"],
                "currency": row["currency"],
            }
            for row in services
        ],
        "staff": [
            {
                "id": row["id"],
                "display_name": row["display_name"],
                "title": row.get("title") or "",
                "bio": row.get("bio") or "",
                "photo_url": row.get("photo_url") or None,
                "services": [
                    {"name": s["name"], "duration_minutes": s["duration_minutes"]}
                    for s in row.get("services") or []
                ],
            }
            for row in staff_rows
        ],
        "hours": hours,
        "images": images,
        "booking": {
            "path": booking_path,
            "url": booking_url_for_location(location),
        },
        "quickcard": (
            {
                "slug": quickcard.slug,
                "path": public_quickcard_path(quickcard.slug),
                "url": public_quickcard_url(quickcard.slug),
                "is_published": bool(quickcard.is_published),
            }
            if quickcard
            else None
        ),
        "site": {
            "path": canonical_path,
            "url": public_url,
            "subdomain": profile.subdomain or None,
            "subdomain_hostname": (
                f"{profile.subdomain}.{site_root}" if profile.subdomain else None
            ),
        },
        "seo": {
            "title": f"{business.name} — Book an Appointment",
            "description": description
            or f"Book online at {business.name}"
            + (f" in {location.city}" if location.city else "")
            + ".",
            "canonical_path": canonical_path,
            "canonical_url": public_url,
            "og_image": cover_url or logo_url or None,
        },
    }


def get_public_site_by_slug(slug: str) -> dict:
    location = resolve_site_location_by_slug(slug)
    return build_public_site_payload(location=location, preview=False)


def get_preview_site_for_business(
    *,
    organization,
    business_id,
    location_id,
) -> dict:
    from businesses.services import get_business_for_organization
    from locations.services import get_location_for_business

    business = get_business_for_organization(
        organization=organization,
        business_id=business_id,
    )
    location = get_location_for_business(
        organization=organization,
        business=business,
        location_id=location_id,
    )
    return build_public_site_payload(location=location, preview=True)
