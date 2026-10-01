"""Durable 24-hour appointment reminders for businesses with their own WhatsApp account."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from messaging.models import (
    AppointmentReminder,
    AppointmentReminderStatus,
    AppointmentReminderType,
    MessageTemplate,
    WhatsAppAccount,
    WhatsAppConnectionStatus,
    WhatsAppMessage,
    WhatsAppMessageStatus,
    WhatsAppMessageType,
    WhatsAppTemplateCategory,
    WhatsAppTemplatePurpose,
    WhatsAppTemplateStatus,
)
from messaging.variables import DEFAULT_TEMPLATE_LANGUAGE, render_template_snapshot

logger = logging.getLogger("messaging.reminders")

_SPECS = (
    (AppointmentReminderType.APPOINTMENT_REMINDER_24H, timedelta(hours=24), "24h"),
    (AppointmentReminderType.APPOINTMENT_REMINDER_1H, timedelta(hours=1), "1h"),
)
_REMINDER_TYPES = {item[0] for item in _SPECS}
_REVIEW_TYPE = AppointmentReminderType.REVIEW_REQUEST
_DUE_TYPES = _REMINDER_TYPES | {_REVIEW_TYPE}
_ACTIVE = {
    AppointmentReminderStatus.PENDING,
    AppointmentReminderStatus.QUEUED,
}


def business_uses_messaging_reminders(*, business_id) -> bool:
    """True when a connected account owns the 24h reminder."""
    return WhatsAppAccount.objects.filter(
        business_id=business_id,
        deleted_at__isnull=True,
        status=WhatsAppConnectionStatus.CONNECTED,
    ).exists()


def handle_reminder_lifecycle(event) -> None:
    try:
        name = type(event).__name__
        appointment_id = getattr(event, "appointment_id", None)
        if appointment_id is None:
            return
        if name == "AppointmentConfirmed":
            _schedule_for_appointment_id(appointment_id)
        elif name == "AppointmentRescheduled":
            _reschedule(appointment_id)
        elif name == "AppointmentCancelled":
            _cancel_active(appointment_id, reason="appointmentcancelled")
        elif name == "AppointmentCompleted":
            _cancel_active(
                appointment_id,
                reason="appointmentcompleted",
                notification_types=_REMINDER_TYPES,
            )
            _schedule_review(appointment_id)
    except Exception:
        logger.exception("whatsapp.reminder_hook_failed event=%s", type(event).__name__)


def process_due_appointment_reminders(*, now=None) -> dict:
    """Queue due reminders. Network calls happen later in the delivery task."""
    moment = now or timezone.now()
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment, timezone.UTC)
    ids = list(
        AppointmentReminder.objects.filter(
            status=AppointmentReminderStatus.PENDING,
            notification_type__in=_DUE_TYPES,
            scheduled_for__lte=moment,
        )
        .order_by("scheduled_for")
        .values_list("id", flat=True)[:200]
    )
    queued = skipped = failed = 0
    for reminder_id in ids:
        outcome = _process_one(reminder_id, now=moment)
        if outcome == "queued":
            queued += 1
        elif outcome == "failed":
            failed += 1
        else:
            skipped += 1
    return {"queued": queued, "skipped": skipped, "failed": failed, "seen": len(ids)}


def note_message_delivery(message: WhatsAppMessage) -> None:
    reminder = (
        AppointmentReminder.objects.filter(whatsapp_message_id=message.id)
        .order_by("-created_at")
        .first()
    )
    if reminder is None:
        return
    if message.status == WhatsAppMessageStatus.SENT:
        reminder.status = AppointmentReminderStatus.SENT
        reminder.sent_at = message.sent_at or timezone.now()
        reminder.last_error_code = ""
        reminder.last_error_message = ""
        reminder.save(
            update_fields=[
                "status",
                "sent_at",
                "last_error_code",
                "last_error_message",
                "updated_at",
            ]
        )
    elif message.status == WhatsAppMessageStatus.FAILED:
        reminder.status = AppointmentReminderStatus.FAILED
        reminder.attempt_count = message.delivery_attempts
        reminder.last_error_code = message.failure_code
        reminder.last_error_message = message.failure_message
        reminder.save(
            update_fields=[
                "status",
                "attempt_count",
                "last_error_code",
                "last_error_message",
                "updated_at",
            ]
        )
    elif message.status == WhatsAppMessageStatus.CANCELLED:
        reminder.status = AppointmentReminderStatus.CANCELLED
        reminder.cancelled_at = reminder.cancelled_at or timezone.now()
        reminder.save(update_fields=["status", "cancelled_at", "updated_at"])


def reminder_summary(*, organization, business, notification_type: str | None = None) -> dict:
    kind = notification_type or AppointmentReminderType.APPOINTMENT_REMINDER_24H
    if kind == _REVIEW_TYPE:
        enabled = (
            business_uses_messaging_reminders(business_id=business.id)
            and _approved_template(
                business_id=business.id,
                purpose=WhatsAppTemplatePurpose.REVIEW_REQUEST,
                category=WhatsAppTemplateCategory.REVIEW_REQUEST,
            )
            is not None
        )
        delay_hours = int(getattr(settings, "WHATSAPP_REVIEW_REQUEST_DELAY_HOURS", 3) or 3)
    else:
        enabled = (
            business_uses_messaging_reminders(business_id=business.id)
            and _approved_reminder_template(business_id=business.id) is not None
        )
        delay_hours = None
    upcoming = AppointmentReminder.objects.filter(
        organization=organization,
        business=business,
        notification_type=kind,
        status__in=[AppointmentReminderStatus.PENDING, AppointmentReminderStatus.QUEUED],
    ).count()
    payload = {
        "notification_type": kind,
        "enabled": enabled,
        "status": "ENABLED" if enabled else "NOT_CONFIGURED",
        "upcoming_count": upcoming,
    }
    if delay_hours is not None:
        payload["delay_hours"] = delay_hours
    return payload


def _schedule_for_appointment_id(appointment_id) -> None:
    appointment = _load(appointment_id)
    if appointment is None or appointment.status != "CONFIRMED":
        return
    if not business_uses_messaging_reminders(business_id=appointment.business_id):
        logger.info(
            "whatsapp.reminder_skipped reason=not_configured reference=%s",
            appointment.public_reference,
        )
        return
    _create_reminders(appointment, now=timezone.now())


def _reschedule(appointment_id) -> None:
    appointment = _load(appointment_id)
    if appointment is None:
        return
    _cancel_active(
        appointment.id,
        reason="rescheduled",
        keep_version=appointment.schedule_version,
    )
    if appointment.status == "CONFIRMED":
        _schedule_for_appointment_id(appointment.id)


def _cancel_active(
    appointment_id,
    *,
    reason: str,
    keep_version: int | None = None,
    notification_types: set[str] | None = None,
) -> None:
    rows = AppointmentReminder.objects.filter(
        appointment_id=appointment_id,
        status__in=list(_ACTIVE),
    )
    if notification_types is not None:
        rows = rows.filter(notification_type__in=list(notification_types))
    if keep_version is not None:
        rows = rows.exclude(schedule_version=keep_version)
    now = timezone.now()
    for reminder in rows.select_related("whatsapp_message"):
        reminder.status = AppointmentReminderStatus.CANCELLED
        reminder.cancelled_at = now
        reminder.last_error_code = reason[:64]
        reminder.save(update_fields=["status", "cancelled_at", "last_error_code", "updated_at"])
        message = reminder.whatsapp_message
        if message is not None and message.status == WhatsAppMessageStatus.QUEUED:
            message.status = WhatsAppMessageStatus.CANCELLED
            message.save(update_fields=["status", "updated_at"])


def _create_reminders(appointment, *, now) -> None:
    for notification_type, offset, suffix in _SPECS:
        _create_one(
            appointment,
            now=now,
            notification_type=notification_type,
            scheduled_for=appointment.starts_at - offset,
            suffix=suffix,
            require_future=True,
        )


def _create_reminder(appointment, *, now) -> AppointmentReminder | None:
    """Backward-compatible helper used by tests for the 24-hour reminder."""
    return _create_one(
        appointment,
        now=now,
        notification_type=AppointmentReminderType.APPOINTMENT_REMINDER_24H,
        scheduled_for=appointment.starts_at - timedelta(hours=24),
        suffix="24h",
        require_future=True,
    )


def _schedule_review(appointment_id) -> None:
    appointment = _load(appointment_id)
    if appointment is None or appointment.status != "COMPLETED":
        return
    if not business_uses_messaging_reminders(business_id=appointment.business_id):
        logger.info(
            "whatsapp.review_skipped reason=not_connected reference=%s",
            appointment.public_reference,
        )
        return
    delay = timedelta(hours=int(getattr(settings, "WHATSAPP_REVIEW_REQUEST_DELAY_HOURS", 3) or 3))
    _create_one(
        appointment,
        now=timezone.now(),
        notification_type=_REVIEW_TYPE,
        scheduled_for=timezone.now() + delay,
        suffix="review-request",
        require_future=False,
        schedule_version=0,
    )


def _create_one(
    appointment,
    *,
    now,
    notification_type: str,
    scheduled_for,
    suffix: str,
    require_future: bool,
    schedule_version: int | None = None,
) -> AppointmentReminder | None:
    version = appointment.schedule_version or 1 if schedule_version is None else schedule_version
    if timezone.is_naive(scheduled_for):
        scheduled_for = timezone.make_aware(scheduled_for, timezone.UTC)
    if suffix == "review-request":
        key = f"appointment:{appointment.id}:review-request"
    else:
        key = f"appointment:{appointment.id}:reminder:{version}:{suffix}"
    existing = AppointmentReminder.objects.filter(idempotency_key=key).first()
    if existing is not None:
        return existing
    status = AppointmentReminderStatus.PENDING
    error = ""
    if require_future and (scheduled_for <= now or appointment.starts_at <= now):
        status = AppointmentReminderStatus.SKIPPED
        error = "reminder_time_passed"
    try:
        return AppointmentReminder.objects.create(
            organization_id=appointment.organization_id,
            business_id=appointment.business_id,
            appointment=appointment,
            notification_type=notification_type,
            schedule_version=version,
            scheduled_for=scheduled_for,
            status=status,
            idempotency_key=key,
            last_error_code=error,
        )
    except IntegrityError:
        return AppointmentReminder.objects.filter(idempotency_key=key).first()


def _process_one(reminder_id, *, now) -> str:
    with transaction.atomic():
        reminder = (
            AppointmentReminder.objects.select_for_update()
            .select_related("appointment", "appointment__customer", "appointment__location")
            .filter(pk=reminder_id)
            .first()
        )
        if reminder is None or reminder.status != AppointmentReminderStatus.PENDING:
            return "skipped"
        appointment = reminder.appointment
        is_review = reminder.notification_type == _REVIEW_TYPE
        allowed_status = "COMPLETED" if is_review else "CONFIRMED"
        if appointment.deleted_at is not None or appointment.status != allowed_status:
            reminder.status = AppointmentReminderStatus.CANCELLED
            reminder.cancelled_at = now
            reminder.last_error_code = "appointment_not_eligible"
            reminder.save(update_fields=["status", "cancelled_at", "last_error_code", "updated_at"])
            return "skipped"
        if not is_review and appointment.schedule_version != reminder.schedule_version:
            reminder.status = AppointmentReminderStatus.SKIPPED
            reminder.last_error_code = "schedule_version_mismatch"
            reminder.save(update_fields=["status", "last_error_code", "updated_at"])
            return "skipped"
        if not is_review and appointment.starts_at <= now:
            reminder.status = AppointmentReminderStatus.SKIPPED
            reminder.last_error_code = "appointment_started"
            reminder.save(update_fields=["status", "last_error_code", "updated_at"])
            return "skipped"
        if not WhatsAppAccount.objects.filter(
            organization_id=appointment.organization_id,
            business_id=appointment.business_id,
            deleted_at__isnull=True,
            status=WhatsAppConnectionStatus.CONNECTED,
        ).exists():
            reminder.status = AppointmentReminderStatus.SKIPPED
            reminder.last_error_code = "not_connected"
            reminder.last_error_message = "WhatsApp Business is not connected."
            reminder.save(
                update_fields=[
                    "status",
                    "last_error_code",
                    "last_error_message",
                    "updated_at",
                ]
            )
            return "skipped"
        template = _template_for(reminder)
        if template is None:
            reminder.status = AppointmentReminderStatus.SKIPPED
            reminder.last_error_code = "no_template"
            reminder.last_error_message = "No approved appointment reminder template."
            reminder.save(
                update_fields=[
                    "status",
                    "last_error_code",
                    "last_error_message",
                    "updated_at",
                ]
            )
            return "skipped"
        phone = (appointment.customer.phone if appointment.customer_id else "") or ""
        if not phone:
            reminder.status = AppointmentReminderStatus.SKIPPED
            reminder.last_error_code = "no_phone"
            reminder.save(update_fields=["status", "last_error_code", "updated_at"])
            return "skipped"
        if is_review and not getattr(appointment.customer, "whatsapp_opt_in", False):
            reminder.status = AppointmentReminderStatus.SKIPPED
            reminder.last_error_code = "opt_out"
            reminder.last_error_message = "Customer has not opted in to WhatsApp."
            reminder.save(
                update_fields=["status", "last_error_code", "last_error_message", "updated_at"]
            )
            return "skipped"
        if is_review:
            from messaging.variables import _public_review_url

            if not _public_review_url(appointment):
                reminder.status = AppointmentReminderStatus.SKIPPED
                reminder.last_error_code = "no_review_url"
                reminder.last_error_message = "No review URL is configured."
                reminder.save(
                    update_fields=[
                        "status",
                        "last_error_code",
                        "last_error_message",
                        "updated_at",
                    ]
                )
                return "skipped"
        names = list(template.variables or [])
        values, rendered = render_template_snapshot(appointment, body=template.body, names=names)
        from messaging.services import queue_whatsapp_message

        message = queue_whatsapp_message(
            organization=appointment.organization,
            business_id=appointment.business_id,
            phone_number=phone,
            message_type=WhatsAppMessageType.TEMPLATE,
            template_name=template.name,
            template_language=template.language,
            variables=values,
            rendered_text=rendered,
            customer_id=appointment.customer_id,
            appointment_id=appointment.id,
            idempotency_key=reminder.idempotency_key,
            purpose=(
                WhatsAppTemplatePurpose.REVIEW_REQUEST
                if is_review
                else WhatsAppTemplatePurpose.APPOINTMENT_REMINDER
            ),
        )
        reminder.whatsapp_message = message
        if message.status == WhatsAppMessageStatus.SENT:
            reminder.status = AppointmentReminderStatus.SENT
            reminder.sent_at = message.sent_at or now
        elif message.status == WhatsAppMessageStatus.FAILED:
            reminder.status = AppointmentReminderStatus.FAILED
            reminder.last_error_code = message.failure_code
            reminder.last_error_message = message.failure_message
        else:
            reminder.status = AppointmentReminderStatus.QUEUED
        reminder.attempt_count = message.delivery_attempts
        reminder.save()
        return "failed" if reminder.status == AppointmentReminderStatus.FAILED else "queued"


def message_blocked_by_reminder(message: WhatsAppMessage) -> bool:
    reminder = (
        AppointmentReminder.objects.select_related("appointment")
        .filter(whatsapp_message_id=message.id)
        .first()
    )
    if reminder is None:
        return False
    appointment = reminder.appointment
    is_review = reminder.notification_type == _REVIEW_TYPE
    if reminder.status == AppointmentReminderStatus.CANCELLED:
        return True
    if appointment.deleted_at is not None:
        return True
    if is_review:
        return appointment.status != "COMPLETED"
    if appointment.schedule_version != reminder.schedule_version:
        return True
    if appointment.status != "CONFIRMED":
        return True
    if appointment.starts_at <= timezone.now():
        return True
    return False


def _template_for(reminder: AppointmentReminder) -> MessageTemplate | None:
    if reminder.notification_type == _REVIEW_TYPE:
        return _approved_template(
            business_id=reminder.business_id,
            purpose=WhatsAppTemplatePurpose.REVIEW_REQUEST,
            category=WhatsAppTemplateCategory.REVIEW_REQUEST,
        )
    return _approved_reminder_template(business_id=reminder.business_id)


def _approved_template(*, business_id, purpose: str, category: str) -> MessageTemplate | None:
    return (
        MessageTemplate.objects.filter(
            business_id=business_id,
            purpose=purpose,
            category=category,
            language=DEFAULT_TEMPLATE_LANGUAGE,
            status=WhatsAppTemplateStatus.APPROVED,
            deleted_at__isnull=True,
        )
        .order_by("created_at")
        .first()
    )


def _approved_reminder_template(*, business_id) -> MessageTemplate | None:
    return _approved_template(
        business_id=business_id,
        purpose=WhatsAppTemplatePurpose.APPOINTMENT_REMINDER,
        category=WhatsAppTemplateCategory.REMINDER,
    )


def _load(appointment_id):
    from booking.models import Appointment

    return (
        Appointment.objects.select_related("customer", "location", "organization")
        .filter(pk=appointment_id, deleted_at__isnull=True)
        .first()
    )
