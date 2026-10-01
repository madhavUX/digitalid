"""Transactional booking notifications — WhatsApp-first, provider-agnostic."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone

from booking.manage_tokens import issue_manage_token
from booking.models import (
    Appointment,
    NotificationChannel,
    NotificationDelivery,
    NotificationStatus,
    NotificationType,
)
from booking.whatsapp import (
    WhatsAppProviderError,
    get_whatsapp_provider,
    mask_phone,
)

logger = logging.getLogger(__name__)

PAYLOAD_VERSION = 1


class NotificationService(Protocol):
    def send_booking_confirmation(
        self, appointment: Appointment, manage_token: str | None = None
    ) -> None: ...

    def send_booking_cancellation(self, appointment: Appointment) -> None: ...


@dataclass(frozen=True)
class BookingMessagePayload:
    text: str
    manage_url: str | None
    book_again_url: str | None


def public_app_base_url() -> str:
    return (getattr(settings, "PUBLIC_APP_URL", "") or "http://localhost:3000").rstrip("/")


def build_manage_url(*, raw_token: str) -> str:
    from urllib.parse import quote

    return f"{public_app_base_url()}/book/manage/{quote(raw_token, safe='')}"


def build_book_again_url(*, location_slug: str) -> str:
    from urllib.parse import quote

    return f"{public_app_base_url()}/book/{quote(location_slug, safe='')}"


def sanitize_url_for_log(url: str | None) -> str:
    """Strip manage token path segment before logging."""
    if not url:
        return ""
    marker = "/book/manage/"
    if marker in url:
        return url.split(marker, 1)[0] + marker + "<redacted>"
    return url


def sanitize_snapshot_for_log(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """Safe summary for logs — never dump full text or raw manage URLs."""
    if not snapshot:
        return {}
    return {
        "payload_version": snapshot.get("payload_version"),
        "message_type": snapshot.get("message_type"),
        "public_reference": snapshot.get("public_reference"),
        "manage_url": sanitize_url_for_log(snapshot.get("manage_url")),
        "book_again_url": snapshot.get("book_again_url") or "",
        "text_chars": len(snapshot.get("text") or ""),
    }


def _format_local_parts(appointment: Appointment) -> tuple[str, str, str]:
    tz = ZoneInfo(appointment.location.timezone)
    start = appointment.starts_at.astimezone(tz)
    end = appointment.ends_at.astimezone(tz)
    date_label = f"{start.day} {start.strftime('%B %Y')}"
    start_t = start.strftime("%I:%M %p").lstrip("0")
    end_t = end.strftime("%I:%M %p").lstrip("0")
    return date_label, start_t, end_t


def build_confirmation_payload(
    appointment: Appointment,
    *,
    manage_token: str | None = None,
) -> BookingMessagePayload:
    from booking.models import AppointmentManageToken

    item = appointment.items.first()
    service_name = item.service_name if item else "Service"
    date_label, start_t, end_t = _format_local_parts(appointment)
    raw_token = manage_token
    if (
        not raw_token
        and not AppointmentManageToken.objects.filter(appointment=appointment).exists()
    ):
        # First confirmation for an internal booking: issue a manage token once.
        raw_token = issue_manage_token(appointment=appointment)
    manage_url = build_manage_url(raw_token=raw_token) if raw_token else None
    lines = [
        "Your booking is confirmed.",
        "",
        appointment.location.name,
        "",
        service_name,
        appointment.staff_profile.display_name,
        "",
        date_label,
        f"{start_t} – {end_t}",
        "",
        f"Booking reference: {appointment.public_reference}",
    ]
    if manage_url:
        lines.extend(["", "Manage your booking:", manage_url])
    return BookingMessagePayload(
        text="\n".join(lines),
        manage_url=manage_url,
        book_again_url=None,
    )


def build_cancellation_payload(appointment: Appointment) -> BookingMessagePayload:
    item = appointment.items.first()
    service_name = item.service_name if item else "Service"
    date_label, start_t, _end_t = _format_local_parts(appointment)
    book_again = build_book_again_url(location_slug=appointment.location.slug)
    lines = [
        "Your booking has been cancelled.",
        "",
        appointment.location.name,
        "",
        service_name,
        date_label,
        start_t,
        "",
        f"Booking reference: {appointment.public_reference}",
        "",
        "Book again:",
        book_again,
    ]
    return BookingMessagePayload(
        text="\n".join(lines),
        manage_url=None,
        book_again_url=book_again,
    )


def _local_iso(appointment: Appointment) -> tuple[str, str]:
    tz = ZoneInfo(appointment.location.timezone)
    return (
        appointment.starts_at.astimezone(tz).isoformat(),
        appointment.ends_at.astimezone(tz).isoformat(),
    )


def build_confirmation_snapshot(
    appointment: Appointment,
    payload: BookingMessagePayload,
) -> dict[str, Any]:
    item = appointment.items.first()
    starts_at, ends_at = _local_iso(appointment)
    date_label, start_t, end_t = _format_local_parts(appointment)
    return {
        "payload_version": PAYLOAD_VERSION,
        "message_type": NotificationType.BOOKING_CONFIRMATION,
        "business_name": appointment.location.name,
        "service_name": item.service_name if item else "Service",
        "staff_name": appointment.staff_profile.display_name,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "date_label": date_label,
        "time_label": f"{start_t} – {end_t}",
        "public_reference": appointment.public_reference,
        "manage_url": payload.manage_url,
        "text": payload.text,
    }


def build_cancellation_snapshot(
    appointment: Appointment,
    payload: BookingMessagePayload,
) -> dict[str, Any]:
    item = appointment.items.first()
    starts_at, ends_at = _local_iso(appointment)
    date_label, start_t, _end_t = _format_local_parts(appointment)
    return {
        "payload_version": PAYLOAD_VERSION,
        "message_type": NotificationType.BOOKING_CANCELLATION,
        "business_name": appointment.location.name,
        "service_name": item.service_name if item else "Service",
        "starts_at": starts_at,
        "ends_at": ends_at,
        "date_label": date_label,
        "time_label": start_t,
        "public_reference": appointment.public_reference,
        "book_again_url": payload.book_again_url,
        "text": payload.text,
    }


def resolve_manage_url_for_reminder(appointment: Appointment) -> str | None:
    """Reuse manage URL from confirmation snapshot; never mint a new token."""
    confirmation = (
        NotificationDelivery.objects.filter(
            appointment=appointment,
            channel=NotificationChannel.WHATSAPP,
            notification_type=NotificationType.BOOKING_CONFIRMATION,
        )
        .only("payload_snapshot")
        .first()
    )
    if not confirmation:
        return None
    snap = confirmation.payload_snapshot or {}
    url = snap.get("manage_url")
    if isinstance(url, str) and url.strip():
        return url.strip()
    return None


def build_reminder_payload(
    appointment: Appointment,
    *,
    notification_type: str,
    manage_url: str | None,
) -> BookingMessagePayload:
    item = appointment.items.first()
    service_name = item.service_name if item else "Service"
    date_label, start_t, _end_t = _format_local_parts(appointment)
    if notification_type == NotificationType.REMINDER_24H:
        headline = "Reminder: Your appointment is tomorrow."
    elif notification_type == NotificationType.REMINDER_1H:
        headline = "Your appointment is in 1 hour."
    else:
        raise ValueError(f"Unsupported reminder type={notification_type}")
    lines = [
        headline,
        "",
        appointment.location.name,
        f"{service_name} with {appointment.staff_profile.display_name}",
        "",
    ]
    if notification_type == NotificationType.REMINDER_24H:
        lines.extend([date_label, start_t, ""])
    else:
        lines.extend([start_t, ""])
    lines.append(f"Booking reference: {appointment.public_reference}")
    if manage_url:
        lines.extend(["", "Manage your booking:", manage_url])
    return BookingMessagePayload(
        text="\n".join(lines),
        manage_url=manage_url,
        book_again_url=None,
    )


def build_reminder_snapshot(
    appointment: Appointment,
    payload: BookingMessagePayload,
    *,
    notification_type: str,
) -> dict[str, Any]:
    item = appointment.items.first()
    starts_at, ends_at = _local_iso(appointment)
    date_label, start_t, _end_t = _format_local_parts(appointment)
    return {
        "payload_version": PAYLOAD_VERSION,
        "message_type": notification_type,
        "notification_type": notification_type,
        "business_name": appointment.location.name,
        "service_name": item.service_name if item else "Service",
        "staff_name": appointment.staff_profile.display_name,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "date_label": date_label,
        "time_label": start_t,
        "public_reference": appointment.public_reference,
        "manage_url": payload.manage_url or "",
        "text": payload.text,
    }


def _customer_whatsapp_recipient(appointment: Appointment) -> str | None:
    """Transactional WhatsApp uses customer.phone; marketing uses whatsapp_opt_in separately."""
    phone = (appointment.customer.phone or "").strip()
    if not phone.startswith("+") or len(phone) < 8:
        return None
    return phone


def _get_or_create_delivery(
    *,
    appointment: Appointment,
    notification_type: str,
    recipient: str,
) -> NotificationDelivery:
    try:
        delivery, _created = NotificationDelivery.objects.get_or_create(
            appointment=appointment,
            channel=NotificationChannel.WHATSAPP,
            notification_type=notification_type,
            defaults={
                "recipient": recipient,
                "status": NotificationStatus.PENDING,
            },
        )
    except IntegrityError:
        delivery = NotificationDelivery.objects.get(
            appointment=appointment,
            channel=NotificationChannel.WHATSAPP,
            notification_type=notification_type,
        )
    if delivery.recipient != recipient and delivery.status != NotificationStatus.SENT:
        delivery.recipient = recipient
        delivery.save(update_fields=["recipient", "updated_at"])
    return delivery


def _persist_snapshot_if_needed(
    delivery: NotificationDelivery,
    snapshot: dict[str, Any],
) -> NotificationDelivery:
    """Store snapshot once before the first provider attempt; never overwrite."""
    if delivery.payload_snapshot and delivery.payload_snapshot.get("text"):
        return delivery
    delivery.payload_snapshot = snapshot
    delivery.payload_version = int(snapshot.get("payload_version") or PAYLOAD_VERSION)
    delivery.save(update_fields=["payload_snapshot", "payload_version", "updated_at"])
    return delivery


def _message_body_from_snapshot(delivery: NotificationDelivery) -> str | None:
    snap = delivery.payload_snapshot or {}
    text = snap.get("text")
    if isinstance(text, str) and text:
        return text
    return None


def _dispatch_whatsapp(
    *,
    delivery: NotificationDelivery,
    body: str,
    increment_attempt: bool = True,
) -> NotificationDelivery:
    if delivery.status == NotificationStatus.SENT:
        logger.info(
            "notification.skip_already_sent notification_type=%s channel=%s "
            "appointment_reference=%s status=SENT",
            delivery.notification_type,
            delivery.channel,
            delivery.appointment.public_reference,
        )
        return delivery

    if increment_attempt:
        delivery.attempt_count += 1
        delivery.save(update_fields=["attempt_count", "updated_at"])

    provider = get_whatsapp_provider()
    snapshot = delivery.payload_snapshot or {"text": body}
    try:
        result = provider.send(
            to=delivery.recipient,
            notification_type=delivery.notification_type,
            snapshot=snapshot,
            notification_id=delivery.id,
        )
    except WhatsAppProviderError as exc:
        delivery.status = NotificationStatus.FAILED
        delivery.provider_status = "failed"
        delivery.last_error = str(exc)[:2000]
        delivery.error_class = "PERMANENT" if exc.permanent else "TRANSIENT"
        delivery.failed_at = timezone.now()
        delivery.save(
            update_fields=[
                "status",
                "provider_status",
                "last_error",
                "error_class",
                "failed_at",
                "updated_at",
            ]
        )
        logger.warning(
            "notification.failed notification_type=%s channel=%s "
            "appointment_reference=%s status=FAILED recipient=%s attempt_count=%s "
            "error_class=%s snapshot=%s",
            delivery.notification_type,
            delivery.channel,
            delivery.appointment.public_reference,
            mask_phone(delivery.recipient),
            delivery.attempt_count,
            delivery.error_class,
            sanitize_snapshot_for_log(delivery.payload_snapshot),
        )
        return delivery
    except Exception as exc:
        delivery.status = NotificationStatus.FAILED
        delivery.provider_status = "failed"
        delivery.last_error = f"Unexpected provider error: {exc}"[:2000]
        delivery.error_class = "TRANSIENT"
        delivery.failed_at = timezone.now()
        delivery.save(
            update_fields=[
                "status",
                "provider_status",
                "last_error",
                "error_class",
                "failed_at",
                "updated_at",
            ]
        )
        logger.exception(
            "notification.provider_exception notification_type=%s channel=%s "
            "appointment_reference=%s",
            delivery.notification_type,
            delivery.channel,
            delivery.appointment.public_reference,
        )
        return delivery

    delivery.status = NotificationStatus.SENT
    delivery.provider_status = "sent"
    delivery.provider_message_id = (result.provider_message_id or "")[:128]
    delivery.last_error = ""
    delivery.error_class = ""
    delivery.sent_at = timezone.now()
    delivery.failed_at = None
    delivery.save(
        update_fields=[
            "status",
            "provider_status",
            "provider_message_id",
            "last_error",
            "error_class",
            "sent_at",
            "failed_at",
            "updated_at",
        ]
    )
    logger.info(
        "notification.sent notification_type=%s channel=%s "
        "appointment_reference=%s status=SENT attempt_count=%s",
        delivery.notification_type,
        delivery.channel,
        delivery.appointment.public_reference,
        delivery.attempt_count,
    )
    return delivery


def _ensure_and_send(
    *,
    delivery: NotificationDelivery,
    kind: str,
    manage_token: str | None = None,
    increment_attempt: bool = True,
) -> NotificationDelivery:
    if delivery.status == NotificationStatus.SENT:
        return delivery

    body = _message_body_from_snapshot(delivery)
    if body is None:
        if kind == NotificationType.BOOKING_CONFIRMATION:
            payload = build_confirmation_payload(delivery.appointment, manage_token=manage_token)
            snapshot = build_confirmation_snapshot(delivery.appointment, payload)
        elif kind == NotificationType.BOOKING_CANCELLATION:
            payload = build_cancellation_payload(delivery.appointment)
            snapshot = build_cancellation_snapshot(delivery.appointment, payload)
        elif kind in (NotificationType.REMINDER_24H, NotificationType.REMINDER_1H):
            manage_url = resolve_manage_url_for_reminder(delivery.appointment)
            payload = build_reminder_payload(
                delivery.appointment,
                notification_type=kind,
                manage_url=manage_url,
            )
            snapshot = build_reminder_snapshot(
                delivery.appointment,
                payload,
                notification_type=kind,
            )
        else:
            raise ValueError(f"Unsupported notification kind={kind}")
        delivery = _persist_snapshot_if_needed(delivery, snapshot)
        body = payload.text
        logger.info(
            "notification.dispatch notification_type=%s channel=%s "
            "appointment_reference=%s snapshot=%s",
            delivery.notification_type,
            delivery.channel,
            delivery.appointment.public_reference,
            sanitize_snapshot_for_log(delivery.payload_snapshot),
        )
    else:
        logger.info(
            "notification.retry_from_snapshot notification_type=%s channel=%s "
            "appointment_reference=%s snapshot=%s",
            delivery.notification_type,
            delivery.channel,
            delivery.appointment.public_reference,
            sanitize_snapshot_for_log(delivery.payload_snapshot),
        )
    return _dispatch_whatsapp(
        delivery=delivery,
        body=body,
        increment_attempt=increment_attempt,
    )


class BookingNotificationService:
    """Creates NotificationDelivery rows and sends via WhatsAppProvider."""

    def send_booking_confirmation(
        self, appointment: Appointment, manage_token: str | None = None
    ) -> None:
        if not getattr(settings, "WHATSAPP_ENABLED", False):
            logger.info(
                "notification.skipped_disabled notification_type=%s appointment_reference=%s",
                NotificationType.BOOKING_CONFIRMATION,
                appointment.public_reference,
            )
            return
        recipient = _customer_whatsapp_recipient(appointment)
        if recipient is None:
            logger.info(
                "notification.skipped_no_recipient notification_type=%s appointment_reference=%s",
                NotificationType.BOOKING_CONFIRMATION,
                appointment.public_reference,
            )
            return
        delivery = _get_or_create_delivery(
            appointment=appointment,
            notification_type=NotificationType.BOOKING_CONFIRMATION,
            recipient=recipient,
        )
        _ensure_and_send(
            delivery=delivery,
            kind=NotificationType.BOOKING_CONFIRMATION,
            manage_token=manage_token,
        )

    def send_booking_cancellation(self, appointment: Appointment) -> None:
        if not getattr(settings, "WHATSAPP_ENABLED", False):
            logger.info(
                "notification.skipped_disabled notification_type=%s appointment_reference=%s",
                NotificationType.BOOKING_CANCELLATION,
                appointment.public_reference,
            )
            return
        recipient = _customer_whatsapp_recipient(appointment)
        if recipient is None:
            logger.info(
                "notification.skipped_no_recipient notification_type=%s appointment_reference=%s",
                NotificationType.BOOKING_CANCELLATION,
                appointment.public_reference,
            )
            return
        delivery = _get_or_create_delivery(
            appointment=appointment,
            notification_type=NotificationType.BOOKING_CANCELLATION,
            recipient=recipient,
        )
        _ensure_and_send(
            delivery=delivery,
            kind=NotificationType.BOOKING_CANCELLATION,
        )

    def send_appointment_reminder(
        self,
        appointment: Appointment,
        *,
        notification_type: str,
        claim_before_send: bool = True,
    ) -> NotificationDelivery | None:
        """
        Dispatch a reminder. Returns the delivery row, or None if skipped before create.

        When claim_before_send is True (scheduler path), attempt_count is claimed under
        row lock before the provider call so concurrent workers do not double-send.
        """
        if not getattr(settings, "WHATSAPP_ENABLED", False):
            logger.info(
                "notification.skipped_disabled notification_type=%s appointment_reference=%s",
                notification_type,
                appointment.public_reference,
            )
            return None
        if notification_type not in (
            NotificationType.REMINDER_24H,
            NotificationType.REMINDER_1H,
        ):
            raise ValueError(f"Unsupported reminder type={notification_type}")

        recipient = _customer_whatsapp_recipient(appointment)
        if recipient is None:
            logger.info(
                "notification.skipped_no_recipient notification_type=%s appointment_reference=%s",
                notification_type,
                appointment.public_reference,
            )
            return None

        delivery = _get_or_create_delivery(
            appointment=appointment,
            notification_type=notification_type,
            recipient=recipient,
        )
        if delivery.status == NotificationStatus.SENT:
            return delivery
        if delivery.status == NotificationStatus.FAILED:
            # Scheduler must not auto-retry; use retry_notification.
            return delivery

        if claim_before_send:
            from django.db import transaction

            from booking.models import AppointmentStatus

            with transaction.atomic():
                appt = (
                    Appointment.objects.select_for_update()
                    .select_related("location", "customer", "staff_profile")
                    .prefetch_related("items")
                    .get(pk=appointment.pk)
                )
                if appt.deleted_at is not None or appt.status != AppointmentStatus.CONFIRMED:
                    logger.info(
                        "notification.reminder_skipped_ineligible notification_type=%s "
                        "appointment_reference=%s status=%s",
                        notification_type,
                        appt.public_reference,
                        appt.status,
                    )
                    return None

                locked = (
                    NotificationDelivery.objects.select_for_update()
                    .select_related(
                        "appointment",
                        "appointment__location",
                        "appointment__customer",
                        "appointment__staff_profile",
                    )
                    .prefetch_related("appointment__items")
                    .get(pk=delivery.pk)
                )
                if locked.status != NotificationStatus.PENDING or locked.attempt_count > 0:
                    return locked
                manage_url = resolve_manage_url_for_reminder(appt)
                payload = build_reminder_payload(
                    appt,
                    notification_type=notification_type,
                    manage_url=manage_url,
                )
                snapshot = build_reminder_snapshot(
                    appt,
                    payload,
                    notification_type=notification_type,
                )
                locked = _persist_snapshot_if_needed(locked, snapshot)
                locked.attempt_count = 1
                locked.save(update_fields=["attempt_count", "updated_at"])
                delivery = locked
                body = _message_body_from_snapshot(locked) or payload.text
            return _dispatch_whatsapp(
                delivery=delivery,
                body=body,
                increment_attempt=False,
            )

        return _ensure_and_send(
            delivery=delivery,
            kind=notification_type,
        )


def retry_notification(notification_id: UUID) -> NotificationDelivery:
    """Retry a failed/pending delivery using the frozen payload snapshot."""
    delivery = (
        NotificationDelivery.objects.select_related(
            "appointment",
            "appointment__location",
            "appointment__customer",
            "appointment__staff_profile",
        )
        .prefetch_related("appointment__items")
        .get(pk=notification_id)
    )
    if delivery.status == NotificationStatus.SENT:
        return delivery

    body = _message_body_from_snapshot(delivery)
    if body is None:
        # Legacy rows without a snapshot: rebuild once and persist (no token rotation
        # when a manage token already exists — confirmation may omit manage_url).
        if delivery.notification_type == NotificationType.BOOKING_CONFIRMATION:
            payload = build_confirmation_payload(delivery.appointment, manage_token=None)
            snapshot = build_confirmation_snapshot(delivery.appointment, payload)
        elif delivery.notification_type == NotificationType.BOOKING_CANCELLATION:
            payload = build_cancellation_payload(delivery.appointment)
            snapshot = build_cancellation_snapshot(delivery.appointment, payload)
        elif delivery.notification_type in (
            NotificationType.REMINDER_24H,
            NotificationType.REMINDER_1H,
        ):
            manage_url = resolve_manage_url_for_reminder(delivery.appointment)
            payload = build_reminder_payload(
                delivery.appointment,
                notification_type=delivery.notification_type,
                manage_url=manage_url,
            )
            snapshot = build_reminder_snapshot(
                delivery.appointment,
                payload,
                notification_type=delivery.notification_type,
            )
        else:
            raise ValueError(f"Unsupported notification_type={delivery.notification_type}")
        delivery = _persist_snapshot_if_needed(delivery, snapshot)
        body = payload.text

    return _dispatch_whatsapp(delivery=delivery, body=body)


_notification_service: NotificationService = BookingNotificationService()


def get_notification_service() -> NotificationService:
    return _notification_service


def set_notification_service(service: NotificationService) -> None:
    global _notification_service
    _notification_service = service


def handle_appointment_booked(event) -> None:
    appointment = (
        Appointment.objects.select_related("location", "customer", "staff_profile")
        .prefetch_related("items")
        .filter(pk=event.appointment_id)
        .first()
    )
    if appointment is None:
        return
    from messaging.automation import business_handles_platform_notification

    if business_handles_platform_notification(
        business_id=appointment.business_id,
        notification_type=NotificationType.BOOKING_CONFIRMATION,
    ):
        logger.info(
            "notification.skipped_business_account notification_type=%s appointment_reference=%s",
            NotificationType.BOOKING_CONFIRMATION,
            appointment.public_reference,
        )
        return
    get_notification_service().send_booking_confirmation(
        appointment,
        manage_token=getattr(event, "manage_token", None),
    )


def handle_appointment_cancelled(event) -> None:
    appointment = (
        Appointment.objects.select_related("location", "customer", "staff_profile")
        .prefetch_related("items")
        .filter(pk=event.appointment_id)
        .first()
    )
    if appointment is None:
        return
    from messaging.automation import business_handles_platform_notification

    if business_handles_platform_notification(
        business_id=appointment.business_id,
        notification_type=NotificationType.BOOKING_CANCELLATION,
    ):
        logger.info(
            "notification.skipped_business_account notification_type=%s appointment_reference=%s",
            NotificationType.BOOKING_CANCELLATION,
            appointment.public_reference,
        )
        return
    get_notification_service().send_booking_cancellation(appointment)


# Back-compat alias used by older tests
class LoggingNotificationService(BookingNotificationService):
    """Deprecated name; delegates to BookingNotificationService."""
