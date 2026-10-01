"""Business setup readiness + dashboard summary (OWNER/MANAGER)."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Prefetch
from django.utils import timezone
from rest_framework.exceptions import NotFound

from booking.models import (
    OCCUPYING_STATUSES,
    Appointment,
    AppointmentItem,
    AppointmentStatus,
    BookingPlan,
    BookingPlanStatus,
)
from businesses.services import get_business_for_organization
from catalog.models import ServiceLocation
from locations.models import Location
from locations.services import get_location_for_business
from sites.models import QuickCard
from sites.services import booking_url_for_location, public_quickcard_path, public_quickcard_url
from staff.models import StaffAvailability, StaffProfile, StaffService

SETUP_STEP_KEYS = (
    "business",
    "location",
    "services",
    "staff",
    "availability",
    "quickcard",
    "publish",
)

BLOCKING_MESSAGES = {
    "business": "Add a business name.",
    "location": "Add at least one location.",
    "services": "Add at least one active bookable service at this location.",
    "staff": "Add at least one active bookable staff member.",
    "availability": "Configure staff availability for at least one staff member.",
    "quickcard": "Create a QuickCard for this location.",
    "publish": "Publish your QuickCard to go live.",
}


def resolve_dashboard_location(
    *,
    organization,
    business,
    location_id=None,
) -> Location:
    if location_id:
        return get_location_for_business(
            organization=organization,
            business=business,
            location_id=location_id,
        )
    location = (
        Location.objects.filter(
            organization=organization,
            business=business,
            is_active=True,
        )
        .order_by("-is_primary", "name")
        .first()
    )
    if location is None:
        raise NotFound(detail="No location found for this business.")
    return location


def get_business_setup_status(
    *,
    organization,
    business_id,
    location_id=None,
) -> dict:
    business = get_business_for_organization(
        organization=organization,
        business_id=business_id,
    )
    locations = list(
        Location.objects.filter(
            organization=organization,
            business=business,
            is_active=True,
        ).order_by("-is_primary", "name")
    )
    location = None
    if location_id:
        location = get_location_for_business(
            organization=organization,
            business=business,
            location_id=location_id,
        )
    elif locations:
        location = locations[0]

    has_business = bool(business.name and business.name.strip())
    has_location = location is not None

    has_services = False
    has_staff = False
    has_staff_services = False
    has_availability = False
    has_quickcard = False
    is_published = False
    quickcard_slug = None

    if location is not None:
        service_id_list = list(
            ServiceLocation.objects.filter(
                organization=organization,
                location=location,
                service__is_active=True,
                service__is_bookable_online=True,
                service__deleted_at__isnull=True,
            ).values_list("service_id", flat=True)
        )
        has_services = len(service_id_list) > 0

        staff_qs = StaffProfile.objects.filter(
            organization=organization,
            business=business,
            location=location,
            is_active=True,
            is_bookable=True,
            deleted_at__isnull=True,
        )
        has_staff = staff_qs.exists()

        if has_staff and has_services:
            has_staff_services = StaffService.objects.filter(
                organization=organization,
                staff_profile__in=staff_qs,
                service_id__in=service_id_list,
            ).exists()

        if has_staff:
            has_availability = StaffAvailability.objects.filter(
                organization=organization,
                location=location,
                staff_profile__in=staff_qs,
            ).exists()

        quickcard = (
            QuickCard.objects.filter(
                organization=organization,
                business=business,
                location=location,
                deleted_at__isnull=True,
            )
            .only("slug", "is_published")
            .first()
        )
        if quickcard is not None:
            has_quickcard = True
            is_published = bool(quickcard.is_published)
            quickcard_slug = quickcard.slug

    # Staff step requires staff + at least one service assignment when services exist
    staff_step_ok = has_staff and (has_staff_services if has_services else False)

    steps = {
        "business": has_business,
        "location": has_location,
        "services": has_services,
        "staff": staff_step_ok,
        "availability": has_availability,
        "quickcard": has_quickcard,
        "publish": is_published,
    }
    completed = sum(1 for key in SETUP_STEP_KEYS if steps[key])
    progress = int(round((completed / len(SETUP_STEP_KEYS)) * 100))
    ready = all(steps.values())
    blocking = [BLOCKING_MESSAGES[key] for key in SETUP_STEP_KEYS if not steps[key]]

    return {
        "ready": ready,
        "progress": progress,
        "completed_steps": completed,
        "total_steps": len(SETUP_STEP_KEYS),
        "steps": steps,
        "blocking_reasons": blocking,
        "business": {
            "id": str(business.id),
            "name": business.name,
            "vertical": business.vertical,
        },
        "location": (
            {
                "id": str(location.id),
                "name": location.name,
                "slug": location.slug,
                "timezone": location.timezone,
            }
            if location
            else None
        ),
        "locations": [
            {
                "id": str(row.id),
                "name": row.name,
                "slug": row.slug,
                "timezone": row.timezone,
                "is_primary": row.is_primary,
            }
            for row in locations
        ],
        "quickcard": (
            {
                "slug": quickcard_slug,
                "is_published": is_published,
                "public_path": public_quickcard_path(quickcard_slug) if quickcard_slug else None,
                "public_url": public_quickcard_url(quickcard_slug) if quickcard_slug else None,
            }
            if has_quickcard
            else None
        ),
        "booking_path": f"/book/{location.slug}" if location else None,
        "booking_url": booking_url_for_location(location) if location else None,
    }


def _local_day_bounds(*, tz_name: str, local_day) -> tuple[datetime, datetime]:
    tz = ZoneInfo(tz_name)
    start = datetime.combine(local_day, time.min, tzinfo=tz).astimezone(UTC)
    end = datetime.combine(local_day, time.max, tzinfo=tz).astimezone(UTC)
    return start, end


def get_business_dashboard(
    *,
    organization,
    business_id,
    location_id=None,
    now: datetime | None = None,
) -> dict:
    business = get_business_for_organization(
        organization=organization,
        business_id=business_id,
    )
    setup = get_business_setup_status(
        organization=organization,
        business_id=business_id,
        location_id=location_id,
    )
    if setup["location"] is None:
        return {
            "business": setup["business"],
            "location": None,
            "locations": setup["locations"],
            "setup": {
                "ready": setup["ready"],
                "progress": setup["progress"],
                "completed_steps": setup["completed_steps"],
                "total_steps": setup["total_steps"],
                "blocking_reasons": setup["blocking_reasons"],
                "steps": setup["steps"],
            },
            "launch": None,
            "today": {"bookings": 0, "upcoming": 0, "regular_bookings": 0},
            "appointments": [],
            "quickcard": setup["quickcard"],
            "booking_path": None,
            "booking_url": None,
        }

    location = get_location_for_business(
        organization=organization,
        business=business,
        location_id=setup["location"]["id"],
    )
    clock = now or timezone.now()
    if timezone.is_naive(clock):
        clock = timezone.make_aware(clock, UTC)
    local_day = clock.astimezone(ZoneInfo(location.timezone)).date()
    day_start, day_end = _local_day_bounds(tz_name=location.timezone, local_day=local_day)

    base_appts = Appointment.objects.filter(
        organization=organization,
        business=business,
        location=location,
        deleted_at__isnull=True,
    )

    today_count = (
        base_appts.filter(
            starts_at__gte=day_start,
            starts_at__lte=day_end,
        )
        .exclude(status=AppointmentStatus.CANCELLED)
        .count()
    )

    upcoming_count = base_appts.filter(
        status__in=list(OCCUPYING_STATUSES),
        starts_at__gte=clock,
        starts_at__lte=clock + timedelta(days=14),
    ).count()

    regular_count = BookingPlan.objects.filter(
        organization=organization,
        business=business,
        location=location,
        status=BookingPlanStatus.ACTIVE,
        deleted_at__isnull=True,
    ).count()

    today_appts = (
        base_appts.filter(starts_at__gte=day_start, starts_at__lte=day_end)
        .exclude(status=AppointmentStatus.CANCELLED)
        .select_related("customer", "staff_profile")
        .prefetch_related(
            Prefetch(
                "items",
                queryset=AppointmentItem.objects.only(
                    "appointment_id",
                    "service_name",
                ),
            )
        )
        .order_by("starts_at")[:50]
    )

    tz = ZoneInfo(location.timezone)
    appointments = []
    for appt in today_appts:
        item = appt.items.all()[0] if appt.items.all() else None
        local_start = appt.starts_at.astimezone(tz)
        appointments.append(
            {
                "public_reference": appt.public_reference,
                "starts_at": local_start.isoformat(),
                "ends_at": appt.ends_at.astimezone(tz).isoformat(),
                "time_label": local_start.strftime("%H:%M"),
                "customer_name": appt.customer.full_name,
                "service_name": item.service_name if item else "",
                "staff_name": appt.staff_profile.display_name,
                "status": appt.status,
                "id": str(appt.id),
            }
        )

    from businesses.launch_services import get_business_launch_status

    launch = get_business_launch_status(
        organization=organization,
        business_id=business_id,
        location_id=str(location.id),
    )

    return {
        "business": setup["business"],
        "location": setup["location"],
        "locations": setup["locations"],
        "setup": {
            "ready": setup["ready"],
            "progress": setup["progress"],
            "completed_steps": setup["completed_steps"],
            "total_steps": setup["total_steps"],
            "blocking_reasons": setup["blocking_reasons"],
            "steps": setup["steps"],
        },
        "launch": {
            "ready": launch["ready"],
            "progress": launch["progress"],
            "launch_status": launch["launch_status"],
            "remaining_blocking": launch["remaining_blocking"],
            "checklist": launch["checklist"],
            "blocking_reasons": launch["blocking_reasons"],
            "template": launch["template"],
            "domain": launch["domain"],
            "whatsapp": launch["whatsapp"],
            "website": launch["website"],
            "quickcard": launch["quickcard"],
            "booking": launch["booking"],
            "profile": launch["profile"],
        },
        "today": {
            "bookings": today_count,
            "upcoming": upcoming_count,
            "regular_bookings": regular_count,
            "local_date": local_day.isoformat(),
        },
        "appointments": appointments,
        "quickcard": setup["quickcard"],
        "booking_path": setup["booking_path"],
        "booking_url": setup["booking_url"],
    }
