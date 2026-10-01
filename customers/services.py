from __future__ import annotations

import re
from decimal import Decimal

from django.db import IntegrityError, models, transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from businesses.services import get_business_for_organization
from customers.models import Customer, CustomerTag, CustomerTagAssignment

# E.164: + then country code and subscriber number (max 15 digits total after +).
_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def _normalize_phone(value: str) -> str:
    phone = (value or "").strip().replace(" ", "").replace("-", "")
    if not phone:
        raise ValidationError({"phone": "This field may not be blank."})
    if not _E164_RE.match(phone):
        raise ValidationError({"phone": "Enter a valid E.164 phone number (e.g. +919876543210)."})
    return phone


def _normalize_email(value: str | None) -> str:
    if value is None:
        return ""
    email = value.strip().lower()
    return email


def _normalize_name(value: str, field: str) -> str:
    name = (value or "").strip()
    if field == "first_name" and not name:
        raise ValidationError({field: "This field may not be blank."})
    return name


def list_customers(*, organization, business):
    return (
        Customer.objects.filter(organization=organization, business=business)
        .prefetch_related("tag_assignments__tag")
        .order_by("last_name", "first_name")
    )


def get_customer_for_business(*, organization, business, customer_id) -> Customer:
    return get_object_or_404(
        Customer.objects.prefetch_related("tag_assignments__tag"),
        organization=organization,
        business=business,
        pk=customer_id,
    )


def _completed_visit_stats(*, customer_id, organization_id, business_id) -> dict:
    """Aggregate live COMPLETED appointments for one customer in their business."""
    from django.db.models import Count, Max, Min
    from django.db.models.functions import Coalesce

    from booking.models import Appointment, AppointmentStatus

    return Appointment.objects.filter(
        customer_id=customer_id,
        organization_id=organization_id,
        business_id=business_id,
        status=AppointmentStatus.COMPLETED,
    ).aggregate(
        total=Count("id"),
        first=Min(Coalesce("completed_at", "ends_at")),
        last=Max(Coalesce("completed_at", "ends_at")),
    )


def refresh_customer_visit_totals(*, customer_id) -> Customer | None:
    """Recalculate total_visits / first_visit_at / last_visit_at from COMPLETED appointments.

    Soft-deleted appointments are excluded by the default Appointment manager.
    Historical COMPLETED rows without completed_at use ends_at for visit timestamps.
    """
    customer = Customer.objects.select_for_update().filter(pk=customer_id).first()
    if customer is None:
        return None

    stats = _completed_visit_stats(
        customer_id=customer.id,
        organization_id=customer.organization_id,
        business_id=customer.business_id,
    )
    customer.total_visits = stats["total"] or 0
    customer.first_visit_at = stats["first"]
    customer.last_visit_at = stats["last"]
    customer.save(update_fields=["total_visits", "first_visit_at", "last_visit_at", "updated_at"])
    return customer


RECENT_VISITS_LIMIT = 10


def _completed_appointments_qs(*, customer_id, organization_id, business_id):
    from booking.models import Appointment, AppointmentStatus

    return Appointment.objects.filter(
        customer_id=customer_id,
        organization_id=organization_id,
        business_id=business_id,
        status=AppointmentStatus.COMPLETED,
    )


def _average_days_between_visits(*, total_visits: int, first_visit_at, last_visit_at):
    """Historical average interval. Null when fewer than two completed visits."""
    if total_visits < 2 or first_visit_at is None or last_visit_at is None:
        return None
    elapsed_days = (last_visit_at - first_visit_at).total_seconds() / 86400
    return round(elapsed_days / (total_visits - 1), 1)


def _serialize_recent_visit(appointment) -> dict:
    item = next(iter(appointment.items.all()), None)
    visit_at = appointment.completed_at or appointment.ends_at
    return {
        "appointment_reference": appointment.public_reference,
        "completed_at": visit_at,
        "location": appointment.location.name if appointment.location_id else "",
        "staff": (appointment.staff_profile.display_name if appointment.staff_profile_id else ""),
        "service": item.service_name if item else "",
        "price_snapshot": str(appointment.total_price),
        "currency": appointment.currency,
    }


def _recent_completed_visits(*, customer_id, organization_id, business_id) -> list[dict]:
    from django.db.models import Prefetch
    from django.db.models.functions import Coalesce

    from booking.models import AppointmentItem

    qs = (
        _completed_appointments_qs(
            customer_id=customer_id,
            organization_id=organization_id,
            business_id=business_id,
        )
        .select_related("location", "staff_profile")
        .prefetch_related(
            Prefetch(
                "items",
                queryset=AppointmentItem.objects.only(
                    "id",
                    "appointment_id",
                    "service_name",
                    "price",
                    "currency",
                ),
            )
        )
        .annotate(visit_at=Coalesce("completed_at", "ends_at"))
        .order_by("-visit_at")[:RECENT_VISITS_LIMIT]
    )
    return [_serialize_recent_visit(row) for row in qs]


def _service_visit_history(*, customer_id, organization_id, business_id) -> list[dict]:
    from django.db.models import Count, Max
    from django.db.models.functions import Coalesce

    from booking.models import AppointmentItem, AppointmentStatus

    rows = (
        AppointmentItem.objects.filter(
            appointment__customer_id=customer_id,
            appointment__organization_id=organization_id,
            appointment__business_id=business_id,
            appointment__status=AppointmentStatus.COMPLETED,
            appointment__deleted_at__isnull=True,
        )
        .values("service_name")
        .annotate(
            visit_count=Count("appointment_id", distinct=True),
            last_visit_at=Max(Coalesce("appointment__completed_at", "appointment__ends_at")),
        )
        .order_by("-visit_count", "service_name")
    )
    return [
        {
            "service_name": row["service_name"],
            "visit_count": row["visit_count"],
            "last_visit_at": row["last_visit_at"],
        }
        for row in rows
    ]


def _staff_visit_history(*, customer_id, organization_id, business_id) -> list[dict]:
    from django.db.models import Count, Max
    from django.db.models.functions import Coalesce

    rows = (
        _completed_appointments_qs(
            customer_id=customer_id,
            organization_id=organization_id,
            business_id=business_id,
        )
        .values("staff_profile__display_name")
        .annotate(
            visit_count=Count("id"),
            last_visit_at=Max(Coalesce("completed_at", "ends_at")),
        )
        .order_by("-visit_count", "staff_profile__display_name")
    )
    return [
        {
            "staff_name": row["staff_profile__display_name"] or "",
            "visit_count": row["visit_count"],
            "last_visit_at": row["last_visit_at"],
        }
        for row in rows
    ]


def _location_visit_history(*, customer_id, organization_id, business_id) -> list[dict]:
    from django.db.models import Count, Max
    from django.db.models.functions import Coalesce

    rows = (
        _completed_appointments_qs(
            customer_id=customer_id,
            organization_id=organization_id,
            business_id=business_id,
        )
        .values("location__name")
        .annotate(
            visit_count=Count("id"),
            last_visit_at=Max(Coalesce("completed_at", "ends_at")),
        )
        .order_by("-visit_count", "location__name")
    )
    return [
        {
            "location_name": row["location__name"] or "",
            "visit_count": row["visit_count"],
            "last_visit_at": row["last_visit_at"],
        }
        for row in rows
    ]


def days_since_last_visit(*, customer: Customer) -> int | None:
    """UTC calendar-day delta from last_visit_at. Null when there is no completed visit."""
    if customer.last_visit_at is None:
        return None
    from django.utils import timezone

    return max(0, (timezone.now() - customer.last_visit_at).days)


def get_or_create_retention_settings(*, organization, business, actor=None):
    """Return business retention settings, creating defaults when missing."""
    from customers.models import CustomerRetentionSettings

    settings, _created = CustomerRetentionSettings.objects.get_or_create(
        business=business,
        defaults={
            "organization": organization,
            "return_after_days": CustomerRetentionSettings.DEFAULT_RETURN_AFTER_DAYS,
            "inactive_after_days": CustomerRetentionSettings.DEFAULT_INACTIVE_AFTER_DAYS,
            "due_message_delay_hours": CustomerRetentionSettings.DEFAULT_DUE_MESSAGE_DELAY_HOURS,
            "enabled": True,
            "created_by": actor,
            "updated_by": actor,
        },
    )
    return settings


def serialize_retention_settings(settings) -> dict:
    return {
        "return_after_days": settings.return_after_days,
        "inactive_after_days": settings.inactive_after_days,
        "due_message_delay_hours": settings.due_message_delay_hours,
        "enabled": settings.enabled,
        "updated_at": settings.updated_at,
    }


def update_retention_settings(*, settings, actor, **fields):
    """Validate and update business retention thresholds. OWNER-only at the view layer."""
    from rest_framework.exceptions import ValidationError

    return_after = fields.get("return_after_days", settings.return_after_days)
    inactive_after = fields.get("inactive_after_days", settings.inactive_after_days)
    delay_hours = fields.get("due_message_delay_hours", settings.due_message_delay_hours)
    enabled = fields.get("enabled", settings.enabled)

    if return_after is None or int(return_after) < 1:
        raise ValidationError({"return_after_days": "Must be a positive integer."})
    if inactive_after is None or int(inactive_after) < 1:
        raise ValidationError({"inactive_after_days": "Must be a positive integer."})
    if delay_hours is None or int(delay_hours) < 1:
        raise ValidationError({"due_message_delay_hours": "Must be a positive integer."})
    return_after = int(return_after)
    inactive_after = int(inactive_after)
    delay_hours = int(delay_hours)
    if inactive_after <= return_after:
        raise ValidationError({"inactive_after_days": "Must be greater than return_after_days."})

    settings.return_after_days = return_after
    settings.inactive_after_days = inactive_after
    settings.due_message_delay_hours = delay_hours
    settings.enabled = bool(enabled)
    settings.updated_by = actor
    try:
        settings.save(
            update_fields=[
                "return_after_days",
                "inactive_after_days",
                "due_message_delay_hours",
                "enabled",
                "updated_by",
                "updated_at",
            ]
        )
    except IntegrityError as exc:
        raise ValidationError(
            {"inactive_after_days": "Must be greater than return_after_days."}
        ) from exc
    return settings


def classify_retention_segment(
    *,
    total_visits: int,
    days_since: int | None,
    return_after_days: int,
    inactive_after_days: int,
) -> str:
    """Deterministic primary segment. Priority: NO_VISITS → NEW → INACTIVE → DUE → RETURNING."""
    from customers.models import RetentionSegment

    if total_visits <= 0 or days_since is None:
        return RetentionSegment.NO_VISITS
    if total_visits == 1:
        return RetentionSegment.NEW
    if days_since >= inactive_after_days:
        return RetentionSegment.INACTIVE
    if days_since >= return_after_days:
        return RetentionSegment.DUE_FOR_RETURN
    return RetentionSegment.RETURNING


def get_customer_retention_status(*, customer: Customer, settings=None) -> dict:
    """Factual segment from visit counters and business thresholds. Not a prediction."""
    if settings is None:
        settings = get_or_create_retention_settings(
            organization=customer.organization,
            business=customer.business,
        )
    days = days_since_last_visit(customer=customer)
    segment = classify_retention_segment(
        total_visits=customer.total_visits,
        days_since=days,
        return_after_days=settings.return_after_days,
        inactive_after_days=settings.inactive_after_days,
    )
    return {
        "segment": segment,
        "days_since_last_visit": days,
        "return_after_days": settings.return_after_days,
        "inactive_after_days": settings.inactive_after_days,
    }


def filter_customers_by_segment(*, queryset, segment: str, settings):
    """Apply DB-level segment filter using stored visit fields + thresholds."""
    from datetime import timedelta

    from django.db.models import Q
    from django.utils import timezone

    from customers.models import RetentionSegment

    if segment not in RetentionSegment.values:
        return queryset.none()

    if segment == RetentionSegment.NO_VISITS:
        return queryset.filter(Q(total_visits=0) | Q(last_visit_at__isnull=True))

    if segment == RetentionSegment.NEW:
        return queryset.filter(total_visits=1)

    now = timezone.now()
    return_cutoff = now - timedelta(days=settings.return_after_days)
    inactive_cutoff = now - timedelta(days=settings.inactive_after_days)
    multi = Q(total_visits__gte=2, last_visit_at__isnull=False)

    if segment == RetentionSegment.INACTIVE:
        return queryset.filter(multi, last_visit_at__lte=inactive_cutoff)

    if segment == RetentionSegment.DUE_FOR_RETURN:
        return queryset.filter(
            multi,
            last_visit_at__lte=return_cutoff,
            last_visit_at__gt=inactive_cutoff,
        )

    # RETURNING
    return queryset.filter(multi, last_visit_at__gt=return_cutoff)


def get_customer_retention_summary(*, customer: Customer) -> dict:
    """Factual visit history for retention. No predictions or campaign thresholds."""
    total = customer.total_visits
    scope = {
        "customer_id": customer.id,
        "organization_id": customer.organization_id,
        "business_id": customer.business_id,
    }
    status = get_customer_retention_status(customer=customer)
    from customers.retention_automation import get_customer_retention_automation_status

    return {
        "customer_id": str(customer.id),
        "total_visits": total,
        "completed_appointments": total,
        "first_visit_at": customer.first_visit_at,
        "last_visit_at": customer.last_visit_at,
        "days_since_last_visit": status["days_since_last_visit"],
        "average_days_between_visits": _average_days_between_visits(
            total_visits=total,
            first_visit_at=customer.first_visit_at,
            last_visit_at=customer.last_visit_at,
        ),
        "segment": status["segment"],
        "return_after_days": status["return_after_days"],
        "inactive_after_days": status["inactive_after_days"],
        "automation": get_customer_retention_automation_status(customer=customer),
        "visits": _recent_completed_visits(**scope),
        "service_history": _service_visit_history(**scope),
        "staff_history": _staff_visit_history(**scope),
        "location_history": _location_visit_history(**scope),
    }


def reconcile_customer_visit_totals(
    *,
    organization_id=None,
    business_id=None,
    batch_size: int = 500,
) -> dict:
    """Recalculate visit totals for live customers. Safe to run repeatedly."""
    from django.db.models import Count, Max, Min
    from django.db.models.functions import Coalesce

    from booking.models import Appointment, AppointmentStatus

    # Historical COMPLETED rows may lack completed_at; use ends_at as the visit time.
    historical = Appointment.objects.filter(
        status=AppointmentStatus.COMPLETED,
        completed_at__isnull=True,
    )
    if organization_id is not None:
        historical = historical.filter(organization_id=organization_id)
    if business_id is not None:
        historical = historical.filter(business_id=business_id)
    historical.update(completed_at=models.F("ends_at"))

    visits = Appointment.objects.filter(status=AppointmentStatus.COMPLETED)
    if organization_id is not None:
        visits = visits.filter(organization_id=organization_id)
    if business_id is not None:
        visits = visits.filter(business_id=business_id)
    by_customer = {
        row["customer_id"]: row
        for row in visits.values("customer_id").annotate(
            total=Count("id"),
            first=Min(Coalesce("completed_at", "ends_at")),
            last=Max(Coalesce("completed_at", "ends_at")),
        )
    }

    qs = Customer.objects.all().order_by("id")
    if organization_id is not None:
        qs = qs.filter(organization_id=organization_id)
    if business_id is not None:
        qs = qs.filter(business_id=business_id)

    processed = 0
    updated = 0
    for customer in qs.iterator(chunk_size=batch_size):
        processed += 1
        row = by_customer.get(customer.id)
        total = row["total"] if row else 0
        first = row["first"] if row else None
        last = row["last"] if row else None
        if (
            customer.total_visits != total
            or customer.first_visit_at != first
            or customer.last_visit_at != last
        ):
            Customer.objects.filter(pk=customer.pk).update(
                total_visits=total,
                first_visit_at=first,
                last_visit_at=last,
            )
            updated += 1
    return {"processed": processed, "updated": updated}


def _ensure_unique_phone(*, business, phone: str, exclude_id=None) -> None:
    qs = Customer.objects.filter(business=business, phone=phone)
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    if qs.exists():
        raise ValidationError(
            {"phone": "A customer with this phone already exists for this business."}
        )


def normalize_public_phone(value: str) -> str:
    """Accept E.164 or a 10-digit Indian mobile; store as E.164."""
    phone = (value or "").strip().replace(" ", "").replace("-", "")
    if re.fullmatch(r"[6-9]\d{9}", phone):
        phone = f"+91{phone}"
    return _normalize_phone(phone)


@transaction.atomic
def get_or_create_customer_by_phone(
    *,
    organization,
    business,
    name: str,
    phone: str,
    email: str = "",
) -> Customer:
    """Public booking customer match: phone primary within the business."""
    phone = normalize_public_phone(phone)
    existing = Customer.objects.filter(
        organization=organization, business=business, phone=phone
    ).first()
    if existing is not None:
        return existing

    parts = (name or "").strip().split(None, 1)
    if not parts:
        raise ValidationError({"name": "This field may not be blank."})
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else ""
    return create_customer(
        organization=organization,
        business_id=business.id,
        actor=None,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        email=email or "",
    )


@transaction.atomic
def create_customer(
    *,
    organization,
    business_id,
    actor,
    first_name: str,
    phone: str,
    last_name: str = "",
    email: str = "",
    date_of_birth=None,
    notes: str = "",
    marketing_opt_in: bool = False,
    whatsapp_opt_in: bool = False,
) -> Customer:
    business = get_business_for_organization(
        organization=organization,
        business_id=business_id,
    )
    first_name = _normalize_name(first_name, "first_name")
    last_name = _normalize_name(last_name, "last_name")
    phone = _normalize_phone(phone)
    email = _normalize_email(email)
    _ensure_unique_phone(business=business, phone=phone)

    try:
        return Customer.objects.create(
            organization=organization,
            business=business,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            email=email,
            date_of_birth=date_of_birth,
            notes=notes or "",
            marketing_opt_in=marketing_opt_in,
            whatsapp_opt_in=whatsapp_opt_in,
            total_visits=0,
            total_spend=Decimal("0.00"),
            created_by=actor,
            updated_by=actor,
        )
    except IntegrityError as exc:
        raise ValidationError(
            {"phone": "A customer with this phone already exists for this business."}
        ) from exc


@transaction.atomic
def update_customer(*, customer: Customer, actor, **fields) -> Customer:
    if "first_name" in fields:
        customer.first_name = _normalize_name(fields["first_name"], "first_name")
    if "last_name" in fields:
        customer.last_name = _normalize_name(fields["last_name"], "last_name")
    if "phone" in fields:
        phone = _normalize_phone(fields["phone"])
        _ensure_unique_phone(
            business=customer.business,
            phone=phone,
            exclude_id=customer.pk,
        )
        customer.phone = phone
    if "email" in fields:
        customer.email = _normalize_email(fields["email"])
    if "date_of_birth" in fields:
        customer.date_of_birth = fields["date_of_birth"]
    if "notes" in fields:
        customer.notes = fields["notes"] or ""
    if "marketing_opt_in" in fields:
        customer.marketing_opt_in = fields["marketing_opt_in"]
    if "whatsapp_opt_in" in fields:
        customer.whatsapp_opt_in = fields["whatsapp_opt_in"]

    customer.updated_by = actor
    try:
        customer.save()
    except IntegrityError as exc:
        raise ValidationError(
            {"phone": "A customer with this phone already exists for this business."}
        ) from exc
    return customer


@transaction.atomic
def soft_delete_customer(*, customer: Customer, actor) -> None:
    CustomerTagAssignment.objects.filter(customer=customer).delete()
    customer.soft_delete(actor=actor)
    customer.updated_by = actor
    customer.save(update_fields=["updated_by", "updated_at"])


def list_customer_tags(*, organization, business):
    return CustomerTag.objects.filter(
        organization=organization,
        business=business,
    ).order_by("name")


def get_customer_tag_for_business(*, organization, business, tag_id) -> CustomerTag:
    return get_object_or_404(
        CustomerTag,
        organization=organization,
        business=business,
        pk=tag_id,
    )


def _ensure_unique_tag_name(*, business, name: str, exclude_id=None) -> None:
    qs = CustomerTag.objects.filter(business=business, name__iexact=name)
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    if qs.exists():
        raise ValidationError({"name": "A tag with this name already exists for this business."})


@transaction.atomic
def create_customer_tag(
    *,
    organization,
    business_id,
    actor,
    name: str,
) -> CustomerTag:
    business = get_business_for_organization(
        organization=organization,
        business_id=business_id,
    )
    name = (name or "").strip()
    if not name:
        raise ValidationError({"name": "This field may not be blank."})
    _ensure_unique_tag_name(business=business, name=name)

    try:
        return CustomerTag.objects.create(
            organization=organization,
            business=business,
            name=name,
            created_by=actor,
            updated_by=actor,
        )
    except IntegrityError as exc:
        raise ValidationError(
            {"name": "A tag with this name already exists for this business."}
        ) from exc


@transaction.atomic
def update_customer_tag(*, tag: CustomerTag, actor, **fields) -> CustomerTag:
    if "name" in fields:
        name = (fields["name"] or "").strip()
        if not name:
            raise ValidationError({"name": "This field may not be blank."})
        _ensure_unique_tag_name(
            business=tag.business,
            name=name,
            exclude_id=tag.pk,
        )
        tag.name = name

    tag.updated_by = actor
    try:
        tag.save()
    except IntegrityError as exc:
        raise ValidationError(
            {"name": "A tag with this name already exists for this business."}
        ) from exc
    return tag


@transaction.atomic
def delete_customer_tag(*, tag: CustomerTag) -> None:
    tag.delete()


def list_customer_tag_assignments(*, organization, customer: Customer):
    return (
        CustomerTagAssignment.objects.filter(
            organization=organization,
            customer=customer,
        )
        .select_related("tag")
        .order_by("created_at")
    )


def get_customer_tag_assignment(
    *,
    organization,
    customer: Customer,
    assignment_id,
) -> CustomerTagAssignment:
    return get_object_or_404(
        CustomerTagAssignment.objects.select_related("tag"),
        organization=organization,
        customer=customer,
        pk=assignment_id,
    )


@transaction.atomic
def assign_customer_tag(
    *,
    organization,
    business,
    customer: Customer,
    actor,
    tag_id,
) -> CustomerTagAssignment:
    tag = get_customer_tag_for_business(
        organization=organization,
        business=business,
        tag_id=tag_id,
    )
    if customer.business_id != business.id or tag.business_id != business.id:
        raise ValidationError({"tag_id": "Customer and tag must belong to the same business."})
    if CustomerTagAssignment.objects.filter(customer=customer, tag=tag).exists():
        raise ValidationError({"tag_id": "This tag is already assigned to the customer."})

    try:
        return CustomerTagAssignment.objects.create(
            organization=organization,
            customer=customer,
            tag=tag,
            created_by=actor,
            updated_by=actor,
        )
    except IntegrityError as exc:
        raise ValidationError({"tag_id": "This tag is already assigned to the customer."}) from exc


@transaction.atomic
def remove_customer_tag_assignment(*, assignment: CustomerTagAssignment) -> None:
    assignment.delete()
