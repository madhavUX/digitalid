"""Appointment lifecycle → queued WhatsApp templates. Does not call the provider."""

from __future__ import annotations

import logging

from messaging.models import (
    MessageTemplate,
    WhatsAppAccount,
    WhatsAppConnectionStatus,
    WhatsAppMessage,
    WhatsAppMessageType,
    WhatsAppTemplateCategory,
    WhatsAppTemplatePurpose,
    WhatsAppTemplateStatus,
)
from messaging.services import queue_whatsapp_message
from messaging.variables import DEFAULT_TEMPLATE_LANGUAGE, resolve_template_variables

logger = logging.getLogger("messaging.automation")

PURPOSE_BY_EVENT = {
    "AppointmentCreated": WhatsAppTemplatePurpose.BOOKING_CONFIRMATION,
    "AppointmentConfirmed": WhatsAppTemplatePurpose.BOOKING_CONFIRMED,
    "AppointmentRescheduled": WhatsAppTemplatePurpose.BOOKING_RESCHEDULED,
    "AppointmentCancelled": WhatsAppTemplatePurpose.BOOKING_CANCELLED,
}

PURPOSE_CATEGORY = {
    WhatsAppTemplatePurpose.BOOKING_CONFIRMATION: WhatsAppTemplateCategory.CONFIRMATION,
    WhatsAppTemplatePurpose.BOOKING_CONFIRMED: WhatsAppTemplateCategory.CONFIRMATION,
    WhatsAppTemplatePurpose.BOOKING_RESCHEDULED: WhatsAppTemplateCategory.CONFIRMATION,
    WhatsAppTemplatePurpose.BOOKING_CANCELLED: WhatsAppTemplateCategory.CONFIRMATION,
    WhatsAppTemplatePurpose.REVIEW_REQUEST: WhatsAppTemplateCategory.REVIEW_REQUEST,
}

_KEY_PREFIX = {
    WhatsAppTemplatePurpose.BOOKING_CONFIRMATION: "booking-confirmation",
    WhatsAppTemplatePurpose.BOOKING_CONFIRMED: "booking-confirmed",
    WhatsAppTemplatePurpose.BOOKING_RESCHEDULED: "booking-rescheduled",
    WhatsAppTemplatePurpose.BOOKING_CANCELLED: "booking-cancelled",
    WhatsAppTemplatePurpose.REVIEW_REQUEST: "review-request",
}

PLATFORM_PURPOSE = {
    "BOOKING_CONFIRMATION": WhatsAppTemplatePurpose.BOOKING_CONFIRMATION,
    "BOOKING_CANCELLATION": WhatsAppTemplatePurpose.BOOKING_CANCELLED,
}


def business_handles_platform_notification(*, business_id, notification_type: str) -> bool:
    """True when the business-owned account will send this platform notification itself."""
    purpose = PLATFORM_PURPOSE.get(notification_type)
    if purpose is None:
        return False
    return _sendable_template(business_id=business_id, purpose=purpose) is not None


def handle_appointment_event(event) -> None:
    """Queue one transactional template after the appointment transaction has committed."""
    try:
        _handle(event)
    except Exception:
        logger.exception(
            "whatsapp.automation_failed event=%s",
            type(event).__name__,
        )


def _handle(event) -> None:
    purpose = PURPOSE_BY_EVENT.get(type(event).__name__)
    appointment_id = getattr(event, "appointment_id", None)
    if purpose is None or appointment_id is None:
        return
    appointment = _load_appointment(appointment_id)
    if appointment is None:
        logger.info("whatsapp.automation_skipped reason=appointment_missing")
        return
    reference = appointment.public_reference or ""
    account = (
        WhatsAppAccount.objects.filter(
            organization_id=appointment.organization_id,
            business_id=appointment.business_id,
            deleted_at__isnull=True,
            status=WhatsAppConnectionStatus.CONNECTED,
        )
        .order_by("-updated_at")
        .first()
    )
    if account is None:
        logger.info(
            "whatsapp.automation_skipped reason=not_connected reference=%s purpose=%s",
            reference,
            purpose,
        )
        return
    template = _sendable_template(business_id=appointment.business_id, purpose=purpose)
    if template is None:
        inactive = MessageTemplate.objects.filter(
            organization_id=appointment.organization_id,
            business_id=appointment.business_id,
            purpose=purpose,
            language=DEFAULT_TEMPLATE_LANGUAGE,
            deleted_at__isnull=True,
        ).first()
        if inactive is not None:
            logger.info(
                "whatsapp.automation_skipped reason=template_inactive reference=%s "
                "purpose=%s status=%s",
                reference,
                purpose,
                inactive.status,
            )
        else:
            logger.info(
                "whatsapp.automation_skipped reason=no_template reference=%s purpose=%s",
                reference,
                purpose,
            )
        return
    phone = (appointment.customer.phone if appointment.customer_id else "") or ""
    if not phone:
        logger.info(
            "whatsapp.automation_skipped reason=no_phone reference=%s purpose=%s",
            reference,
            purpose,
        )
        return
    variables = resolve_template_variables(appointment, list(template.variables or []))
    key = _idempotency_key(purpose, appointment)
    queue_whatsapp_message(
        organization=appointment.organization,
        business_id=appointment.business_id,
        phone_number=phone,
        message_type=WhatsAppMessageType.TEMPLATE,
        template_name=template.name,
        template_language=template.language,
        variables=variables,
        customer_id=appointment.customer_id,
        appointment_id=appointment.id,
        idempotency_key=key,
        purpose=purpose,
    )
    logger.info(
        "whatsapp.automation_queued reference=%s purpose=%s",
        reference,
        purpose,
    )


def _sendable_template(*, business_id, purpose: str) -> MessageTemplate | None:
    category = PURPOSE_CATEGORY.get(purpose)
    if category is None:
        return None
    template = (
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
    if template is None:
        return None
    connected = WhatsAppAccount.objects.filter(
        business_id=business_id,
        deleted_at__isnull=True,
        status=WhatsAppConnectionStatus.CONNECTED,
    ).exists()
    if not connected:
        return None
    return template


def _idempotency_key(purpose: str, appointment) -> str:
    prefix = _KEY_PREFIX[purpose]
    appointment_id = appointment.id
    if purpose == WhatsAppTemplatePurpose.BOOKING_RESCHEDULED:
        stamp = int(appointment.updated_at.timestamp()) if appointment.updated_at else 0
        return f"{prefix}:{appointment_id}:{stamp}"
    if purpose == WhatsAppTemplatePurpose.BOOKING_CANCELLED:
        moment = appointment.cancelled_at or appointment.updated_at
        stamp = int(moment.timestamp()) if moment else 0
        return f"{prefix}:{appointment_id}:{stamp}"
    return f"{prefix}:{appointment_id}"


def _load_appointment(appointment_id):
    from booking.models import Appointment

    return (
        Appointment.objects.select_related(
            "customer",
            "location",
            "business",
            "staff_profile",
            "organization",
        )
        .prefetch_related("items")
        .filter(pk=appointment_id, deleted_at__isnull=True)
        .first()
    )


def queued_for_purpose(*, business_id, appointment_id, purpose: str) -> WhatsAppMessage | None:
    return (
        WhatsAppMessage.objects.filter(
            business_id=business_id,
            appointment_id=appointment_id,
            purpose=purpose,
        )
        .order_by("created_at")
        .first()
    )
