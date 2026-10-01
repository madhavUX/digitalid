"""Scheduler-independent WhatsApp appointment reminder processing."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from booking.models import (
    Appointment,
    AppointmentStatus,
    NotificationChannel,
    NotificationDelivery,
    NotificationStatus,
    NotificationType,
)
from booking.notifications import BookingNotificationService, get_notification_service

logger = logging.getLogger(__name__)

# Reminder eligibility: CONFIRMED only. CHECKED_IN customers are already on-site.
REMINDER_ELIGIBLE_STATUSES = frozenset({AppointmentStatus.CONFIRMED})


@dataclass(frozen=True)
class ReminderKind:
    notification_type: str
    offset_minutes: int
    enabled_setting: str
    label: str


@dataclass
class ReminderRunResult:
    processed: int = 0
    sent: int = 0
    skipped: int = 0
    failed: int = 0


def reminder_kinds() -> list[ReminderKind]:
    return [
        ReminderKind(
            notification_type=NotificationType.REMINDER_24H,
            offset_minutes=int(
                getattr(settings, "WHATSAPP_REMINDER_24H_OFFSET_MINUTES", 1440) or 1440
            ),
            enabled_setting="WHATSAPP_REMINDER_24H_ENABLED",
            label="24h",
        ),
        ReminderKind(
            notification_type=NotificationType.REMINDER_1H,
            offset_minutes=int(getattr(settings, "WHATSAPP_REMINDER_1H_OFFSET_MINUTES", 60) or 60),
            enabled_setting="WHATSAPP_REMINDER_1H_ENABLED",
            label="1h",
        ),
    ]


def reminder_due_at(*, starts_at: datetime, offset_minutes: int) -> datetime:
    return starts_at - timedelta(minutes=offset_minutes)


def max_late_minutes() -> int:
    return int(getattr(settings, "WHATSAPP_REMINDER_MAX_LATE_MINUTES", 30) or 30)


def is_appointment_reminder_eligible(appointment: Appointment) -> bool:
    """Status/soft-delete gate (timing checked separately)."""
    if appointment.deleted_at is not None:
        return False
    return appointment.status in REMINDER_ELIGIBLE_STATUSES


def is_reminder_in_send_window(
    *,
    starts_at: datetime,
    created_at: datetime,
    offset_minutes: int,
    now: datetime,
    late_minutes: int | None = None,
) -> bool:
    """
    Reminder is due when:
    - appointment has not started (now < starts_at)
    - due_at <= now <= due_at + max_late
    - appointment existed before due_at (created_at <= due_at)

    The created_at rule skips reminders for bookings made inside the offset window
    (e.g. booked 30 minutes before start → 1h reminder never becomes "on time").
    """
    late = max_late_minutes() if late_minutes is None else late_minutes
    if now >= starts_at:
        return False
    due_at = reminder_due_at(starts_at=starts_at, offset_minutes=offset_minutes)
    if created_at > due_at:
        return False
    if now < due_at:
        return False
    if now > due_at + timedelta(minutes=late):
        return False
    return True


def _existing_reminder_subquery(notification_type: str):
    return NotificationDelivery.objects.filter(
        appointment_id=OuterRef("pk"),
        channel=NotificationChannel.WHATSAPP,
        notification_type=notification_type,
    )


def find_due_appointments_for_kind(
    *,
    kind: ReminderKind,
    now: datetime,
) -> list[Appointment]:
    late = max_late_minutes()
    # due_at = starts_at - offset ∈ [now - late, now]
    # ⇒ starts_at ∈ [now - late + offset, now + offset]
    # also starts_at > now
    lower = now - timedelta(minutes=late) + timedelta(minutes=kind.offset_minutes)
    upper = now + timedelta(minutes=kind.offset_minutes)
    candidates = (
        Appointment.objects.filter(
            deleted_at__isnull=True,
            status=AppointmentStatus.CONFIRMED,
            starts_at__gt=now,
            starts_at__gte=lower,
            starts_at__lte=upper,
        )
        .annotate(has_reminder=Exists(_existing_reminder_subquery(kind.notification_type)))
        .filter(has_reminder=False)
        .select_related("location", "customer", "staff_profile")
        .prefetch_related("items")
        .order_by("starts_at")
    )
    due: list[Appointment] = []
    for appointment in candidates:
        if is_reminder_in_send_window(
            starts_at=appointment.starts_at,
            created_at=appointment.created_at,
            offset_minutes=kind.offset_minutes,
            now=now,
            late_minutes=late,
        ):
            due.append(appointment)
    return due


def _record_no_recipient_failure(
    appointment: Appointment,
    *,
    notification_type: str,
) -> NotificationDelivery:
    from booking.notifications import _get_or_create_delivery

    delivery = _get_or_create_delivery(
        appointment=appointment,
        notification_type=notification_type,
        recipient="invalid",
    )
    if delivery.status == NotificationStatus.SENT:
        return delivery
    delivery.status = NotificationStatus.FAILED
    delivery.provider_status = "failed"
    delivery.last_error = "No valid WhatsApp recipient."
    delivery.error_class = "PERMANENT"
    delivery.failed_at = timezone.now()
    delivery.attempt_count = max(delivery.attempt_count, 1)
    delivery.save(
        update_fields=[
            "status",
            "provider_status",
            "last_error",
            "error_class",
            "failed_at",
            "attempt_count",
            "updated_at",
        ]
    )
    return delivery


def process_reminder_for_appointment(
    appointment: Appointment,
    *,
    kind: ReminderKind,
    now: datetime,
) -> str:
    """
    Process one appointment/reminder pair.

    Returns one of: sent, skipped, failed.
    Re-checks eligibility under appointment row lock before dispatch.
    """
    with transaction.atomic():
        locked = (
            Appointment.objects.select_for_update()
            .select_related("location", "customer", "staff_profile")
            .prefetch_related("items")
            .filter(pk=appointment.pk)
            .first()
        )
        if locked is None:
            return "skipped"
        if not is_appointment_reminder_eligible(locked):
            logger.info(
                "reminder.skipped reminder_type=%s appointment_reference=%s "
                "reason=ineligible_status",
                kind.notification_type,
                locked.public_reference,
            )
            return "skipped"
        if not is_reminder_in_send_window(
            starts_at=locked.starts_at,
            created_at=locked.created_at,
            offset_minutes=kind.offset_minutes,
            now=now,
        ):
            logger.info(
                "reminder.skipped reminder_type=%s appointment_reference=%s reason=outside_window",
                kind.notification_type,
                locked.public_reference,
            )
            return "skipped"
        if NotificationDelivery.objects.filter(
            appointment=locked,
            channel=NotificationChannel.WHATSAPP,
            notification_type=kind.notification_type,
        ).exists():
            return "skipped"
        if kind.notification_type in {
            NotificationType.REMINDER_24H,
            NotificationType.REMINDER_1H,
        }:
            from messaging.reminders import business_uses_messaging_reminders

            if business_uses_messaging_reminders(business_id=locked.business_id):
                logger.info(
                    "reminder.skipped reminder_type=%s appointment_reference=%s "
                    "reason=business_whatsapp",
                    kind.notification_type,
                    locked.public_reference,
                )
                return "skipped"

        phone = (locked.customer.phone or "").strip()
        if not phone.startswith("+") or len(phone) < 8:
            _record_no_recipient_failure(locked, notification_type=kind.notification_type)
            logger.info(
                "reminder.failed reminder_type=%s appointment_reference=%s reason=no_recipient",
                kind.notification_type,
                locked.public_reference,
            )
            return "failed"

        appointment_id = locked.pk
        public_reference = locked.public_reference

    # Dispatch outside appointment lock (provider I/O). Claim happens inside notification service.
    locked = (
        Appointment.objects.select_related("location", "customer", "staff_profile")
        .prefetch_related("items")
        .get(pk=appointment_id)
    )
    service = get_notification_service()
    if not isinstance(service, BookingNotificationService):
        send = getattr(service, "send_appointment_reminder", None)
        if send is None:
            logger.warning(
                "reminder.skipped reminder_type=%s appointment_reference=%s reason=no_reminder_api",
                kind.notification_type,
                public_reference,
            )
            return "skipped"
        delivery = send(locked, notification_type=kind.notification_type)
    else:
        delivery = service.send_appointment_reminder(
            locked,
            notification_type=kind.notification_type,
            claim_before_send=True,
        )

    if delivery is None:
        return "skipped"
    if delivery.status == NotificationStatus.SENT:
        logger.info(
            "reminder.sent reminder_type=%s appointment_reference=%s status=SENT",
            kind.notification_type,
            public_reference,
        )
        return "sent"
    if delivery.status == NotificationStatus.FAILED:
        logger.info(
            "reminder.failed reminder_type=%s appointment_reference=%s status=FAILED",
            kind.notification_type,
            public_reference,
        )
        return "failed"
    return "skipped"


def process_due_reminders(*, now: datetime | None = None) -> ReminderRunResult:
    """
    Find and send due WhatsApp reminders.

    Scheduler-independent: safe for cron, K8s CronJob, or future Celery.
    Idempotent via unique (appointment, channel, notification_type) + claim-before-send.

    Tradeoff: claim increments attempt_count before Meta returns. Concurrent workers
    see attempt_count > 0 and skip. This avoids duplicate external sends under
    row locking; Meta itself is not exactly-once. A crash after claim and before
    Meta response may leave PENDING with attempt_count=1 — use retry_notification.
    """
    result = ReminderRunResult()
    if not getattr(settings, "WHATSAPP_REMINDERS_ENABLED", False):
        logger.info("reminder.run_skipped reason=reminders_disabled")
        return result
    if not getattr(settings, "WHATSAPP_ENABLED", False):
        logger.info("reminder.run_skipped reason=whatsapp_disabled")
        return result

    clock = now or timezone.now()
    if timezone.is_naive(clock):
        clock = timezone.make_aware(clock, timezone.utc)

    for kind in reminder_kinds():
        if not getattr(settings, kind.enabled_setting, True):
            logger.info("reminder.kind_disabled reminder_type=%s", kind.notification_type)
            continue
        due = find_due_appointments_for_kind(kind=kind, now=clock)
        for appointment in due:
            result.processed += 1
            outcome = process_reminder_for_appointment(appointment, kind=kind, now=clock)
            if outcome == "sent":
                result.sent += 1
            elif outcome == "failed":
                result.failed += 1
            else:
                result.skipped += 1

    logger.info(
        "reminder.run_complete processed=%s sent=%s skipped=%s failed=%s",
        result.processed,
        result.sent,
        result.skipped,
        result.failed,
    )
    return result
