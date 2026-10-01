from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from rest_framework.exceptions import ValidationError

from businesses.services import get_business_for_organization
from locations.models import Location


def generate_unique_location_slug(*, business, name: str, exclude_id=None) -> str:
    base = slugify(name) or "location"
    slug = base
    suffix = 1
    while True:
        qs = Location.objects.filter(business=business, slug=slug)
        if exclude_id is not None:
            qs = qs.exclude(pk=exclude_id)
        if not qs.exists():
            return slug
        slug = f"{base}-{suffix}"
        suffix += 1


def list_locations(*, organization, business):
    return Location.objects.filter(
        organization=organization,
        business=business,
    ).order_by("name")


def get_location_for_business(*, organization, business, location_id) -> Location:
    return get_object_or_404(
        Location,
        organization=organization,
        business=business,
        pk=location_id,
    )


@transaction.atomic
def create_location(
    *,
    organization,
    business_id,
    actor,
    name: str,
    timezone: str,
    slug: str | None = None,
    address_line1: str = "",
    address_line2: str = "",
    city: str = "",
    state: str = "",
    postal_code: str = "",
    country: str = "",
    latitude=None,
    longitude=None,
    phone: str = "",
    email: str = "",
    is_primary: bool = False,
    is_active: bool = True,
) -> Location:
    business = get_business_for_organization(
        organization=organization,
        business_id=business_id,
    )

    name = name.strip()
    if not name:
        raise ValidationError({"name": "This field may not be blank."})

    resolved_slug = (
        slug.strip()
        if slug
        else generate_unique_location_slug(
            business=business,
            name=name,
        )
    )
    if Location.objects.filter(business=business, slug=resolved_slug).exists():
        raise ValidationError({"slug": "A location with this slug already exists."})

    if is_primary:
        Location.objects.filter(business=business, is_primary=True).update(is_primary=False)
    elif not Location.objects.filter(business=business).exists():
        # First location for a business becomes primary by default.
        is_primary = True

    return Location.objects.create(
        organization=organization,
        business=business,
        name=name,
        slug=resolved_slug,
        address_line1=address_line1 or "",
        address_line2=address_line2 or "",
        city=city or "",
        state=state or "",
        postal_code=postal_code or "",
        country=(country or "").upper(),
        latitude=latitude,
        longitude=longitude,
        timezone=timezone,
        phone=phone or "",
        email=email or "",
        is_primary=is_primary,
        is_active=is_active,
        created_by=actor,
        updated_by=actor,
    )


@transaction.atomic
def update_location(*, location: Location, actor, **fields) -> Location:
    if "name" in fields and fields["name"] is not None:
        name = fields["name"].strip()
        if not name:
            raise ValidationError({"name": "This field may not be blank."})
        location.name = name

    if "slug" in fields and fields["slug"] is not None:
        slug = fields["slug"].strip()
        if not slug:
            raise ValidationError({"slug": "This field may not be blank."})
        if (
            Location.objects.filter(business=location.business, slug=slug)
            .exclude(pk=location.pk)
            .exists()
        ):
            raise ValidationError({"slug": "A location with this slug already exists."})
        location.slug = slug

    for field in (
        "address_line1",
        "address_line2",
        "city",
        "state",
        "postal_code",
        "timezone",
        "phone",
        "email",
        "latitude",
        "longitude",
        "is_active",
    ):
        if field in fields and fields[field] is not None:
            setattr(location, field, fields[field])

    if "country" in fields and fields["country"] is not None:
        location.country = fields["country"].upper()

    if "is_primary" in fields and fields["is_primary"] is not None:
        if fields["is_primary"]:
            Location.objects.filter(
                business=location.business,
                is_primary=True,
            ).exclude(pk=location.pk).update(is_primary=False)
            location.is_primary = True
        else:
            location.is_primary = False

    location.updated_by = actor
    location.save()
    return location


@transaction.atomic
def soft_delete_location(*, location: Location, actor) -> None:
    location.soft_delete(actor=actor)
