"""Public catalog listing for a resolved location — reuses booking pricing helpers."""

from __future__ import annotations

import uuid

from django.db.models import Prefetch
from rest_framework.exceptions import NotFound

from booking.services import resolve_effective_pricing
from catalog.models import Service, ServiceCategory, ServiceLocation
from locations.models import Location


def _public_services_queryset(location: Location):
    return (
        Service.objects.filter(
            organization=location.organization,
            business=location.business,
            is_active=True,
            is_bookable_online=True,
            service_locations__location=location,
        )
        .select_related("category")
        .prefetch_related(
            Prefetch(
                "service_locations",
                queryset=ServiceLocation.objects.filter(location=location),
                to_attr="at_this_location",
            )
        )
        .distinct()
        .order_by("name")
    )


def _effective_for(service: Service, location: Location):
    rows = getattr(service, "at_this_location", None)
    if rows:
        service_location = rows[0]
    else:
        service_location = ServiceLocation.objects.filter(
            organization=location.organization,
            service=service,
            location=location,
        ).first()
        if service_location is None:
            raise NotFound(detail="Service not found.")
    return resolve_effective_pricing(
        service=service,
        service_location=service_location,
        staff_service=None,
    )


def serialize_public_service(service: Service, *, location: Location) -> dict:
    pricing = _effective_for(service, location)
    category = service.category
    return {
        "id": str(service.id),
        "slug": service.slug,
        "name": service.name,
        "description": service.description or "",
        "duration_minutes": pricing.duration_minutes,
        "price": str(pricing.price),
        "currency": pricing.currency,
        "is_bookable_online": service.is_bookable_online,
        "category": (
            {
                "slug": category.slug,
                "name": category.name,
            }
            if category is not None
            else None
        ),
    }


def list_public_services(*, location: Location):
    return _public_services_queryset(location)


def get_public_service(*, location: Location, service_identifier: str) -> Service:
    identifier = (service_identifier or "").strip()
    if not identifier:
        raise NotFound(detail="Service not found.")

    qs = _public_services_queryset(location)
    service = qs.filter(slug=identifier).first()
    if service is not None:
        return service

    try:
        uuid.UUID(identifier)
    except (ValueError, TypeError, AttributeError):
        raise NotFound(detail="Service not found.") from None

    service = qs.filter(pk=identifier).first()
    if service is not None:
        return service

    raise NotFound(detail="Service not found.")


def list_public_categories(*, location: Location):
    return (
        ServiceCategory.objects.filter(
            organization=location.organization,
            business=location.business,
            services__is_active=True,
            services__is_bookable_online=True,
            services__deleted_at__isnull=True,
            services__service_locations__location=location,
        )
        .distinct()
        .order_by("display_order", "name")
    )


def serialize_public_category(category: ServiceCategory) -> dict:
    return {
        "slug": category.slug,
        "name": category.name,
        "display_order": category.display_order,
    }
