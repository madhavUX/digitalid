"""Public staff discovery for a resolved location."""

from __future__ import annotations

from django.db.models import Prefetch

from booking.services import resolve_effective_pricing
from catalog.models import Service, ServiceLocation
from locations.models import Location
from staff.models import StaffProfile, StaffService


def _location_bookable_services_qs(location: Location):
    return Service.objects.filter(
        organization=location.organization,
        business=location.business,
        is_active=True,
        is_bookable_online=True,
        deleted_at__isnull=True,
        service_locations__location=location,
    )


def list_public_staff(*, location: Location):
    """Staff who can participate in online booking at this location.

    Association follows booking eligibility: recurring availability at the
    location (primary ``StaffProfile.location`` alone is not enough). Staff
    must also have ≥1 active online-bookable service offered at the location.
    """
    bookable_service_ids = _location_bookable_services_qs(location).values("id")

    staff_services_qs = (
        StaffService.objects.filter(
            organization=location.organization,
            service_id__in=bookable_service_ids,
            service__is_active=True,
            service__is_bookable_online=True,
            service__deleted_at__isnull=True,
        )
        .select_related("service", "service__category")
        .prefetch_related(
            Prefetch(
                "service__service_locations",
                queryset=ServiceLocation.objects.filter(location=location),
                to_attr="at_this_location",
            )
        )
        .order_by("service__name")
    )

    return (
        StaffProfile.objects.filter(
            organization=location.organization,
            business=location.business,
            is_active=True,
            is_bookable=True,
            availabilities__location=location,
            staff_services__service_id__in=bookable_service_ids,
        )
        .distinct()
        .prefetch_related(
            Prefetch(
                "staff_services",
                queryset=staff_services_qs,
                to_attr="public_staff_services",
            )
        )
        .order_by("display_name", "id")
    )


def serialize_public_staff(staff: StaffProfile, *, location: Location) -> dict:
    services = []
    for staff_service in getattr(staff, "public_staff_services", []):
        service = staff_service.service
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
                continue
        pricing = resolve_effective_pricing(
            service=service,
            service_location=service_location,
            staff_service=staff_service,
        )
        services.append(
            {
                "id": str(service.id),
                "slug": service.slug,
                "name": service.name,
                "duration_minutes": pricing.duration_minutes,
                "price": str(pricing.price),
                "currency": pricing.currency,
            }
        )

    return {
        # UUID bridge for /public/booking/* staff_id.
        "id": str(staff.id),
        "display_name": staff.display_name,
        "title": staff.title or "",
        "bio": staff.bio or "",
        "photo_url": staff.photo_url or "",
        "services": services,
    }
