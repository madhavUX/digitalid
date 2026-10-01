"""Public booking orchestration — reuses booking.services, never reimplements slots."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from rest_framework.exceptions import APIException, ValidationError

from booking.events import AppointmentBooked, emit
from booking.manage_tokens import (
    appointment_can_cancel,
    issue_manage_token,
    resolve_appointment_for_manage_token,
)
from booking.models import Appointment, AppointmentSource, AppointmentStatus, IdempotencyRecord
from booking.services import (
    AppointmentConflict,
    cancel_appointment,
    compute_available_slots,
    create_appointment,
    get_service_location_for_booking,
    resolve_effective_pricing,
)
from catalog.models import Service
from customers.services import get_or_create_customer_by_phone
from locations.models import Location

PUBLIC_CREATE_SCOPE = "public_booking.create"
IDEMPOTENCY_PENDING = 0


class PublicBookingError(APIException):
    status_code = 400
    default_detail = "Public booking request is invalid."
    default_code = "public_booking_error"

    def __init__(self, detail=None, *, code=None, status_code=None):
        if status_code is not None:
            self.status_code = status_code
        resolved_code = code or self.default_code
        self.error_code = resolved_code
        super().__init__(detail=detail, code=resolved_code)


def _raise(code: str, message: str, status_code: int = 400, field: str | None = None):
    detail = {field: message} if field else message
    raise PublicBookingError(detail=detail, code=code, status_code=status_code)


def resolve_public_location(location_id) -> Location:
    try:
        location = Location.objects.select_related("business", "organization").get(pk=location_id)
    except (Location.DoesNotExist, ValueError, TypeError):
        _raise("INVALID_LOCATION", "Location not found.", status_code=404, field="location_id")
    if not location.is_active:
        _raise("INVALID_LOCATION", "Location is not active.", field="location_id")
    return location


def resolve_public_service(*, location: Location, service_id) -> Service:
    try:
        service = Service.objects.get(
            pk=service_id,
            organization=location.organization,
            business=location.business,
        )
    except (Service.DoesNotExist, ValueError, TypeError):
        _raise("INVALID_SERVICE", "Service not found.", status_code=404, field="service_id")
    if not service.is_active:
        _raise("INVALID_SERVICE", "Service is not active.", field="service_id")
    if not service.is_bookable_online:
        _raise("INVALID_SERVICE", "Service is not bookable online.", field="service_id")
    try:
        get_service_location_for_booking(
            organization=location.organization,
            service=service,
            location=location,
        )
    except ValidationError:
        _raise(
            "INVALID_SERVICE",
            "This service is not offered at the selected location.",
            field="service_id",
        )
    return service


def public_availability(*, location_id, service_id, local_day: date, staff_id=None) -> dict:
    location = resolve_public_location(location_id)
    service = resolve_public_service(location=location, service_id=service_id)

    try:
        slots = compute_available_slots(
            organization=location.organization,
            business=location.business,
            location=location,
            service=service,
            local_day=local_day,
            staff_id=staff_id,
        )
    except ValidationError as exc:
        detail = exc.detail
        if isinstance(detail, dict) and "staff_id" in detail:
            _raise("INVALID_STAFF", str(detail["staff_id"]), field="staff_id")
        raise

    service_location = get_service_location_for_booking(
        organization=location.organization,
        service=service,
        location=location,
    )
    pricing = resolve_effective_pricing(
        service=service,
        service_location=service_location,
        staff_service=None,
    )
    tz = ZoneInfo(location.timezone)
    public_slots = []
    for slot in slots:
        start_local = slot["starts_at"].astimezone(tz)
        end_local = slot["ends_at"].astimezone(tz)
        entry = {
            "start": start_local.isoformat(),
            "end": end_local.isoformat(),
            "starts_at": slot["starts_at"].isoformat().replace("+00:00", "Z"),
            "ends_at": slot["ends_at"].isoformat().replace("+00:00", "Z"),
        }
        if staff_id is not None:
            entry["staff_id"] = str(slot["staff_options"][0])
        else:
            entry["staff_id"] = None
            entry["staff_options"] = [str(value) for value in slot["staff_options"]]
        public_slots.append(entry)

    return {
        "location": {
            "id": str(location.id),
            "name": location.name,
            "timezone": location.timezone,
        },
        "service": {
            "id": str(service.id),
            "name": service.name,
            "duration_minutes": pricing.duration_minutes,
            "price": str(pricing.price),
            "currency": pricing.currency,
        },
        "date": local_day.isoformat(),
        "slot_grid_minutes": 15,
        "slots": public_slots,
    }


def resolve_quickcard_attribution(*, location, source: str | None, ref: str | None):
    """Return (QUICKCARD, card id) only when the public ref matches this location.

    A bad or cross-tenant ref returns (None, None) so booking can continue.
    """
    from sites.models import QuickCard

    if (source or "").strip().lower() != "quickcard":
        return None, None
    slug = (ref or "").strip()
    if not slug or len(slug) > 255:
        return None, None
    card = (
        QuickCard.objects.filter(
            slug=slug,
            is_published=True,
            location_id=location.id,
            business_id=location.business_id,
            organization_id=location.organization_id,
            location__is_active=True,
            business__is_active=True,
        )
        .only("id")
        .first()
    )
    if card is None:
        return None, None
    return "QUICKCARD", card.id


def resolve_retention_attribution(*, location, source: str | None, ref: str | None, customer):
    """Return (RETENTION, message id) when the opaque ref matches this booking.

    Requires same org/business/location/customer. Cancelled or skipped cycles
    do not attribute. Invalid refs return (None, None) so booking continues.
    """
    from customers.models import CustomerRetentionMessage, CustomerRetentionMessageStatus

    if (source or "").strip().lower() != "retention":
        return None, None
    if customer is None:
        return None, None
    token = (ref or "").strip()
    if not token or len(token) > 32:
        return None, None
    row = (
        CustomerRetentionMessage.objects.filter(
            public_reference=token,
            organization_id=location.organization_id,
            business_id=location.business_id,
            location_id=location.id,
            customer_id=customer.id,
        )
        .only("id", "status")
        .first()
    )
    if row is None:
        return None, None
    if row.status in {
        CustomerRetentionMessageStatus.CANCELLED,
        CustomerRetentionMessageStatus.SKIPPED,
    }:
        return None, None
    return "RETENTION", row.id


def resolve_public_booking_attribution(
    *,
    location,
    source: str | None,
    ref: str | None,
    customer=None,
):
    """Resolve QuickCard or retention attribution. Invalid input → (None, None)."""
    acquisition_source, acquisition_reference = resolve_quickcard_attribution(
        location=location,
        source=source,
        ref=ref,
    )
    if acquisition_source is not None:
        return acquisition_source, acquisition_reference
    return resolve_retention_attribution(
        location=location,
        source=source,
        ref=ref,
        customer=customer,
    )


def serialize_public_appointment(appointment: Appointment) -> dict:
    item = appointment.items.select_related("service").first()
    tz = ZoneInfo(appointment.location.timezone)
    from payments.services import appointment_requires_payment, resolve_payable_amount

    payable = resolve_payable_amount(appointment=appointment)
    return {
        "public_reference": appointment.public_reference,
        "status": appointment.status,
        "service": item.service_name if item else "",
        "location": appointment.location.name,
        "staff": appointment.staff_profile.display_name,
        "start": appointment.starts_at.astimezone(tz).isoformat(),
        "end": appointment.ends_at.astimezone(tz).isoformat(),
        "total": str(appointment.total_price),
        "currency": appointment.currency,
        "payment_status": appointment.payment_status,
        "payment_required": appointment_requires_payment(appointment=appointment),
        "payable_amount": str(payable) if payable is not None else None,
    }


def get_appointment_by_public_reference(public_reference: str) -> Appointment:
    ref = (public_reference or "").strip()
    if not ref:
        _raise("BOOKING_NOT_FOUND", "Booking not found.", status_code=404)
    appointment = (
        Appointment.objects.select_related("location", "staff_profile", "customer", "business")
        .prefetch_related("items")
        .filter(public_reference=ref)
        .first()
    )
    if appointment is None:
        _raise("BOOKING_NOT_FOUND", "Booking not found.", status_code=404)
    return appointment


def _request_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _replay_or_conflict(record: IdempotencyRecord, request_hash: str) -> tuple[dict, int, bool]:
    if record.request_hash != request_hash:
        _raise(
            "IDEMPOTENCY_CONFLICT",
            "Idempotency-Key was reused with a different request payload.",
            status_code=409,
        )
    if record.response_status == IDEMPOTENCY_PENDING:
        _raise(
            "IDEMPOTENCY_CONFLICT",
            "A request with this Idempotency-Key is already in progress.",
            status_code=409,
        )
    return record.response_body, record.response_status, True


@transaction.atomic
def create_public_appointment(
    *,
    location_id,
    service_id,
    starts_at: datetime,
    customer_name: str,
    customer_phone: str,
    customer_email: str = "",
    staff_id=None,
    idempotency_key: str | None = None,
    attribution_source: str | None = None,
    attribution_ref: str | None = None,
) -> tuple[dict, int, bool]:
    """Returns (body, http_status, is_replay)."""
    payload_for_hash = {
        "location_id": str(location_id),
        "service_id": str(service_id),
        "staff_id": str(staff_id) if staff_id else None,
        "starts_at": starts_at.isoformat(),
        "customer": {
            "name": customer_name.strip(),
            "phone": customer_phone.strip(),
            "email": (customer_email or "").strip().lower(),
        },
        "attribution_source": (attribution_source or "").strip().lower(),
        "attribution_ref": (attribution_ref or "").strip(),
    }
    request_hash = _request_hash(payload_for_hash)
    record = None

    if idempotency_key:
        try:
            with transaction.atomic():
                record = IdempotencyRecord.objects.create(
                    scope=PUBLIC_CREATE_SCOPE,
                    key=idempotency_key,
                    request_hash=request_hash,
                    response_status=IDEMPOTENCY_PENDING,
                    response_body={},
                )
        except IntegrityError:
            existing = (
                IdempotencyRecord.objects.select_for_update()
                .filter(scope=PUBLIC_CREATE_SCOPE, key=idempotency_key)
                .get()
            )
            return _replay_or_conflict(existing, request_hash)

    location = resolve_public_location(location_id)
    service = resolve_public_service(location=location, service_id=service_id)

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

    acquisition_source, acquisition_reference = resolve_public_booking_attribution(
        location=location,
        source=attribution_source,
        ref=attribution_ref,
        customer=customer,
    )

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
            acquisition_source=acquisition_source,
            acquisition_reference=acquisition_reference,
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
            if "location_id" in detail:
                _raise("INVALID_LOCATION", str(detail["location_id"]), field="location_id")
        raise

    body = serialize_public_appointment(appointment)
    # Raw manage token returned once; only the hash is stored.
    manage_token = issue_manage_token(appointment=appointment)
    body["manage_token"] = manage_token
    appointment_id = appointment.id
    transaction.on_commit(
        lambda aid=appointment_id, token=manage_token: emit(
            AppointmentBooked(appointment_id=aid, manage_token=token)
        )
    )
    if record is not None:
        record.response_status = 201
        record.response_body = body
        record.save(update_fields=["response_status", "response_body", "updated_at"])

    return body, 201, False


def serialize_managed_appointment(appointment: Appointment) -> dict:
    item = appointment.items.first()
    tz = ZoneInfo(appointment.location.timezone)
    payload = {
        "public_reference": appointment.public_reference,
        "status": appointment.status,
        "location": {
            "name": appointment.location.name,
            "slug": appointment.location.slug,
        },
        "service": {
            "name": item.service_name if item else "",
            "duration_minutes": item.duration_minutes if item else 0,
        },
        "staff": {"name": appointment.staff_profile.display_name},
        "starts_at": appointment.starts_at.astimezone(tz).isoformat(),
        "ends_at": appointment.ends_at.astimezone(tz).isoformat(),
        "customer": {"name": appointment.customer.full_name},
        "can_cancel": appointment_can_cancel(appointment),
        "is_regular_booking": appointment.booking_plan_id is not None,
    }
    if appointment.booking_plan_id:
        # Caller should attach via get_managed_appointment with token; keep flag only here.
        payload["regular_booking"] = None
    return payload


def get_managed_appointment(*, raw_token: str) -> dict:
    appointment = resolve_appointment_for_manage_token(raw_token)
    if appointment is None:
        _raise(
            "BOOKING_NOT_FOUND",
            "This booking link is invalid or has expired.",
            status_code=404,
        )
    payload = serialize_managed_appointment(appointment)
    if appointment.booking_plan_id:
        from booking.plan_services import get_regular_booking_for_manage_token

        payload["regular_booking"] = get_regular_booking_for_manage_token(raw_token=raw_token)
    return payload


def cancel_managed_appointment(*, raw_token: str, reason: str = "") -> dict:
    appointment = resolve_appointment_for_manage_token(raw_token)
    if appointment is None:
        _raise(
            "BOOKING_NOT_FOUND",
            "This booking link is invalid or has expired.",
            status_code=404,
        )
    if appointment.status == AppointmentStatus.CANCELLED:
        return {
            "public_reference": appointment.public_reference,
            "status": AppointmentStatus.CANCELLED,
            "message": "Your booking has already been cancelled.",
        }
    if not appointment_can_cancel(appointment):
        _raise(
            "CANCELLATION_NOT_ALLOWED",
            "This appointment cannot be cancelled.",
            status_code=400,
            field="status",
        )
    try:
        appointment = cancel_appointment(
            appointment=appointment,
            actor=None,
            reason=reason,
        )
    except ValidationError as exc:
        message = (
            str(exc.detail.get("status", exc.detail))
            if isinstance(exc.detail, dict)
            else str(exc.detail)
        )
        _raise(
            "CANCELLATION_NOT_ALLOWED",
            message,
            status_code=400,
            field="status",
        )
    return {
        "public_reference": appointment.public_reference,
        "status": appointment.status,
        "message": "Your booking has been cancelled.",
    }


def cancel_public_appointment(*, public_reference: str, reason: str = "") -> dict:
    appointment = get_appointment_by_public_reference(public_reference)
    try:
        appointment = cancel_appointment(
            appointment=appointment,
            actor=None,
            reason=reason,
        )
    except ValidationError as exc:
        message = (
            str(exc.detail.get("status", exc.detail))
            if isinstance(exc.detail, dict)
            else str(exc.detail)
        )
        _raise(
            "CANCELLATION_NOT_ALLOWED",
            message,
            status_code=400,
            field="status",
        )
    return serialize_public_appointment(appointment)
