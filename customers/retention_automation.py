"""Due-for-Return WhatsApp retention automation. Deterministic and rule-based."""

from __future__ import annotations

import logging
import re
from datetime import UTC, timedelta

from django.conf import settings as django_settings
from django.db import IntegrityError, transaction
from django.utils import timezone

logger = logging.getLogger("customers.retention_automation")

_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def retention_idempotency_key(*, customer_id, last_visit_at) -> str:
    stamp = last_visit_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"retention:due:{customer_id}:{stamp}"


def handle_retention_lifecycle(event) -> None:
    """Schedule/cancel retention rows on appointment completion. Never raises to booking."""
    try:
        if type(event).__name__ != "AppointmentCompleted":
            return
        appointment_id = getattr(event, "appointment_id", None)
        if appointment_id is None:
            return
        _on_appointment_completed(appointment_id)
    except Exception:
        logger.exception("retention.lifecycle_failed event=%s", type(event).__name__)


def _on_appointment_completed(appointment_id) -> None:
    from booking.models import Appointment, AppointmentStatus

    appointment = (
        Appointment.objects.select_related("customer", "business", "organization")
        .filter(pk=appointment_id, deleted_at__isnull=True)
        .first()
    )
    if appointment is None or appointment.status != AppointmentStatus.COMPLETED:
        return
    customer = appointment.customer
    if customer is None or customer.deleted_at is not None:
        return
    customer.refresh_from_db()
    cancel_stale_retention_cycles(customer=customer)
    schedule_due_retention_for_customer(customer=customer)


def cancel_stale_retention_cycles(*, customer) -> int:
    """Cancel PENDING retention rows that no longer match the current visit cycle."""
    from customers.models import CustomerRetentionMessage, CustomerRetentionMessageStatus

    if customer.last_visit_at is None:
        qs = CustomerRetentionMessage.objects.filter(
            customer_id=customer.id,
            status=CustomerRetentionMessageStatus.PENDING,
        )
    else:
        qs = CustomerRetentionMessage.objects.filter(
            customer_id=customer.id,
            status=CustomerRetentionMessageStatus.PENDING,
        ).exclude(trigger_visit_at=customer.last_visit_at)
    now = timezone.now()
    return qs.update(
        status=CustomerRetentionMessageStatus.CANCELLED,
        cancelled_at=now,
        skip_reason="visit_cycle_changed",
        updated_at=now,
    )


def schedule_due_retention_for_customer(*, customer, settings=None, now=None):
    """Create PENDING Due-for-Return message for the current visit cycle when automation is on."""
    from customers.models import (
        CustomerRetentionMessage,
        CustomerRetentionMessageStatus,
        RetentionSegment,
    )
    from customers.services import get_or_create_retention_settings

    moment = now or timezone.now()
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment, UTC)
    if customer.last_visit_at is None or customer.total_visits < 2:
        return None
    if settings is None:
        settings = get_or_create_retention_settings(
            organization=customer.organization,
            business=customer.business,
        )
    if not settings.enabled:
        return None
    if customer.business.deleted_at is not None or not customer.business.is_active:
        return None

    key = retention_idempotency_key(
        customer_id=customer.id,
        last_visit_at=customer.last_visit_at,
    )
    existing = CustomerRetentionMessage.objects.filter(idempotency_key=key).first()
    if existing is not None:
        return existing

    scheduled_for = customer.last_visit_at + timedelta(
        days=settings.return_after_days,
        hours=settings.due_message_delay_hours,
    )
    try:
        return CustomerRetentionMessage.objects.create(
            organization_id=customer.organization_id,
            business_id=customer.business_id,
            customer=customer,
            segment=RetentionSegment.DUE_FOR_RETURN,
            trigger_visit_at=customer.last_visit_at,
            scheduled_for=scheduled_for,
            status=CustomerRetentionMessageStatus.PENDING,
            idempotency_key=key,
        )
    except IntegrityError:
        return CustomerRetentionMessage.objects.filter(idempotency_key=key).first()


def schedule_eligible_due_customers(*, now=None, batch_size: int = 200) -> int:
    """Catch-up: schedule DUE customers who have no cycle row yet."""
    from customers.models import (
        Customer,
        CustomerRetentionMessage,
        CustomerRetentionSettings,
        RetentionSegment,
    )
    from customers.services import filter_customers_by_segment

    moment = now or timezone.now()
    created = 0
    for settings in CustomerRetentionSettings.objects.filter(enabled=True).select_related(
        "business", "organization"
    ):
        if settings.business.deleted_at is not None or not settings.business.is_active:
            continue
        qs = Customer.objects.filter(
            organization_id=settings.organization_id,
            business_id=settings.business_id,
        )
        due = filter_customers_by_segment(
            queryset=qs,
            segment=RetentionSegment.DUE_FOR_RETURN,
            settings=settings,
        ).order_by("id")[:batch_size]
        for customer in due:
            key = retention_idempotency_key(
                customer_id=customer.id,
                last_visit_at=customer.last_visit_at,
            )
            if CustomerRetentionMessage.objects.filter(idempotency_key=key).exists():
                continue
            # Past the ideal send time: still wait delay hours from discovery.
            ideal = customer.last_visit_at + timedelta(
                days=settings.return_after_days,
                hours=settings.due_message_delay_hours,
            )
            scheduled_for = (
                ideal
                if ideal > moment
                else moment + timedelta(hours=settings.due_message_delay_hours)
            )
            try:
                CustomerRetentionMessage.objects.create(
                    organization_id=customer.organization_id,
                    business_id=customer.business_id,
                    customer=customer,
                    segment=RetentionSegment.DUE_FOR_RETURN,
                    trigger_visit_at=customer.last_visit_at,
                    scheduled_for=scheduled_for,
                    status="PENDING",
                    idempotency_key=key,
                )
                created += 1
            except IntegrityError:
                continue
    return created


def process_due_retention_messages(*, now=None) -> dict:
    """Revalidate and queue due retention WhatsApp messages."""
    from customers.models import CustomerRetentionMessage, CustomerRetentionMessageStatus

    moment = now or timezone.now()
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment, UTC)

    scheduled = schedule_eligible_due_customers(now=moment)
    ids = list(
        CustomerRetentionMessage.objects.filter(
            status=CustomerRetentionMessageStatus.PENDING,
            scheduled_for__lte=moment,
        )
        .order_by("scheduled_for")
        .values_list("id", flat=True)[:200]
    )
    queued = skipped = failed = 0
    for message_id in ids:
        outcome = _process_one(message_id, now=moment)
        if outcome == "queued":
            queued += 1
        elif outcome == "failed":
            failed += 1
        else:
            skipped += 1
    return {
        "seen": len(ids),
        "queued": queued,
        "skipped": skipped,
        "failed": failed,
        "scheduled": scheduled,
    }


def _process_one(message_id, *, now) -> str:
    from customers.models import (
        CustomerRetentionMessage,
        CustomerRetentionMessageStatus,
        RetentionSegment,
    )
    from customers.services import (
        get_customer_retention_status,
        get_or_create_retention_settings,
    )
    from messaging.models import (
        WhatsAppAccount,
        WhatsAppConnectionStatus,
        WhatsAppMessageStatus,
        WhatsAppMessageType,
        WhatsAppTemplatePurpose,
    )
    from messaging.services import queue_whatsapp_message

    with transaction.atomic():
        row = (
            CustomerRetentionMessage.objects.select_for_update()
            .select_related(
                "customer",
                "customer__business",
                "business",
                "organization",
            )
            .filter(pk=message_id)
            .first()
        )
        if row is None or row.status != CustomerRetentionMessageStatus.PENDING:
            return "skipped"

        def skip(code: str) -> str:
            row.status = CustomerRetentionMessageStatus.SKIPPED
            row.skip_reason = code[:64]
            row.save(update_fields=["status", "skip_reason", "updated_at"])
            return "skipped"

        customer = row.customer
        if customer.deleted_at is not None:
            return skip("customer_inactive")
        business = row.business
        if business.deleted_at is not None or not business.is_active:
            return skip("business_inactive")

        settings = get_or_create_retention_settings(
            organization=row.organization,
            business=business,
        )
        if not settings.enabled:
            return skip("automation_disabled")

        if customer.last_visit_at != row.trigger_visit_at:
            row.status = CustomerRetentionMessageStatus.CANCELLED
            row.cancelled_at = now
            row.skip_reason = "visit_cycle_changed"
            row.save(update_fields=["status", "cancelled_at", "skip_reason", "updated_at"])
            return "skipped"

        status = get_customer_retention_status(customer=customer, settings=settings)
        if status["segment"] != RetentionSegment.DUE_FOR_RETURN:
            return skip("segment_changed")

        phone = (customer.phone or "").strip()
        if not phone or not _E164_RE.match(phone):
            return skip("invalid_phone")
        if not customer.whatsapp_opt_in:
            return skip("opt_out")

        if not WhatsAppAccount.objects.filter(
            organization_id=row.organization_id,
            business_id=row.business_id,
            deleted_at__isnull=True,
            status=WhatsAppConnectionStatus.CONNECTED,
        ).exists():
            return skip("not_connected")

        template = _approved_retention_template(business_id=row.business_id)
        if template is None:
            return skip("no_template")

        location = _booking_location_for_customer(customer)
        if location is None:
            return skip("no_booking_url")

        row.location = location
        names = list(template.variables or [])
        values, rendered = render_retention_template(
            customer=customer,
            business=business,
            location=location,
            body=template.body,
            names=names,
            retention_message=row,
        )
        message = queue_whatsapp_message(
            organization=row.organization,
            business_id=row.business_id,
            phone_number=phone,
            message_type=WhatsAppMessageType.TEMPLATE,
            template_name=template.name,
            template_language=template.language,
            variables=values,
            rendered_text=rendered,
            customer_id=customer.id,
            idempotency_key=row.idempotency_key,
            purpose=WhatsAppTemplatePurpose.RETENTION_DUE_RETURN,
        )
        row.whatsapp_message = message
        if message.status == WhatsAppMessageStatus.SENT:
            row.status = CustomerRetentionMessageStatus.SENT
            row.sent_at = message.sent_at or now
        elif message.status == WhatsAppMessageStatus.FAILED:
            row.status = CustomerRetentionMessageStatus.FAILED
            row.skip_reason = (message.failure_code or "provider_failed")[:64]
        else:
            row.status = CustomerRetentionMessageStatus.QUEUED
        row.save()
        return "failed" if row.status == CustomerRetentionMessageStatus.FAILED else "queued"


def _approved_retention_template(*, business_id):
    from messaging.models import (
        MessageTemplate,
        WhatsAppTemplateCategory,
        WhatsAppTemplatePurpose,
        WhatsAppTemplateStatus,
    )
    from messaging.variables import DEFAULT_TEMPLATE_LANGUAGE

    return (
        MessageTemplate.objects.filter(
            business_id=business_id,
            purpose=WhatsAppTemplatePurpose.RETENTION_DUE_RETURN,
            category=WhatsAppTemplateCategory.RETENTION,
            language=DEFAULT_TEMPLATE_LANGUAGE,
            status=WhatsAppTemplateStatus.APPROVED,
            provider_status=WhatsAppTemplateStatus.APPROVED,
            deleted_at__isnull=True,
        )
        .order_by("created_at")
        .first()
    )


def _booking_location_for_customer(customer):
    from booking.models import Appointment, AppointmentStatus

    appointment = (
        Appointment.objects.filter(
            customer_id=customer.id,
            organization_id=customer.organization_id,
            business_id=customer.business_id,
            status=AppointmentStatus.COMPLETED,
        )
        .select_related("location")
        .order_by("-completed_at", "-ends_at")
        .first()
    )
    if appointment is not None and appointment.location_id:
        return appointment.location
    from locations.models import Location

    return (
        Location.objects.filter(
            business_id=customer.business_id,
            organization_id=customer.organization_id,
            is_active=True,
        )
        .order_by("created_at")
        .first()
    )


def render_retention_template(
    *,
    customer,
    business,
    location,
    body: str,
    names: list[str],
    retention_message=None,
):
    """Resolve allowlisted retention variables. Restricted to identity + booking URL."""
    from messaging.variables import ALLOWED_TEMPLATE_VARIABLES

    slug = getattr(location, "slug", "") or ""
    base = (getattr(django_settings, "PUBLIC_APP_URL", "") or "http://localhost:3000").rstrip("/")
    booking_url = ""
    if slug:
        booking_url = f"{base}/book/{slug}"
        if retention_message is not None and retention_message.public_reference:
            booking_url = f"{booking_url}?source=retention&ref={retention_message.public_reference}"
    values_map = {
        "customer_name": customer.full_name if customer is not None else "",
        "business_name": getattr(business, "name", "") or "",
        "booking_url": booking_url,
    }
    ordered = [
        values_map.get(name, "") if name in ALLOWED_TEMPLATE_VARIABLES else "" for name in names
    ]
    text = body or ""
    for name, value in values_map.items():
        text = text.replace("{{" + name + "}}", value)
    return ordered, text[:4000]


def note_retention_message_delivery(message) -> None:
    """Mirror WhatsAppMessage delivery status onto CustomerRetentionMessage."""
    from customers.models import CustomerRetentionMessage, CustomerRetentionMessageStatus
    from messaging.models import WhatsAppMessageStatus

    row = CustomerRetentionMessage.objects.filter(whatsapp_message_id=message.id).first()
    if row is None:
        return
    if message.status == WhatsAppMessageStatus.SENT:
        row.status = CustomerRetentionMessageStatus.SENT
        row.sent_at = message.sent_at or timezone.now()
        row.save(update_fields=["status", "sent_at", "updated_at"])
    elif message.status == WhatsAppMessageStatus.FAILED:
        row.status = CustomerRetentionMessageStatus.FAILED
        row.skip_reason = (message.failure_code or "provider_failed")[:64]
        row.save(update_fields=["status", "skip_reason", "updated_at"])
    elif message.status == WhatsAppMessageStatus.CANCELLED:
        row.status = CustomerRetentionMessageStatus.CANCELLED
        row.cancelled_at = timezone.now()
        row.skip_reason = "whatsapp_cancelled"
        row.save(update_fields=["status", "cancelled_at", "skip_reason", "updated_at"])


def get_customer_retention_automation_status(*, customer) -> dict | None:
    """Latest automation row for the current visit cycle (read-only for owners)."""
    from customers.models import CustomerRetentionMessage

    if customer.last_visit_at is None:
        latest = (
            CustomerRetentionMessage.objects.filter(customer_id=customer.id)
            .order_by("-created_at")
            .first()
        )
    else:
        latest = (
            CustomerRetentionMessage.objects.filter(
                customer_id=customer.id,
                trigger_visit_at=customer.last_visit_at,
            )
            .order_by("-created_at")
            .first()
        )
        if latest is None:
            latest = (
                CustomerRetentionMessage.objects.filter(customer_id=customer.id)
                .order_by("-created_at")
                .first()
            )
    if latest is None:
        return None
    return {
        "status": latest.status,
        "scheduled_for": latest.scheduled_for,
        "sent_at": latest.sent_at,
        "skip_reason": latest.skip_reason or None,
    }
