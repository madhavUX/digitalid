"""Public location resolution and customer-safe location payloads."""

from __future__ import annotations

from rest_framework.exceptions import NotFound

from locations.models import Location


def resolve_public_location_by_slug(slug: str) -> Location:
    """Resolve the public location selector to exactly one active location.

    ``Location.slug`` is unique per business in the schema. For public URLs we
    require an unambiguous match among live, active locations under an active
    business. Zero or multiple matches → 404 (no existence leak / no ambiguity).
    """
    cleaned = (slug or "").strip()
    if not cleaned:
        raise NotFound(detail="Location not found.")

    matches = list(
        Location.objects.select_related("business", "organization").filter(
            slug=cleaned,
            is_active=True,
            business__is_active=True,
            business__deleted_at__isnull=True,
        )[:2]
    )
    if len(matches) != 1:
        raise NotFound(detail="Location not found.")
    return matches[0]


def serialize_public_location(location: Location) -> dict:
    business = location.business
    return {
        "slug": location.slug,
        "name": location.name,
        "timezone": location.timezone,
        "phone": location.phone or "",
        "email": location.email or "",
        "address": {
            "line1": location.address_line1 or "",
            "line2": location.address_line2 or "",
            "city": location.city or "",
            "state": location.state or "",
            "postal_code": location.postal_code or "",
            "country": location.country or "",
        },
        "business": {
            "name": business.name,
            "slug": business.slug,
            "vertical": business.vertical,
            "description": business.description or "",
            "logo_url": business.logo_url or "",
        },
        # UUID retained for compatibility with /public/booking/* (location_id).
        "id": str(location.id),
    }
