"""QuickCard business logic — presentation over Location/catalog/staff."""

from __future__ import annotations

import re
from datetime import time
from io import BytesIO
from urllib.parse import urlparse

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from catalog.public_services import list_public_services, serialize_public_service
from locations.models import Location
from locations.public_services import serialize_public_location
from locations.services import get_location_for_business
from sites.models import QuickCard, suggest_quickcard_slug
from staff.models import StaffAvailability, Weekday
from staff.public_services import list_public_staff, serialize_public_staff

WEEKDAY_LABELS = {
    Weekday.MONDAY: "Monday",
    Weekday.TUESDAY: "Tuesday",
    Weekday.WEDNESDAY: "Wednesday",
    Weekday.THURSDAY: "Thursday",
    Weekday.FRIDAY: "Friday",
    Weekday.SATURDAY: "Saturday",
    Weekday.SUNDAY: "Sunday",
}


def _public_app_base_url() -> str:
    return (getattr(settings, "PUBLIC_APP_URL", "") or "http://localhost:3000").rstrip("/")


def public_quickcard_path(slug: str) -> str:
    return f"/q/{slug}"


def public_quickcard_url(slug: str) -> str:
    return f"{_public_app_base_url()}{public_quickcard_path(slug)}"


def booking_url_for_location(location: Location) -> str:
    return f"{_public_app_base_url()}/book/{location.slug}"


def public_https_url(value: str | None) -> str:
    """Return a customer-facing https URL, or empty when the value is unsafe."""
    raw = (value or "").strip()
    if not raw or len(raw) > 500:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        return ""
    lowered = raw.lower()
    if lowered.startswith(("javascript:", "data:", "file:")) or "token=" in lowered:
        return ""
    if "/book/manage/" in raw:
        return ""
    return raw


def public_whatsapp_url(number: str | None) -> str:
    digits = re.sub(r"\D", "", number or "")
    if len(digits) < 8 or len(digits) > 15:
        return ""
    return f"https://wa.me/{digits}"


def public_call_url(number: str | None) -> str:
    raw = (number or "").strip()
    if not re.fullmatch(r"\+?[0-9][0-9 \-()]{6,20}", raw):
        return ""
    tel = re.sub(r"[^\d+]", "", raw)
    if tel.count("+") > 1 or ("+" in tel and not tel.startswith("+")):
        return ""
    if len(re.sub(r"\D", "", tel)) < 8:
        return ""
    return f"tel:{tel}"


def get_quickcard_for_location(
    *,
    organization,
    business,
    location_id,
) -> QuickCard:
    location = get_location_for_business(
        organization=organization,
        business=business,
        location_id=location_id,
    )
    try:
        return QuickCard.objects.select_related(
            "location",
            "location__business",
            "business",
            "organization",
        ).get(location=location, organization=organization)
    except QuickCard.DoesNotExist as exc:
        raise NotFound(detail="QuickCard not found.") from exc


def _ensure_unique_slug(slug: str, *, exclude_id=None) -> str:
    candidate = slugify(slug)[:255]
    if not candidate:
        raise ValidationError({"slug": "Enter a valid slug."})
    qs = QuickCard.objects.filter(slug=candidate)
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    if qs.exists():
        raise ValidationError({"slug": "This QuickCard slug is already in use."})
    return candidate


@transaction.atomic
def create_quickcard(
    *,
    organization,
    business,
    location_id,
    actor,
    slug: str | None = None,
    headline: str = "",
    description: str = "",
    logo_url: str = "",
    cover_image_url: str = "",
    phone: str = "",
    whatsapp: str = "",
    website_url: str = "",
    google_maps_url: str = "",
    instagram_url: str = "",
    facebook_url: str = "",
    is_published: bool = False,
) -> QuickCard:
    location = get_location_for_business(
        organization=organization,
        business=business,
        location_id=location_id,
    )
    if QuickCard.objects.filter(location=location).exists():
        raise ValidationError({"location": "A QuickCard already exists for this location."})

    raw_slug = slug or suggest_quickcard_slug(
        location_name=location.name,
        location_slug=location.slug,
    )
    unique_slug = _ensure_unique_slug(raw_slug)

    card = QuickCard(
        organization=organization,
        business=business,
        location=location,
        slug=unique_slug,
        headline=headline or "",
        description=description or "",
        logo_url=logo_url or "",
        cover_image_url=cover_image_url or "",
        phone=phone or location.phone or "",
        whatsapp=whatsapp or location.phone or "",
        website_url=website_url or "",
        google_maps_url=google_maps_url or "",
        instagram_url=instagram_url or "",
        facebook_url=facebook_url or "",
        is_published=bool(is_published),
        published_at=timezone.now() if is_published else None,
        created_by=actor,
        updated_by=actor,
    )
    try:
        card.save()
    except IntegrityError as exc:
        raise ValidationError({"slug": "This QuickCard slug is already in use."}) from exc
    return card


@transaction.atomic
def update_quickcard(
    *,
    quickcard: QuickCard,
    actor,
    **fields,
) -> QuickCard:
    # Slug is stable after creation — reject changes.
    if "slug" in fields and fields["slug"] and fields["slug"] != quickcard.slug:
        raise ValidationError({"slug": "QuickCard slug cannot be changed after creation."})
    fields.pop("slug", None)

    allowed = {
        "headline",
        "description",
        "logo_url",
        "cover_image_url",
        "phone",
        "whatsapp",
        "website_url",
        "google_maps_url",
        "instagram_url",
        "facebook_url",
    }
    for key, value in fields.items():
        if key not in allowed:
            continue
        setattr(quickcard, key, value if value is not None else "")
    quickcard.updated_by = actor
    quickcard.save()
    return quickcard


@transaction.atomic
def publish_quickcard(*, quickcard: QuickCard, actor) -> QuickCard:
    quickcard.is_published = True
    if quickcard.published_at is None:
        quickcard.published_at = timezone.now()
    quickcard.updated_by = actor
    quickcard.save(update_fields=["is_published", "published_at", "updated_by", "updated_at"])
    return quickcard


@transaction.atomic
def unpublish_quickcard(*, quickcard: QuickCard, actor) -> QuickCard:
    quickcard.is_published = False
    quickcard.updated_by = actor
    quickcard.save(update_fields=["is_published", "updated_by", "updated_at"])
    return quickcard


def serialize_managed_quickcard(quickcard: QuickCard) -> dict:
    location = quickcard.location
    return {
        "id": str(quickcard.id),
        "location_id": str(location.id),
        "slug": quickcard.slug,
        "headline": quickcard.headline,
        "description": quickcard.description,
        "logo_url": quickcard.logo_url,
        "cover_image_url": quickcard.cover_image_url,
        "phone": quickcard.phone,
        "whatsapp": quickcard.whatsapp,
        "website_url": quickcard.website_url,
        "google_maps_url": quickcard.google_maps_url,
        "instagram_url": quickcard.instagram_url,
        "facebook_url": quickcard.facebook_url,
        "is_published": quickcard.is_published,
        "published_at": quickcard.published_at.isoformat() if quickcard.published_at else None,
        "public_path": public_quickcard_path(quickcard.slug),
        "public_url": public_quickcard_url(quickcard.slug),
        "booking_url": booking_url_for_location(location),
        "location": {
            "id": str(location.id),
            "name": location.name,
            "slug": location.slug,
            "timezone": location.timezone,
        },
        "created_at": quickcard.created_at.isoformat(),
        "updated_at": quickcard.updated_at.isoformat(),
    }


def _format_clock(value: time) -> str:
    return value.strftime("%H:%M")


def provisional_opening_hours(*, location: Location) -> list[dict]:
    """
    Aggregate StaffAvailability at the location as provisional bookable hours.
    Not LocationHours (not implemented yet).
    """
    rows = (
        StaffAvailability.objects.filter(
            organization=location.organization,
            location=location,
            staff_profile__is_active=True,
            staff_profile__is_bookable=True,
            staff_profile__deleted_at__isnull=True,
        )
        .values("weekday", "starts_at", "ends_at")
        .order_by("weekday", "starts_at")
    )
    by_day: dict[int, list[tuple[time, time]]] = {d: [] for d in range(7)}
    for row in rows:
        by_day[row["weekday"]].append((row["starts_at"], row["ends_at"]))

    result = []
    for day in range(7):
        intervals = by_day[day]
        if not intervals:
            result.append(
                {
                    "weekday": day,
                    "label": WEEKDAY_LABELS[day],
                    "closed": True,
                    "opens_at": None,
                    "closes_at": None,
                }
            )
            continue
        opens = min(i[0] for i in intervals)
        closes = max(i[1] for i in intervals)
        result.append(
            {
                "weekday": day,
                "label": WEEKDAY_LABELS[day],
                "closed": False,
                "opens_at": _format_clock(opens),
                "closes_at": _format_clock(closes),
            }
        )
    return result


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


def resolve_published_quickcard(slug: str) -> QuickCard:
    card = (
        QuickCard.objects.select_related(
            "location",
            "location__business",
            "business",
            "organization",
        )
        .filter(
            slug=slug,
            is_published=True,
            deleted_at__isnull=True,
            location__is_active=True,
            location__deleted_at__isnull=True,
            business__is_active=True,
            business__deleted_at__isnull=True,
        )
        .first()
    )
    if card is None:
        raise NotFound(detail="QuickCard not found.")
    return card


def _launch_public_links(location: Location) -> tuple[str, str]:
    from businesses.models import BusinessLaunchProfile

    profile = (
        BusinessLaunchProfile.objects.filter(
            organization_id=location.organization_id,
            business_id=location.business_id,
            location_id=location.id,
        )
        .only("google_business_url", "google_review_url")
        .first()
    )
    if profile is None:
        return "", ""
    return (
        public_https_url(profile.google_business_url),
        public_https_url(profile.google_review_url),
    )


def serialize_public_quickcard(quickcard: QuickCard) -> dict:
    location = quickcard.location
    business = location.business
    services = [
        serialize_public_service(service, location=location)
        for service in list_public_services(location=location)
    ]
    staff = [
        serialize_public_staff(member, location=location)
        for member in list_public_staff(location=location)
    ]
    location_public = serialize_public_location(location)
    logo = public_https_url(quickcard.logo_url) or public_https_url(business.logo_url)
    cover = public_https_url(quickcard.cover_image_url)
    phone = (location.phone or quickcard.phone or "").strip()
    whatsapp_number = (quickcard.whatsapp or quickcard.phone or location.phone or "").strip()
    maps_url, review_url = _launch_public_links(location)
    if not maps_url:
        maps_url = public_https_url(quickcard.google_maps_url)
    description = (
        quickcard.description or quickcard.headline or business.description or ""
    ).strip()
    title = f"{business.name} — Book now"
    return {
        "slug": quickcard.slug,
        "business": {
            "name": business.name,
            "slug": business.slug,
            "description": business.description or "",
            "address": _format_address(location),
            "timezone": location.timezone,
            "vertical": business.vertical,
            "logo": logo,
        },
        "location": {
            "name": location.name,
            "slug": location.slug,
            "timezone": location.timezone,
            "phone": phone,
            "email": (location.email or "").strip(),
            "address": location_public["address"],
            "maps_url": maps_url or None,
        },
        "quickcard": {
            "headline": quickcard.headline,
            "description": quickcard.description,
            "logo_url": logo,
            "cover_image_url": cover,
            "phone": phone,
            "whatsapp": whatsapp_number if public_whatsapp_url(whatsapp_number) else "",
            "website_url": public_https_url(quickcard.website_url),
            "google_maps_url": maps_url,
            "instagram_url": public_https_url(quickcard.instagram_url),
            "facebook_url": public_https_url(quickcard.facebook_url),
        },
        "services": services,
        "staff": staff,
        "hours": provisional_opening_hours(location=location),
        "reviews": None,
        "booking": {
            "location_slug": location.slug,
            "location_id": str(location.id),
            "booking_url": (
                f"{booking_url_for_location(location)}?source=quickcard&ref={quickcard.slug}"
            ),
            "booking_path": f"/book/{location.slug}?source=quickcard&ref={quickcard.slug}",
        },
        "actions": {
            "booking_url": f"/book/{location.slug}?source=quickcard&ref={quickcard.slug}",
            "whatsapp_url": public_whatsapp_url(whatsapp_number) or None,
            "call_url": public_call_url(phone) or None,
            "directions_url": maps_url or None,
            "review_url": review_url or None,
            "share_url": public_quickcard_url(quickcard.slug),
        },
        "seo": {
            "title": title,
            "description": (description or f"Book online at {business.name}.")[:300],
            "canonical_path": public_quickcard_path(quickcard.slug),
            "og_image": cover or logo or None,
        },
    }


def generate_quickcard_qr_png(*, slug: str) -> bytes:
    import qrcode

    url = public_quickcard_url(slug)
    if "/book/manage/" in url or "token=" in url.lower():
        raise PermissionDenied("Refusing to encode a private token URL.")
    qr = qrcode.QRCode(version=None, box_size=8, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
