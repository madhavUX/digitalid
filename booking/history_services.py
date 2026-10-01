"""Guest booking history + Book Again — scoped by manage token → customer."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Prefetch, Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from booking.manage_tokens import resolve_appointment_for_manage_token
from booking.models import Appointment, AppointmentItem, AppointmentStatus
from booking.public_services import PublicBookingError, _raise
from booking.services import get_service_location_for_booking
from catalog.models import Service
from staff.models import StaffAvailability, StaffProfile, StaffService

HISTORY_CATEGORIES = frozenset({"upcoming", "past", "cancelled"})

ACTIVE_UPCOMING_STATUSES = frozenset(
    {
        AppointmentStatus.PENDING,
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.CHECKED_IN,
    }
)


def _resolve_scope_appointment(*, raw_token: str) -> Appointment:
    appointment = resolve_appointment_for_manage_token(raw_token)
    if appointment is None:
        _raise(
            "BOOKING_NOT_FOUND",
            "This booking link is invalid or has expired.",
            status_code=404,
        )
    return appointment


def max_history_page_size() -> int:
    return int(getattr(settings, "MAX_PUBLIC_BOOKING_HISTORY_PAGE_SIZE", 50) or 50)


def default_history_page_size() -> int:
    return min(20, max_history_page_size())


def _service_currently_bookable(*, appointment: Appointment) -> bool:
    item = appointment.items.first()
    if item is None or item.service_id is None:
        return False
    service = item.service
    if service is None:
        return False
    if service.deleted_at is not None or not service.is_active or not service.is_bookable_online:
        return False
    location = appointment.location
    if location.deleted_at is not None or not location.is_active:
        return False
    try:
        get_service_location_for_booking(
            organization=location.organization,
            service=service,
            location=location,
        )
    except ValidationError:
        return False
    return True


def _staff_eligible_for_service(
    *,
    location,
    service: Service,
    staff: StaffProfile,
) -> bool:
    if staff.deleted_at is not None or not staff.is_active or not staff.is_bookable:
        return False
    if staff.organization_id != location.organization_id:
        return False
    if staff.business_id != location.business_id:
        return False
    if not StaffService.objects.filter(
        organization=location.organization,
        staff_profile=staff,
        service=service,
    ).exists():
        return False
    if not StaffAvailability.objects.filter(
        organization=location.organization,
        staff_profile=staff,
        location=location,
    ).exists():
        return False
    return True


def categorize_appointment(appointment: Appointment, *, now: datetime) -> str:
    if appointment.status == AppointmentStatus.CANCELLED:
        return "cancelled"
    if appointment.status in (AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW):
        return "past"
    if appointment.status in ACTIVE_UPCOMING_STATUSES and appointment.starts_at > now:
        return "upcoming"
    return "past"


def serialize_history_booking(appointment: Appointment, *, now: datetime) -> dict:
    item = appointment.items.first()
    tz = ZoneInfo(appointment.location.timezone)
    can_book_again = _service_currently_bookable(appointment=appointment)
    return {
        "public_reference": appointment.public_reference,
        "status": appointment.status,
        "category": categorize_appointment(appointment, now=now),
        "location": {
            "name": appointment.location.name,
            "slug": appointment.location.slug,
        },
        "service": {
            "name": item.service_name if item else "",
        },
        "staff": {
            "name": appointment.staff_profile.display_name,
        },
        "starts_at": appointment.starts_at.astimezone(tz).isoformat(),
        "ends_at": appointment.ends_at.astimezone(tz).isoformat(),
        "can_book_again": can_book_again,
        "is_regular_booking": appointment.booking_plan_id is not None,
    }


def _history_base_queryset(*, customer_id):
    return (
        Appointment.objects.filter(customer_id=customer_id, deleted_at__isnull=True)
        .select_related(
            "location",
            "staff_profile",
            "customer",
        )
        .prefetch_related(
            Prefetch(
                "items",
                queryset=AppointmentItem.objects.select_related("service"),
            )
        )
    )


def _category_filter(category: str, *, now: datetime) -> Q:
    if category == "cancelled":
        return Q(status=AppointmentStatus.CANCELLED)
    if category == "upcoming":
        return Q(status__in=ACTIVE_UPCOMING_STATUSES, starts_at__gt=now)
    # past: completed, no-show, or still "active" but start time has passed
    return Q(status__in=[AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW]) | Q(
        status__in=ACTIVE_UPCOMING_STATUSES,
        starts_at__lte=now,
    )


def list_guest_booking_history(
    *,
    raw_token: str,
    category: str = "upcoming",
    limit: int | None = None,
    offset: int = 0,
    now: datetime | None = None,
) -> dict:
    """
    History scoped to the customer on the appointment identified by the manage token.

    Does not accept phone/email/customer_id from the client.
    """
    category = (category or "upcoming").strip().lower()
    if category not in HISTORY_CATEGORIES:
        raise PublicBookingError(
            detail={"category": "Must be upcoming, past, or cancelled."},
            code="INVALID_CATEGORY",
            status_code=400,
        )

    scope = _resolve_scope_appointment(raw_token=raw_token)
    clock = now or timezone.now()
    if timezone.is_naive(clock):
        clock = timezone.make_aware(clock, timezone.utc)

    max_size = max_history_page_size()
    page_size = default_history_page_size() if limit is None else int(limit)
    if page_size < 1:
        page_size = default_history_page_size()
    page_size = min(page_size, max_size)
    offset = max(0, int(offset or 0))

    qs = _history_base_queryset(customer_id=scope.customer_id).filter(
        _category_filter(category, now=clock)
    )
    if category == "upcoming":
        qs = qs.order_by("starts_at", "id")
    else:
        qs = qs.order_by("-starts_at", "-id")

    total = qs.count()
    page = list(qs[offset : offset + page_size])
    results = [serialize_history_booking(a, now=clock) for a in page]
    return {
        "category": category,
        "count": total,
        "limit": page_size,
        "offset": offset,
        "scope_public_reference": scope.public_reference,
        "results": results,
    }


def get_book_again_prefill(*, raw_token: str, public_reference: str) -> dict:
    """
    Return safe funnel prefill for a history appointment in the token's customer scope.

    Does not create an appointment. Bridge UUIDs match existing public booking APIs.
    """
    scope = _resolve_scope_appointment(raw_token=raw_token)
    reference = (public_reference or "").strip()
    appointment = (
        Appointment.objects.filter(
            customer_id=scope.customer_id,
            public_reference=reference,
            deleted_at__isnull=True,
        )
        .select_related("location", "staff_profile")
        .prefetch_related(
            Prefetch(
                "items",
                queryset=AppointmentItem.objects.select_related("service"),
            )
        )
        .first()
    )
    if appointment is None:
        _raise(
            "BOOKING_NOT_FOUND",
            "This booking link is invalid or has expired.",
            status_code=404,
        )

    location = appointment.location
    item = appointment.items.first()
    location_payload = {
        "id": str(location.id),
        "slug": location.slug,
        "name": location.name,
    }

    if item is None or item.service_id is None:
        return {
            "available": False,
            "reason": "SERVICE_UNAVAILABLE",
            "message": "This service is no longer available to book online.",
            "location": {"slug": location.slug, "name": location.name},
        }

    service = item.service
    if not _service_currently_bookable(appointment=appointment):
        return {
            "available": False,
            "reason": "SERVICE_UNAVAILABLE",
            "message": "This service is no longer available to book online.",
            "location": {"slug": location.slug, "name": location.name},
            "service": {"name": item.service_name, "available": False},
        }

    staff = appointment.staff_profile
    staff_available = _staff_eligible_for_service(
        location=location,
        service=service,
        staff=staff,
    )
    staff_payload = {
        "id": str(staff.id),
        "name": staff.display_name,
        "available": staff_available,
    }
    return {
        "available": True,
        "location": location_payload,
        "service": {
            "id": str(service.id),
            "name": service.name,
            "available": True,
        },
        "staff": staff_payload,
        "prefill": {
            "location_id": str(location.id),
            "service_id": str(service.id),
            # Prefer original staff when eligible; otherwise Any staff (null).
            "staff_id": str(staff.id) if staff_available else None,
        },
    }
