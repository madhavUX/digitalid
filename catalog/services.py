from decimal import Decimal

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from rest_framework.exceptions import ValidationError

from businesses.services import get_business_for_organization
from catalog.models import Service, ServiceCategory, ServiceLocation
from locations.services import get_location_for_business


def _unique_slug(*, queryset, name: str, exclude_id=None, fallback: str) -> str:
    base = slugify(name) or fallback
    slug = base
    suffix = 1
    while True:
        qs = queryset.filter(slug=slug)
        if exclude_id is not None:
            qs = qs.exclude(pk=exclude_id)
        if not qs.exists():
            return slug
        slug = f"{base}-{suffix}"
        suffix += 1


def _normalize_currency(value: str | None) -> str:
    if value is None:
        return "INR"
    currency = value.strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValidationError({"currency": "Enter a valid ISO 4217 currency code."})
    return currency


def _validate_duration(value: int, field: str = "duration_minutes") -> int:
    if value is None or value < 1:
        raise ValidationError({field: "Duration must be at least 1 minute."})
    return value


def _validate_price(value, field: str = "price") -> Decimal:
    amount = Decimal(str(value))
    if amount < 0:
        raise ValidationError({field: "Price cannot be negative."})
    return amount


# --- ServiceCategory ---


def list_service_categories(*, organization, business):
    return ServiceCategory.objects.filter(
        organization=organization,
        business=business,
    ).order_by("display_order", "name")


def get_service_category_for_business(*, organization, business, category_id) -> ServiceCategory:
    return get_object_or_404(
        ServiceCategory,
        organization=organization,
        business=business,
        pk=category_id,
    )


@transaction.atomic
def create_service_category(
    *,
    organization,
    business_id,
    actor,
    name: str,
    slug: str | None = None,
    display_order: int = 0,
) -> ServiceCategory:
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
        else _unique_slug(
            queryset=ServiceCategory.objects.filter(business=business),
            name=name,
            fallback="category",
        )
    )
    if ServiceCategory.objects.filter(business=business, slug=resolved_slug).exists():
        raise ValidationError({"slug": "A category with this slug already exists."})

    return ServiceCategory.objects.create(
        organization=organization,
        business=business,
        name=name,
        slug=resolved_slug,
        display_order=display_order or 0,
        created_by=actor,
        updated_by=actor,
    )


@transaction.atomic
def update_service_category(*, category: ServiceCategory, actor, **fields) -> ServiceCategory:
    if "name" in fields and fields["name"] is not None:
        name = fields["name"].strip()
        if not name:
            raise ValidationError({"name": "This field may not be blank."})
        category.name = name

    if "slug" in fields and fields["slug"] is not None:
        slug = fields["slug"].strip()
        if not slug:
            raise ValidationError({"slug": "This field may not be blank."})
        if (
            ServiceCategory.objects.filter(business=category.business, slug=slug)
            .exclude(pk=category.pk)
            .exists()
        ):
            raise ValidationError({"slug": "A category with this slug already exists."})
        category.slug = slug

    if "display_order" in fields and fields["display_order"] is not None:
        category.display_order = fields["display_order"]

    category.updated_by = actor
    category.save()
    return category


@transaction.atomic
def soft_delete_service_category(*, category: ServiceCategory, actor) -> None:
    category.soft_delete(actor=actor)


# --- Service ---


def list_services(*, organization, business):
    return (
        Service.objects.filter(organization=organization, business=business)
        .select_related("category")
        .order_by("name")
    )


def get_service_for_business(*, organization, business, service_id) -> Service:
    return get_object_or_404(
        Service.objects.select_related("category"),
        organization=organization,
        business=business,
        pk=service_id,
    )


def _resolve_category(*, organization, business, category_id) -> ServiceCategory | None:
    if category_id is None:
        return None
    return get_service_category_for_business(
        organization=organization,
        business=business,
        category_id=category_id,
    )


@transaction.atomic
def create_service(
    *,
    organization,
    business_id,
    actor,
    name: str,
    duration_minutes: int,
    price,
    currency: str = "INR",
    slug: str | None = None,
    description: str = "",
    category_id=None,
    buffer_before_minutes: int = 0,
    buffer_after_minutes: int = 0,
    is_bookable_online: bool = True,
    is_active: bool = True,
) -> Service:
    business = get_business_for_organization(
        organization=organization,
        business_id=business_id,
    )
    name = name.strip()
    if not name:
        raise ValidationError({"name": "This field may not be blank."})

    duration_minutes = _validate_duration(duration_minutes)
    price = _validate_price(price)
    currency = _normalize_currency(currency)
    category = _resolve_category(
        organization=organization,
        business=business,
        category_id=category_id,
    )

    if buffer_before_minutes is not None and buffer_before_minutes < 0:
        raise ValidationError({"buffer_before_minutes": "Cannot be negative."})
    if buffer_after_minutes is not None and buffer_after_minutes < 0:
        raise ValidationError({"buffer_after_minutes": "Cannot be negative."})

    resolved_slug = (
        slug.strip()
        if slug
        else _unique_slug(
            queryset=Service.objects.filter(business=business),
            name=name,
            fallback="service",
        )
    )
    if Service.objects.filter(business=business, slug=resolved_slug).exists():
        raise ValidationError({"slug": "A service with this slug already exists."})

    return Service.objects.create(
        organization=organization,
        business=business,
        category=category,
        name=name,
        slug=resolved_slug,
        description=description or "",
        duration_minutes=duration_minutes,
        buffer_before_minutes=buffer_before_minutes or 0,
        buffer_after_minutes=buffer_after_minutes or 0,
        price=price,
        currency=currency,
        is_bookable_online=is_bookable_online,
        is_active=is_active,
        created_by=actor,
        updated_by=actor,
    )


@transaction.atomic
def update_service(*, service: Service, actor, **fields) -> Service:
    if "name" in fields and fields["name"] is not None:
        name = fields["name"].strip()
        if not name:
            raise ValidationError({"name": "This field may not be blank."})
        service.name = name

    if "slug" in fields and fields["slug"] is not None:
        slug = fields["slug"].strip()
        if not slug:
            raise ValidationError({"slug": "This field may not be blank."})
        if (
            Service.objects.filter(business=service.business, slug=slug)
            .exclude(pk=service.pk)
            .exists()
        ):
            raise ValidationError({"slug": "A service with this slug already exists."})
        service.slug = slug

    if "description" in fields and fields["description"] is not None:
        service.description = fields["description"]

    if "duration_minutes" in fields and fields["duration_minutes"] is not None:
        service.duration_minutes = _validate_duration(fields["duration_minutes"])

    if "buffer_before_minutes" in fields and fields["buffer_before_minutes"] is not None:
        if fields["buffer_before_minutes"] < 0:
            raise ValidationError({"buffer_before_minutes": "Cannot be negative."})
        service.buffer_before_minutes = fields["buffer_before_minutes"]

    if "buffer_after_minutes" in fields and fields["buffer_after_minutes"] is not None:
        if fields["buffer_after_minutes"] < 0:
            raise ValidationError({"buffer_after_minutes": "Cannot be negative."})
        service.buffer_after_minutes = fields["buffer_after_minutes"]

    if "price" in fields and fields["price"] is not None:
        service.price = _validate_price(fields["price"])

    if "currency" in fields and fields["currency"] is not None:
        service.currency = _normalize_currency(fields["currency"])

    if "is_bookable_online" in fields and fields["is_bookable_online"] is not None:
        service.is_bookable_online = fields["is_bookable_online"]

    if "is_active" in fields and fields["is_active"] is not None:
        service.is_active = fields["is_active"]

    if "category_id" in fields:
        service.category = _resolve_category(
            organization=service.organization,
            business=service.business,
            category_id=fields["category_id"],
        )

    service.updated_by = actor
    service.save()
    return service


@transaction.atomic
def soft_delete_service(*, service: Service, actor) -> None:
    ServiceLocation.objects.filter(service=service).delete()
    service.soft_delete(actor=actor)


# --- ServiceLocation ---


def list_service_locations(*, organization, service):
    return (
        ServiceLocation.objects.filter(organization=organization, service=service)
        .select_related("location", "service")
        .order_by("created_at")
    )


def get_service_location(*, organization, service, service_location_id) -> ServiceLocation:
    return get_object_or_404(
        ServiceLocation.objects.select_related("location", "service"),
        organization=organization,
        service=service,
        pk=service_location_id,
    )


@transaction.atomic
def assign_service_location(
    *,
    organization,
    business,
    service,
    actor,
    location_id,
    duration_minutes=None,
    price=None,
    currency: str = "",
) -> ServiceLocation:
    location = get_location_for_business(
        organization=organization,
        business=business,
        location_id=location_id,
    )

    if location.business_id != service.business_id:
        raise ValidationError(
            {"location_id": "Location must belong to the same business as the service."}
        )
    if location.organization_id != organization.id or service.organization_id != organization.id:
        raise ValidationError(
            {"detail": "Service and location must belong to the current organization."}
        )

    if ServiceLocation.objects.filter(service=service, location=location).exists():
        raise ValidationError({"location_id": "This service is already assigned to this location."})

    override_duration = None
    if duration_minutes is not None:
        override_duration = _validate_duration(duration_minutes)

    override_price = None
    override_currency = ""
    if price is not None:
        override_price = _validate_price(price)
        override_currency = _normalize_currency(currency or service.currency)

    return ServiceLocation.objects.create(
        organization=organization,
        service=service,
        location=location,
        duration_minutes=override_duration,
        price=override_price,
        currency=override_currency,
        created_by=actor,
        updated_by=actor,
    )


@transaction.atomic
def update_service_location(
    *, service_location: ServiceLocation, actor, **fields
) -> ServiceLocation:
    if "duration_minutes" in fields:
        value = fields["duration_minutes"]
        service_location.duration_minutes = None if value is None else _validate_duration(value)

    if "price" in fields:
        value = fields["price"]
        if value is None:
            service_location.price = None
            if "currency" not in fields:
                service_location.currency = ""
        else:
            service_location.price = _validate_price(value)
            if "currency" in fields and fields["currency"]:
                service_location.currency = _normalize_currency(fields["currency"])
            elif not service_location.currency:
                service_location.currency = service_location.service.currency

    if "currency" in fields and fields["currency"] is not None and "price" not in fields:
        if fields["currency"] == "":
            service_location.currency = ""
        else:
            service_location.currency = _normalize_currency(fields["currency"])

    service_location.updated_by = actor
    service_location.save()
    return service_location


@transaction.atomic
def remove_service_location(*, service_location: ServiceLocation) -> None:
    service_location.delete()
