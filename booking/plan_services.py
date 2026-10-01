"""Book Regularly — BookingPlan orchestration (not subscriptions / payments)."""

from __future__ import annotations

import calendar
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from booking.events import AppointmentBooked, emit
from booking.manage_tokens import (
    hash_manage_token,
    issue_manage_token,
    resolve_appointment_for_manage_token,
)
from booking.models import (
    ALLOWED_BOOKING_PLAN_TRANSITIONS,
    Appointment,
    AppointmentSource,
    AppointmentStatus,
    BookingPlan,
    BookingPlanFrequency,
    BookingPlanManageToken,
    BookingPlanStaffPreference,
    BookingPlanStatus,
    IdempotencyRecord,
)
from booking.public_services import (
    IDEMPOTENCY_PENDING,
    _raise,
    _replay_or_conflict,
    resolve_public_location,
    resolve_public_service,
    serialize_public_appointment,
)
from booking.services import (
    AppointmentConflict,
    compute_available_slots,
    create_appointment,
    get_service_location_for_booking,
)
from customers.services import get_or_create_customer_by_phone

logger = logging.getLogger(__name__)

PUBLIC_PLAN_CREATE_SCOPE = "public_booking.plan_create"
DEFAULT_PLAN_TOKEN_TTL_DAYS = 365 * 2
PLAN_TOKEN_BYTES = 32

FREQUENCY_LABELS = {
    (BookingPlanFrequency.WEEK, 1): "Every week",
    (BookingPlanFrequency.WEEK, 2): "Every 2 weeks",
    (BookingPlanFrequency.MONTH, 1): "Every month",
    (BookingPlanFrequency.MONTH, 2): "Every 2 months",
}

ALLOWED_FREQUENCY_INTERVALS = frozenset(
    {
        (BookingPlanFrequency.WEEK, 1),
        (BookingPlanFrequency.WEEK, 2),
        (BookingPlanFrequency.MONTH, 1),
        (BookingPlanFrequency.MONTH, 2),
    }
)


def add_plan_interval(local_day: date, *, frequency: str, interval: int) -> date:
    """Advance a calendar date by WEEK/MONTH interval (calendar months, not 30 days)."""
    if interval < 1:
        raise ValueError("interval must be >= 1")
    if frequency == BookingPlanFrequency.WEEK:
        return local_day + timedelta(weeks=interval)
    if frequency == BookingPlanFrequency.MONTH:
        month_index = local_day.month - 1 + interval
        year = local_day.year + month_index // 12
        month = month_index % 12 + 1
        day = min(local_day.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)
    raise ValueError(f"Unsupported frequency: {frequency}")


def combine_local_start(*, local_day: date, preferred_time: time, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    return datetime(
        local_day.year,
        local_day.month,
        local_day.day,
        preferred_time.hour,
        preferred_time.minute,
        preferred_time.second,
        tzinfo=tz,
    )


def next_due_after(*, local_start: datetime, frequency: str, interval: int) -> datetime:
    next_day = add_plan_interval(
        local_start.date(),
        frequency=frequency,
        interval=interval,
    )
    return combine_local_start(
        local_day=next_day,
        preferred_time=local_start.time().replace(tzinfo=None),
        tz_name=str(local_start.tzinfo),
    )


def _preferred_time_from_local(local_start: datetime) -> time:
    return time(local_start.hour, local_start.minute, local_start.second)


def frequency_label(*, frequency: str, interval: int) -> str:
    return FREQUENCY_LABELS.get((frequency, interval), f"Every {interval} {frequency.lower()}")


def issue_plan_manage_token(*, booking_plan: BookingPlan) -> str:
    import secrets

    raw = secrets.token_urlsafe(PLAN_TOKEN_BYTES)
    token_hash = hash_manage_token(raw)
    expires_at = timezone.now() + timedelta(days=DEFAULT_PLAN_TOKEN_TTL_DAYS)
    BookingPlanManageToken.objects.update_or_create(
        booking_plan=booking_plan,
        defaults={
            "token_hash": token_hash,
            "expires_at": expires_at,
            "revoked_at": None,
        },
    )
    return raw


def resolve_plan_for_manage_token(raw_token: str) -> BookingPlan | None:
    cleaned = (raw_token or "").strip()
    if not cleaned:
        return None
    token_hash = hash_manage_token(cleaned)
    row = (
        BookingPlanManageToken.objects.select_related(
            "booking_plan",
            "booking_plan__location",
            "booking_plan__location__business",
            "booking_plan__service",
            "booking_plan__staff_profile",
            "booking_plan__customer",
        )
        .filter(token_hash=token_hash, revoked_at__isnull=True)
        .first()
    )
    if row is None:
        return None
    if row.expires_at is not None and row.expires_at <= timezone.now():
        return None
    plan = row.booking_plan
    if plan.deleted_at is not None:
        return None
    return plan


def _plan_not_found():
    _raise(
        "BOOKING_NOT_FOUND",
        "This booking link is invalid or has expired.",
        status_code=404,
    )


def _request_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def serialize_public_booking_plan(plan: BookingPlan) -> dict:
    tz = ZoneInfo(plan.timezone)
    next_local = plan.next_due_at.astimezone(tz)
    next_appointment = (
        Appointment.objects.filter(
            booking_plan=plan,
            plan_occurrence_date=next_local.date(),
            deleted_at__isnull=True,
        )
        .exclude(status=AppointmentStatus.CANCELLED)
        .order_by("starts_at")
        .first()
    )
    upcoming = (
        Appointment.objects.filter(
            booking_plan=plan,
            deleted_at__isnull=True,
            status__in=[
                AppointmentStatus.PENDING,
                AppointmentStatus.CONFIRMED,
                AppointmentStatus.CHECKED_IN,
            ],
            starts_at__gte=timezone.now(),
        )
        .order_by("starts_at")
        .first()
    )
    next_block = None
    ref_appt = upcoming or next_appointment
    if ref_appt is not None:
        local = ref_appt.starts_at.astimezone(tz)
        next_block = {
            "date": local.date().isoformat(),
            "time": local.strftime("%H:%M"),
            "public_reference": ref_appt.public_reference,
        }
    elif not plan.needs_action and plan.status == BookingPlanStatus.ACTIVE:
        next_block = {
            "date": next_local.date().isoformat(),
            "time": next_local.strftime("%H:%M"),
            "public_reference": None,
        }

    return {
        "service_name": plan.service.name,
        "business_name": plan.business.name,
        "location_name": plan.location.name,
        "frequency": plan.frequency,
        "interval": plan.interval,
        "frequency_label": frequency_label(frequency=plan.frequency, interval=plan.interval),
        "preferred_time": plan.preferred_time.strftime("%H:%M"),
        "staff_preference": plan.staff_preference,
        "staff_name": (
            plan.staff_profile.display_name
            if plan.staff_profile_id
            and plan.staff_preference == BookingPlanStaffPreference.SAME_STAFF
            else None
        ),
        "status": plan.status,
        "needs_action": plan.needs_action,
        "needs_action_code": plan.needs_action_code or None,
        "next_appointment": next_block,
        "timezone": plan.timezone,
    }


def serialize_managed_regular_booking(plan: BookingPlan) -> dict:
    data = serialize_public_booking_plan(plan)
    data["can_pause"] = plan.status == BookingPlanStatus.ACTIVE
    data["can_resume"] = plan.status == BookingPlanStatus.PAUSED
    data["can_cancel"] = plan.status != BookingPlanStatus.CANCELLED
    return data


@transaction.atomic
def _transition_plan(*, plan: BookingPlan, new_status: str) -> BookingPlan:
    if plan.status == new_status:
        return plan  # idempotent
    allowed = ALLOWED_BOOKING_PLAN_TRANSITIONS.get(plan.status, frozenset())
    if new_status not in allowed:
        raise ValidationError({"status": f"Cannot transition from {plan.status} to {new_status}."})
    plan.status = new_status
    fields = ["status", "updated_at"]
    if new_status == BookingPlanStatus.CANCELLED:
        plan.cancelled_at = timezone.now()
        fields.append("cancelled_at")
    plan.save(update_fields=fields)
    return plan


def pause_booking_plan(*, plan: BookingPlan) -> BookingPlan:
    return _transition_plan(plan=plan, new_status=BookingPlanStatus.PAUSED)


def resume_booking_plan(*, plan: BookingPlan, now: datetime | None = None) -> BookingPlan:
    clock = now or timezone.now()
    if timezone.is_naive(clock):
        clock = timezone.make_aware(clock, UTC)
    plan = _transition_plan(plan=plan, new_status=BookingPlanStatus.ACTIVE)
    if plan.next_due_at <= clock:
        plan.needs_action = True
        plan.needs_action_code = "RESUME_REQUIRES_SLOT"
        plan.save(update_fields=["needs_action", "needs_action_code", "updated_at"])
    elif plan.needs_action_code in {
        "SLOT_UNAVAILABLE",
        "STAFF_UNAVAILABLE",
        "RESUME_REQUIRES_SLOT",
    }:
        plan.needs_action = False
        plan.needs_action_code = ""
        plan.save(update_fields=["needs_action", "needs_action_code", "updated_at"])
    return plan


def cancel_booking_plan(*, plan: BookingPlan) -> BookingPlan:
    """Cancel the plan only — does not cancel existing appointments."""
    return _transition_plan(plan=plan, new_status=BookingPlanStatus.CANCELLED)


def get_public_booking_plan(*, raw_token: str) -> dict:
    plan = resolve_plan_for_manage_token(raw_token)
    if plan is None:
        _plan_not_found()
    return serialize_public_booking_plan(plan)


def pause_public_booking_plan(*, raw_token: str) -> dict:
    plan = resolve_plan_for_manage_token(raw_token)
    if plan is None:
        _plan_not_found()
    plan = BookingPlan.objects.select_for_update().get(pk=plan.pk)
    pause_booking_plan(plan=plan)
    return serialize_public_booking_plan(plan)


def resume_public_booking_plan(*, raw_token: str) -> dict:
    plan = resolve_plan_for_manage_token(raw_token)
    if plan is None:
        _plan_not_found()
    plan = BookingPlan.objects.select_for_update().get(pk=plan.pk)
    resume_booking_plan(plan=plan)
    return serialize_public_booking_plan(plan)


def cancel_public_booking_plan(*, raw_token: str) -> dict:
    plan = resolve_plan_for_manage_token(raw_token)
    if plan is None:
        _plan_not_found()
    plan = BookingPlan.objects.select_for_update().get(pk=plan.pk)
    cancel_booking_plan(plan=plan)
    return serialize_public_booking_plan(plan)


def _resolve_plan_via_appointment_token(raw_token: str) -> BookingPlan:
    appointment = resolve_appointment_for_manage_token(raw_token)
    if appointment is None or appointment.booking_plan_id is None:
        _plan_not_found()
    plan = (
        BookingPlan.objects.select_related(
            "location",
            "location__business",
            "business",
            "service",
            "staff_profile",
            "customer",
        )
        .filter(pk=appointment.booking_plan_id, customer_id=appointment.customer_id)
        .first()
    )
    if plan is None or plan.deleted_at is not None:
        _plan_not_found()
    return plan


def get_regular_booking_for_manage_token(*, raw_token: str) -> dict | None:
    appointment = resolve_appointment_for_manage_token(raw_token)
    if appointment is None or not appointment.booking_plan_id:
        return None
    plan = (
        BookingPlan.objects.select_related(
            "location",
            "business",
            "service",
            "staff_profile",
            "customer",
        )
        .filter(pk=appointment.booking_plan_id, customer_id=appointment.customer_id)
        .first()
    )
    if plan is None or plan.deleted_at is not None:
        return None
    return serialize_managed_regular_booking(plan)


def pause_plan_via_appointment_token(*, raw_token: str) -> dict:
    plan = _resolve_plan_via_appointment_token(raw_token)
    plan = BookingPlan.objects.select_for_update().get(pk=plan.pk)
    pause_booking_plan(plan=plan)
    return serialize_managed_regular_booking(plan)


def resume_plan_via_appointment_token(*, raw_token: str) -> dict:
    plan = _resolve_plan_via_appointment_token(raw_token)
    plan = BookingPlan.objects.select_for_update().get(pk=plan.pk)
    resume_booking_plan(plan=plan)
    return serialize_managed_regular_booking(plan)


def cancel_plan_via_appointment_token(*, raw_token: str) -> dict:
    plan = _resolve_plan_via_appointment_token(raw_token)
    plan = BookingPlan.objects.select_for_update().get(pk=plan.pk)
    cancel_booking_plan(plan=plan)
    return serialize_managed_regular_booking(plan)


def _validate_frequency_interval(*, frequency: str, interval: int):
    if frequency not in BookingPlanFrequency.values:
        raise ValidationError({"frequency": "Unsupported frequency."})
    if (frequency, interval) not in ALLOWED_FREQUENCY_INTERVALS:
        raise ValidationError({"interval": "Supported intervals: 1–2 weeks or 1–2 months."})


@transaction.atomic
def create_public_booking_plan(
    *,
    location_id,
    service_id,
    starts_at: datetime,
    customer_name: str,
    customer_phone: str,
    customer_email: str = "",
    staff_id=None,
    frequency: str,
    interval: int,
    staff_preference: str | None = None,
    preferred_time: time | None = None,
    idempotency_key: str | None = None,
) -> tuple[dict, int, bool]:
    """Create BookingPlan + first Appointment in one transaction."""
    _validate_frequency_interval(frequency=frequency, interval=interval)

    payload_for_hash = {
        "location_id": str(location_id),
        "service_id": str(service_id),
        "staff_id": str(staff_id) if staff_id else None,
        "starts_at": starts_at.isoformat(),
        "frequency": frequency,
        "interval": interval,
        "staff_preference": staff_preference,
        "preferred_time": preferred_time.isoformat() if preferred_time else None,
        "customer": {
            "name": customer_name.strip(),
            "phone": customer_phone.strip(),
            "email": (customer_email or "").strip().lower(),
        },
    }
    request_hash = _request_hash(payload_for_hash)
    record = None

    if idempotency_key:
        try:
            with transaction.atomic():
                record = IdempotencyRecord.objects.create(
                    scope=PUBLIC_PLAN_CREATE_SCOPE,
                    key=idempotency_key,
                    request_hash=request_hash,
                    response_status=IDEMPOTENCY_PENDING,
                    response_body={},
                )
        except IntegrityError:
            existing = (
                IdempotencyRecord.objects.select_for_update()
                .filter(scope=PUBLIC_PLAN_CREATE_SCOPE, key=idempotency_key)
                .get()
            )
            return _replay_or_conflict(existing, request_hash)

    location = resolve_public_location(location_id)
    service = resolve_public_service(location=location, service_id=service_id)

    if timezone.is_naive(starts_at):
        _raise("INVALID_START", "Start must include a timezone.", field="start")

    tz = ZoneInfo(location.timezone)
    local_start = starts_at.astimezone(tz)
    pref_time = preferred_time or _preferred_time_from_local(local_start)

    if staff_preference is None:
        staff_preference = (
            BookingPlanStaffPreference.SAME_STAFF
            if staff_id
            else BookingPlanStaffPreference.ANY_STAFF
        )
    if staff_preference not in BookingPlanStaffPreference.values:
        _raise("INVALID_STAFF_PREFERENCE", "Invalid staff preference.", field="staff_preference")

    if staff_preference == BookingPlanStaffPreference.SAME_STAFF:
        if staff_id is None:
            _raise(
                "INVALID_STAFF",
                "Same staff requires a selected staff member.",
                field="staff_id",
            )
        plan_staff_id = staff_id
    else:
        plan_staff_id = None
        # First appointment may still use a specific staff if chosen; any-staff plan stores null.
        # Prefer booking with provided staff_id for first visit, else any-staff resolution.

    try:
        customer = get_or_create_customer_by_phone(
            organization=location.organization,
            business=location.business,
            name=customer_name,
            phone=customer_phone,
            email=customer_email,
        )
    except ValidationError as exc:
        detail = exc.detail
        if isinstance(detail, dict) and "phone" in detail:
            _raise("INVALID_CUSTOMER", str(detail["phone"]), field="customer")
        if isinstance(detail, dict) and "name" in detail:
            _raise("INVALID_CUSTOMER", str(detail["name"]), field="customer")
        raise

    next_due_local = next_due_after(
        local_start=local_start.replace(
            hour=pref_time.hour,
            minute=pref_time.minute,
            second=pref_time.second,
            microsecond=0,
        ),
        frequency=frequency,
        interval=interval,
    )

    plan = BookingPlan(
        organization=location.organization,
        business=location.business,
        customer=customer,
        location=location,
        service=service,
        staff_profile_id=plan_staff_id,
        staff_preference=staff_preference,
        frequency=frequency,
        interval=interval,
        preferred_time=pref_time,
        timezone=location.timezone,
        start_date=local_start.date(),
        next_due_at=next_due_local.astimezone(UTC),
        status=BookingPlanStatus.ACTIVE,
    )
    plan.save()

    try:
        appointment = create_appointment(
            organization=location.organization,
            business_id=location.business_id,
            actor=None,
            location_id=location.id,
            customer_id=customer.id,
            service_id=service.id,
            starts_at=starts_at,
            staff_id=staff_id,
            status=AppointmentStatus.CONFIRMED,
            source=AppointmentSource.ONLINE,
            emit_booked_event=False,
            booking_plan=plan,
            plan_occurrence_date=local_start.date(),
        )
    except AppointmentConflict:
        _raise(
            "SLOT_UNAVAILABLE",
            "This time overlaps an existing appointment for the staff member.",
            status_code=409,
            field="start",
        )
    except ValidationError as exc:
        detail = exc.detail
        if isinstance(detail, dict):
            if "starts_at" in detail:
                _raise(
                    "SLOT_UNAVAILABLE",
                    str(detail["starts_at"]),
                    status_code=409,
                    field="start",
                )
            if "staff_id" in detail:
                _raise("INVALID_STAFF", str(detail["staff_id"]), field="staff_id")
            if "service_id" in detail:
                _raise("INVALID_SERVICE", str(detail["service_id"]), field="service_id")
        raise

    manage_token = issue_manage_token(appointment=appointment)
    plan_token = issue_plan_manage_token(booking_plan=plan)
    appointment_id = appointment.id
    transaction.on_commit(
        lambda aid=appointment_id, token=manage_token: emit(
            AppointmentBooked(appointment_id=aid, manage_token=token)
        )
    )

    body = {
        **serialize_public_appointment(appointment),
        "manage_token": manage_token,
        "plan_token": plan_token,
        "regular_booking": serialize_public_booking_plan(plan),
    }
    if record is not None:
        record.response_status = 201
        record.response_body = body
        record.save(update_fields=["response_status", "response_body", "updated_at"])
    return body, 201, False


@dataclass
class PlanProcessResult:
    processed: int = 0
    created: int = 0
    skipped: int = 0
    failed: int = 0


def _service_still_bookable(*, plan: BookingPlan) -> bool:
    service = plan.service
    location = plan.location
    if service.deleted_at is not None or not service.is_active or not service.is_bookable_online:
        return False
    if location.deleted_at is not None or not location.is_active:
        return False
    try:
        get_service_location_for_booking(
            organization=plan.organization,
            service=service,
            location=location,
        )
    except ValidationError:
        return False
    return True


def _mark_needs_action(plan: BookingPlan, code: str) -> None:
    plan.needs_action = True
    plan.needs_action_code = code
    plan.save(update_fields=["needs_action", "needs_action_code", "updated_at"])


@transaction.atomic
def process_one_booking_plan(*, plan_id, now: datetime) -> str:
    """
    Process a single due plan. Returns: created | skipped | needs_action | failed.
    Uses select_for_update to prevent duplicate occurrence bookings.
    """
    try:
        plan = BookingPlan.objects.select_for_update(of=("self",)).get(
            pk=plan_id,
            deleted_at__isnull=True,
        )
    except BookingPlan.DoesNotExist:
        return "skipped"

    plan = BookingPlan.objects.select_related(
        "organization",
        "business",
        "location",
        "service",
        "staff_profile",
        "customer",
    ).get(pk=plan.pk)

    if plan.status != BookingPlanStatus.ACTIVE or plan.needs_action:
        return "skipped"
    if plan.next_due_at > now:
        return "skipped"

    tz = ZoneInfo(plan.timezone)
    due_local = plan.next_due_at.astimezone(tz)
    occurrence_date = due_local.date()

    existing = Appointment.objects.filter(
        booking_plan=plan,
        plan_occurrence_date=occurrence_date,
        deleted_at__isnull=True,
    ).exists()
    if existing:
        # Advance past this occurrence
        nxt = next_due_after(
            local_start=due_local,
            frequency=plan.frequency,
            interval=plan.interval,
        )
        plan.next_due_at = nxt.astimezone(UTC)
        plan.save(update_fields=["next_due_at", "updated_at"])
        return "skipped"

    if not _service_still_bookable(plan=plan):
        _mark_needs_action(plan, "SERVICE_INACTIVE")
        return "needs_action"

    staff_id = (
        plan.staff_profile_id
        if plan.staff_preference == BookingPlanStaffPreference.SAME_STAFF
        else None
    )

    try:
        slots = compute_available_slots(
            organization=plan.organization,
            business=plan.business,
            location=plan.location,
            service=plan.service,
            local_day=occurrence_date,
            staff_id=staff_id,
        )
    except ValidationError:
        code = (
            "STAFF_UNAVAILABLE"
            if plan.staff_preference == BookingPlanStaffPreference.SAME_STAFF
            else "SLOT_UNAVAILABLE"
        )
        _mark_needs_action(plan, code)
        return "needs_action"

    target_utc = plan.next_due_at.astimezone(UTC)
    match = next(
        (slot for slot in slots if slot["starts_at"].astimezone(UTC) == target_utc),
        None,
    )
    if match is None:
        code = (
            "STAFF_UNAVAILABLE"
            if plan.staff_preference == BookingPlanStaffPreference.SAME_STAFF
            else "SLOT_UNAVAILABLE"
        )
        _mark_needs_action(plan, code)
        return "needs_action"

    try:
        appointment = create_appointment(
            organization=plan.organization,
            business_id=plan.business_id,
            actor=None,
            location_id=plan.location_id,
            customer_id=plan.customer_id,
            service_id=plan.service_id,
            starts_at=target_utc,
            staff_id=staff_id,
            status=AppointmentStatus.CONFIRMED,
            source=AppointmentSource.ONLINE,
            emit_booked_event=False,
            booking_plan=plan,
            plan_occurrence_date=occurrence_date,
        )
    except (AppointmentConflict, ValidationError, IntegrityError):
        _mark_needs_action(plan, "SLOT_UNAVAILABLE")
        return "needs_action"

    manage_token = issue_manage_token(appointment=appointment)
    appointment_id = appointment.id
    transaction.on_commit(
        lambda aid=appointment_id, token=manage_token: emit(
            AppointmentBooked(appointment_id=aid, manage_token=token)
        )
    )

    nxt = next_due_after(
        local_start=due_local,
        frequency=plan.frequency,
        interval=plan.interval,
    )
    plan.next_due_at = nxt.astimezone(UTC)
    plan.needs_action = False
    plan.needs_action_code = ""
    plan.save(
        update_fields=[
            "next_due_at",
            "needs_action",
            "needs_action_code",
            "updated_at",
        ]
    )
    return "created"


def process_due_booking_plans(
    *, now: datetime | None = None, limit: int = 100
) -> PlanProcessResult:
    clock = now or timezone.now()
    if timezone.is_naive(clock):
        clock = timezone.make_aware(clock, UTC)

    result = PlanProcessResult()
    plan_ids = list(
        BookingPlan.objects.filter(
            status=BookingPlanStatus.ACTIVE,
            needs_action=False,
            next_due_at__lte=clock,
            deleted_at__isnull=True,
        )
        .order_by("next_due_at")
        .values_list("id", flat=True)[:limit]
    )

    for plan_id in plan_ids:
        result.processed += 1
        try:
            outcome = process_one_booking_plan(plan_id=plan_id, now=clock)
            if outcome == "created":
                result.created += 1
            elif outcome in {"skipped", "needs_action"}:
                result.skipped += 1
            else:
                result.failed += 1
        except Exception:
            logger.exception("booking_plan.process_failed plan_id=%s", plan_id)
            result.failed += 1

    return result
