"""Slot calculation and appointment lifecycle services."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from booking.events import (
    AppointmentBooked,
    AppointmentCancelled,
    AppointmentCompleted,
    AppointmentConfirmed,
    AppointmentCreated,
    AppointmentRescheduled,
    emit,
)
from booking.models import (
    ALLOWED_STATUS_TRANSITIONS,
    OCCUPYING_STATUSES,
    Appointment,
    AppointmentItem,
    AppointmentSource,
    AppointmentStatus,
    generate_public_reference,
)
from businesses.services import get_business_for_organization
from catalog.models import Service, ServiceLocation
from catalog.services import get_service_for_business
from customers.services import get_customer_for_business
from locations.services import get_location_for_business
from staff.models import StaffAvailability, StaffProfile, StaffService, StaffTimeOff

SLOT_GRID_MINUTES = 15


class AppointmentConflict(APIException):
    status_code = 409
    default_detail = "This time overlaps an existing appointment for the staff member."
    default_code = "appointment_conflict"


@dataclass(frozen=True)
class EffectiveServicePricing:
    duration_minutes: int
    buffer_before_minutes: int
    buffer_after_minutes: int
    price: Decimal
    currency: str
    service_name: str


@dataclass(frozen=True)
class TimeInterval:
    start: datetime
    end: datetime

    def overlaps(self, other: TimeInterval) -> bool:
        return self.start < other.end and other.start < self.end

    def contains(self, other: TimeInterval) -> bool:
        return self.start <= other.start and other.end <= self.end


def _ensure_aware(dt: datetime) -> datetime:
    if timezone.is_naive(dt):
        raise ValidationError({"starts_at": "Naive datetimes are not allowed."})
    return dt


def _local_zone(location) -> ZoneInfo:
    return ZoneInfo(location.timezone)


def _local_day_bounds_utc(local_day: date, tz: ZoneInfo) -> TimeInterval:
    start_local = datetime.combine(local_day, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return TimeInterval(
        start_local.astimezone(UTC),
        end_local.astimezone(UTC),
    )


def _subtract_intervals(
    base: list[TimeInterval], blockers: list[TimeInterval]
) -> list[TimeInterval]:
    result = list(base)
    for blocker in blockers:
        next_result: list[TimeInterval] = []
        for interval in result:
            if not interval.overlaps(blocker):
                next_result.append(interval)
                continue
            if interval.start < blocker.start:
                next_result.append(TimeInterval(interval.start, blocker.start))
            if blocker.end < interval.end:
                next_result.append(TimeInterval(blocker.end, interval.end))
        result = [i for i in next_result if i.start < i.end]
    return result


def get_service_location_for_booking(*, organization, service, location) -> ServiceLocation:
    service_location = ServiceLocation.objects.filter(
        organization=organization,
        service=service,
        location=location,
    ).first()
    if service_location is None:
        raise ValidationError(
            {"service_id": "This service is not offered at the selected location."}
        )
    return service_location


def resolve_effective_pricing(
    *,
    service: Service,
    service_location: ServiceLocation,
    staff_service: StaffService | None,
) -> EffectiveServicePricing:
    duration = service.duration_minutes
    if service_location.duration_minutes is not None:
        duration = service_location.duration_minutes
    if staff_service is not None and staff_service.duration_minutes is not None:
        duration = staff_service.duration_minutes

    price = service.price
    currency = service.currency or "INR"
    if service_location.price is not None:
        price = service_location.price
    if service_location.currency:
        currency = service_location.currency
    if staff_service is not None:
        if staff_service.price is not None:
            price = staff_service.price
        if staff_service.currency:
            currency = staff_service.currency

    return EffectiveServicePricing(
        duration_minutes=duration,
        buffer_before_minutes=service.buffer_before_minutes,
        buffer_after_minutes=service.buffer_after_minutes,
        price=price,
        currency=currency.upper(),
        service_name=service.name,
    )


def _get_staff_service(*, organization, staff_profile, service) -> StaffService:
    staff_service = StaffService.objects.filter(
        organization=organization,
        staff_profile=staff_profile,
        service=service,
    ).first()
    if staff_service is None:
        raise ValidationError({"staff_id": "This staff member does not provide the service."})
    return staff_service


def list_eligible_staff(
    *,
    organization,
    business,
    location,
    service: Service,
    staff_id=None,
) -> list[StaffProfile]:
    qs = (
        StaffProfile.objects.filter(
            organization=organization,
            business=business,
            is_active=True,
            is_bookable=True,
            staff_services__service=service,
            availabilities__location=location,
        )
        .distinct()
        .order_by("id")
    )
    if staff_id is not None:
        qs = qs.filter(pk=staff_id)
        staff = qs.first()
        if staff is None:
            raise ValidationError(
                {
                    "staff_id": (
                        "Staff is not eligible for this service/location "
                        "(inactive, not bookable, missing capability, or no availability)."
                    )
                }
            )
        return [staff]
    return list(qs)


def _availability_intervals_utc(
    *,
    staff: StaffProfile,
    location,
    local_day: date,
    tz: ZoneInfo,
) -> list[TimeInterval]:
    weekday = local_day.weekday()  # Monday=0 matches Weekday choices
    rows = StaffAvailability.objects.filter(
        staff_profile=staff,
        location=location,
        weekday=weekday,
    ).order_by("starts_at")
    intervals: list[TimeInterval] = []
    for row in rows:
        start_local = datetime.combine(local_day, row.starts_at, tzinfo=tz)
        end_local = datetime.combine(local_day, row.ends_at, tzinfo=tz)
        if end_local <= start_local:
            continue
        intervals.append(TimeInterval(start_local.astimezone(UTC), end_local.astimezone(UTC)))
    return intervals


def _time_off_blockers(*, staff: StaffProfile, day_bounds: TimeInterval) -> list[TimeInterval]:
    rows = StaffTimeOff.objects.filter(
        staff_profile=staff,
        starts_at__lt=day_bounds.end,
        ends_at__gt=day_bounds.start,
    )
    return [TimeInterval(row.starts_at, row.ends_at) for row in rows]


def _appointment_blockers(
    *,
    staff: StaffProfile,
    day_bounds: TimeInterval,
    exclude_appointment_id=None,
) -> list[TimeInterval]:
    qs = Appointment.objects.filter(
        staff_profile=staff,
        status__in=list(OCCUPYING_STATUSES),
        occupancy_starts_at__lt=day_bounds.end,
        occupancy_ends_at__gt=day_bounds.start,
    )
    if exclude_appointment_id is not None:
        qs = qs.exclude(pk=exclude_appointment_id)
    return [TimeInterval(row.occupancy_starts_at, row.occupancy_ends_at) for row in qs]


def _iter_grid_starts(local_day: date, tz: ZoneInfo):
    cursor = datetime.combine(local_day, time.min, tzinfo=tz)
    end = cursor + timedelta(days=1)
    step = timedelta(minutes=SLOT_GRID_MINUTES)
    while cursor < end:
        yield cursor
        cursor += step


def compute_free_intervals_for_staff(
    *,
    staff: StaffProfile,
    location,
    local_day: date,
    exclude_appointment_id=None,
) -> list[TimeInterval]:
    tz = _local_zone(location)
    day_bounds = _local_day_bounds_utc(local_day, tz)
    free = _availability_intervals_utc(
        staff=staff,
        location=location,
        local_day=local_day,
        tz=tz,
    )
    blockers = _time_off_blockers(staff=staff, day_bounds=day_bounds) + _appointment_blockers(
        staff=staff,
        day_bounds=day_bounds,
        exclude_appointment_id=exclude_appointment_id,
    )
    return _subtract_intervals(free, blockers)


def occupancy_window(
    *,
    starts_at: datetime,
    duration_minutes: int,
    buffer_before_minutes: int,
    buffer_after_minutes: int,
) -> tuple[datetime, datetime, TimeInterval]:
    starts_at = _ensure_aware(starts_at).astimezone(UTC)
    ends_at = starts_at + timedelta(minutes=duration_minutes)
    occupancy_starts = starts_at - timedelta(minutes=buffer_before_minutes)
    occupancy_ends = ends_at + timedelta(minutes=buffer_after_minutes)
    return starts_at, ends_at, TimeInterval(occupancy_starts, occupancy_ends)


def staff_can_take_occupancy(
    *, staff, location, local_day, occupancy: TimeInterval, exclude_appointment_id=None
) -> bool:
    free = compute_free_intervals_for_staff(
        staff=staff,
        location=location,
        local_day=local_day,
        exclude_appointment_id=exclude_appointment_id,
    )
    return any(interval.contains(occupancy) for interval in free)


def compute_available_slots(
    *,
    organization,
    business,
    location,
    service: Service,
    local_day: date,
    staff_id=None,
) -> list[dict]:
    if not location.is_active:
        raise ValidationError({"location_id": "Location is not active."})
    if not service.is_active:
        raise ValidationError({"service_id": "Service is not active."})

    service_location = get_service_location_for_booking(
        organization=organization,
        service=service,
        location=location,
    )
    eligible = list_eligible_staff(
        organization=organization,
        business=business,
        location=location,
        service=service,
        staff_id=staff_id,
    )
    tz = _local_zone(location)
    now_utc = timezone.now()

    # Map start_utc -> sorted staff ids
    slot_map: dict[datetime, list[uuid.UUID]] = {}
    ends_map: dict[datetime, datetime] = {}

    for staff in eligible:
        staff_service = _get_staff_service(
            organization=organization,
            staff_profile=staff,
            service=service,
        )
        pricing = resolve_effective_pricing(
            service=service,
            service_location=service_location,
            staff_service=staff_service,
        )
        free = compute_free_intervals_for_staff(
            staff=staff,
            location=location,
            local_day=local_day,
        )
        duration = pricing.duration_minutes
        before = pricing.buffer_before_minutes
        after = pricing.buffer_after_minutes

        for local_start in _iter_grid_starts(local_day, tz):
            starts_at, ends_at, occupancy = occupancy_window(
                starts_at=local_start,
                duration_minutes=duration,
                buffer_before_minutes=before,
                buffer_after_minutes=after,
            )
            # Skip past visible starts for availability listing
            if starts_at < now_utc:
                continue
            if not any(interval.contains(occupancy) for interval in free):
                continue
            slot_map.setdefault(starts_at, []).append(staff.id)
            ends_map[starts_at] = ends_at

    slots = []
    for starts_at in sorted(slot_map.keys()):
        staff_ids = sorted(slot_map[starts_at], key=lambda value: str(value))
        local_start = starts_at.astimezone(tz)
        slots.append(
            {
                "starts_at": starts_at,
                "ends_at": ends_map[starts_at],
                "local_starts_at": local_start.isoformat(),
                "timezone": location.timezone,
                "staff_options": staff_ids,
                "staff_profile_id": staff_ids[0] if staff_id is not None else None,
            }
        )
    return slots


def pick_staff_for_slot(*, staff_options: list) -> StaffProfile:
    """Deterministic tie-break: lowest staff UUID string among eligible options."""
    if not staff_options:
        raise ValidationError({"starts_at": "No eligible staff for this slot."})
    chosen_id = sorted(staff_options, key=lambda value: str(value))[0]
    return StaffProfile.objects.get(pk=chosen_id)


def _lock_overlapping_appointments(*, staff, occupancy: TimeInterval, exclude_id=None):
    qs = (
        Appointment.objects.select_for_update()
        .filter(
            staff_profile=staff,
            status__in=list(OCCUPYING_STATUSES),
            occupancy_starts_at__lt=occupancy.end,
            occupancy_ends_at__gt=occupancy.start,
        )
        .order_by("occupancy_starts_at")
    )
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    return list(qs)


def list_appointments(*, organization, business):
    return (
        Appointment.objects.filter(organization=organization, business=business)
        .select_related("location", "customer", "staff_profile")
        .prefetch_related(
            Prefetch("items", queryset=AppointmentItem.objects.select_related("service"))
        )
        .order_by("starts_at")
    )


def get_appointment_for_business(*, organization, business, appointment_id) -> Appointment:
    return get_object_or_404(
        Appointment.objects.select_related(
            "location", "customer", "staff_profile", "business"
        ).prefetch_related(
            Prefetch("items", queryset=AppointmentItem.objects.select_related("service"))
        ),
        organization=organization,
        business=business,
        pk=appointment_id,
    )


@transaction.atomic
def create_appointment(
    *,
    organization,
    business_id,
    actor,
    location_id,
    customer_id,
    service_id,
    starts_at: datetime,
    staff_id=None,
    status: str = AppointmentStatus.CONFIRMED,
    source: str = AppointmentSource.DASHBOARD,
    notes: str = "",
    emit_booked_event: bool = True,
    booking_plan=None,
    plan_occurrence_date=None,
    acquisition_source: str | None = None,
    acquisition_reference=None,
) -> Appointment:
    business = get_business_for_organization(organization=organization, business_id=business_id)
    location = get_location_for_business(
        organization=organization,
        business=business,
        location_id=location_id,
    )
    if not location.is_active:
        raise ValidationError({"location_id": "Location is not active."})

    customer = get_customer_for_business(
        organization=organization,
        business=business,
        customer_id=customer_id,
    )
    service = get_service_for_business(
        organization=organization,
        business=business,
        service_id=service_id,
    )
    if not service.is_active:
        raise ValidationError({"service_id": "Service is not active."})

    if status not in {AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED}:
        raise ValidationError({"status": "New appointments must be PENDING or CONFIRMED."})
    if source not in AppointmentSource.values:
        raise ValidationError({"source": "Invalid appointment source."})

    starts_at = _ensure_aware(starts_at).astimezone(UTC)
    tz = _local_zone(location)
    local_day = starts_at.astimezone(tz).date()

    # Align to 15-minute grid in local time
    local_start = starts_at.astimezone(tz)
    if (
        local_start.minute % SLOT_GRID_MINUTES != 0
        or local_start.second != 0
        or local_start.microsecond != 0
    ):
        raise ValidationError(
            {
                "starts_at": (
                    f"Start time must align to a {SLOT_GRID_MINUTES}-minute "
                    "grid in the location timezone."
                )
            }
        )

    service_location = get_service_location_for_booking(
        organization=organization,
        service=service,
        location=location,
    )

    eligible = list_eligible_staff(
        organization=organization,
        business=business,
        location=location,
        service=service,
        staff_id=staff_id,
    )

    # Resolve staff before insert (any-staff: deterministic UUID among those free at this start)
    candidates: list[tuple[StaffProfile, EffectiveServicePricing, TimeInterval, datetime]] = []
    for staff in eligible:
        staff_service = _get_staff_service(
            organization=organization,
            staff_profile=staff,
            service=service,
        )
        pricing = resolve_effective_pricing(
            service=service,
            service_location=service_location,
            staff_service=staff_service,
        )
        visible_start, visible_end, occupancy = occupancy_window(
            starts_at=starts_at,
            duration_minutes=pricing.duration_minutes,
            buffer_before_minutes=pricing.buffer_before_minutes,
            buffer_after_minutes=pricing.buffer_after_minutes,
        )
        if staff_can_take_occupancy(
            staff=staff,
            location=location,
            local_day=local_day,
            occupancy=occupancy,
        ):
            candidates.append((staff, pricing, occupancy, visible_end))

    if not candidates:
        raise ValidationError({"starts_at": "Requested time is not available."})

    candidates.sort(key=lambda row: str(row[0].id))
    staff, pricing, occupancy, ends_at = candidates[0]

    # Serialize concurrent writers for this staff
    StaffProfile.objects.select_for_update().filter(pk=staff.pk).get()
    overlapping = _lock_overlapping_appointments(staff=staff, occupancy=occupancy)
    if overlapping:
        raise AppointmentConflict()

    # Revalidate inside lock
    if not staff_can_take_occupancy(
        staff=staff,
        location=location,
        local_day=local_day,
        occupancy=occupancy,
    ):
        raise AppointmentConflict()

    get_service_location_for_booking(
        organization=organization,
        service=service,
        location=location,
    )
    _get_staff_service(organization=organization, staff_profile=staff, service=service)

    try:
        appointment = Appointment.objects.create(
            organization=organization,
            business=business,
            location=location,
            customer=customer,
            staff_profile=staff,
            starts_at=starts_at,
            ends_at=ends_at,
            occupancy_starts_at=occupancy.start,
            occupancy_ends_at=occupancy.end,
            status=status,
            source=source,
            acquisition_source=acquisition_source or None,
            acquisition_reference=acquisition_reference,
            total_price=pricing.price,
            currency=pricing.currency,
            notes=notes or "",
            public_reference=generate_public_reference(),
            booking_plan=booking_plan,
            plan_occurrence_date=plan_occurrence_date,
            created_by=actor,
            updated_by=actor,
        )
        AppointmentItem.objects.create(
            appointment=appointment,
            service=service,
            staff_profile=staff,
            service_name=pricing.service_name,
            duration_minutes=pricing.duration_minutes,
            buffer_before_minutes=pricing.buffer_before_minutes,
            buffer_after_minutes=pricing.buffer_after_minutes,
            price=pricing.price,
            currency=pricing.currency,
            created_by=actor,
            updated_by=actor,
        )
    except IntegrityError as exc:
        raise AppointmentConflict() from exc

    from payments.services import initial_appointment_payment_status

    payment_status = initial_appointment_payment_status(appointment=appointment)
    if payment_status != appointment.payment_status:
        appointment.payment_status = payment_status
        appointment.save(update_fields=["payment_status", "updated_at"])

    appointment_id = appointment.id
    if emit_booked_event:
        transaction.on_commit(lambda: emit(AppointmentBooked(appointment_id=appointment_id)))
    transaction.on_commit(lambda: emit(AppointmentCreated(appointment_id=appointment_id)))
    if status == AppointmentStatus.CONFIRMED:
        transaction.on_commit(lambda: emit(AppointmentConfirmed(appointment_id=appointment_id)))

    return get_appointment_for_business(
        organization=organization,
        business=business,
        appointment_id=appointment.id,
    )


@transaction.atomic
def transition_appointment_status(
    *,
    appointment: Appointment,
    actor,
    new_status: str,
) -> Appointment:
    if new_status not in AppointmentStatus.values:
        raise ValidationError({"status": "Invalid status."})
    allowed = ALLOWED_STATUS_TRANSITIONS.get(appointment.status, frozenset())
    if new_status not in allowed:
        raise ValidationError(
            {"status": (f"Cannot transition from {appointment.status} to {new_status}.")}
        )

    StaffProfile.objects.select_for_update().filter(pk=appointment.staff_profile_id).get()
    appointment.status = new_status
    appointment.updated_by = actor
    if new_status == AppointmentStatus.CANCELLED:
        appointment.cancelled_at = timezone.now()
        appointment.cancelled_by = actor
    if new_status == AppointmentStatus.COMPLETED and appointment.completed_at is None:
        appointment.completed_at = timezone.now()
    try:
        appointment.save()
    except IntegrityError as exc:
        raise AppointmentConflict() from exc
    if new_status == AppointmentStatus.COMPLETED:
        from customers.services import refresh_customer_visit_totals

        refresh_customer_visit_totals(customer_id=appointment.customer_id)
    appointment_id = appointment.id
    if new_status == AppointmentStatus.CONFIRMED:
        transaction.on_commit(lambda: emit(AppointmentConfirmed(appointment_id=appointment_id)))
    elif new_status == AppointmentStatus.COMPLETED:
        transaction.on_commit(lambda: emit(AppointmentCompleted(appointment_id=appointment_id)))
    return appointment


@transaction.atomic
def cancel_appointment(
    *,
    appointment: Appointment,
    actor,
    reason: str = "",
) -> Appointment:
    if appointment.status in {
        AppointmentStatus.COMPLETED,
        AppointmentStatus.CANCELLED,
        AppointmentStatus.NO_SHOW,
    }:
        raise ValidationError({"status": "This appointment cannot be cancelled."})

    allowed = ALLOWED_STATUS_TRANSITIONS.get(appointment.status, frozenset())
    if AppointmentStatus.CANCELLED not in allowed:
        raise ValidationError({"status": "This appointment cannot be cancelled."})

    StaffProfile.objects.select_for_update().filter(pk=appointment.staff_profile_id).get()
    appointment.status = AppointmentStatus.CANCELLED
    appointment.cancelled_at = timezone.now()
    appointment.cancelled_by = actor
    appointment.cancellation_reason = (reason or "")[:255]
    appointment.updated_by = actor
    appointment.save()

    appointment_id = appointment.id
    transaction.on_commit(lambda: emit(AppointmentCancelled(appointment_id=appointment_id)))
    return appointment


@transaction.atomic
def reschedule_appointment(
    *,
    appointment: Appointment,
    actor,
    starts_at: datetime,
) -> Appointment:
    if appointment.status not in {AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED}:
        raise ValidationError(
            {"starts_at": "Only pending or confirmed appointments can be rescheduled."}
        )

    item = appointment.items.select_related("service").first()
    if item is None:
        raise ValidationError({"detail": "Appointment has no service item."})

    starts_at = _ensure_aware(starts_at).astimezone(UTC)
    location = appointment.location
    tz = _local_zone(location)
    local_start = starts_at.astimezone(tz)
    if (
        local_start.minute % SLOT_GRID_MINUTES != 0
        or local_start.second != 0
        or local_start.microsecond != 0
    ):
        raise ValidationError(
            {
                "starts_at": (
                    f"Start time must align to a {SLOT_GRID_MINUTES}-minute "
                    "grid in the location timezone."
                )
            }
        )
    local_day = local_start.date()

    visible_start, visible_end, occupancy = occupancy_window(
        starts_at=starts_at,
        duration_minutes=item.duration_minutes,
        buffer_before_minutes=item.buffer_before_minutes,
        buffer_after_minutes=item.buffer_after_minutes,
    )

    StaffProfile.objects.select_for_update().filter(pk=appointment.staff_profile_id).get()
    overlapping = _lock_overlapping_appointments(
        staff=appointment.staff_profile,
        occupancy=occupancy,
        exclude_id=appointment.pk,
    )
    if overlapping:
        raise AppointmentConflict()

    if not staff_can_take_occupancy(
        staff=appointment.staff_profile,
        location=location,
        local_day=local_day,
        occupancy=occupancy,
        exclude_appointment_id=appointment.pk,
    ):
        raise AppointmentConflict()

    appointment.starts_at = visible_start
    appointment.ends_at = visible_end
    appointment.occupancy_starts_at = occupancy.start
    appointment.occupancy_ends_at = occupancy.end
    appointment.updated_by = actor
    appointment.schedule_version = (appointment.schedule_version or 1) + 1
    try:
        appointment.save()
    except IntegrityError as exc:
        raise AppointmentConflict() from exc
    appointment_id = appointment.id
    transaction.on_commit(lambda: emit(AppointmentRescheduled(appointment_id=appointment_id)))
    return appointment


@transaction.atomic
def update_appointment(
    *,
    appointment: Appointment,
    actor,
    **fields,
) -> Appointment:
    if "status" in fields and fields["status"] != appointment.status:
        appointment = transition_appointment_status(
            appointment=appointment,
            actor=actor,
            new_status=fields["status"],
        )
    if "starts_at" in fields and fields["starts_at"] is not None:
        appointment = reschedule_appointment(
            appointment=appointment,
            actor=actor,
            starts_at=fields["starts_at"],
        )
    if "notes" in fields:
        appointment.notes = fields["notes"] or ""
        appointment.updated_by = actor
        appointment.save(update_fields=["notes", "updated_by", "updated_at"])
    if "cancellation_reason" in fields and appointment.status == AppointmentStatus.CANCELLED:
        appointment.cancellation_reason = (fields["cancellation_reason"] or "")[:255]
        appointment.updated_by = actor
        appointment.save(update_fields=["cancellation_reason", "updated_by", "updated_at"])
    return get_appointment_for_business(
        organization=appointment.organization,
        business=appointment.business,
        appointment_id=appointment.id,
    )
