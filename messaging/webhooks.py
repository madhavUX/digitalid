"""Apply Meta delivery callbacks to business-owned WhatsAppMessage rows."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from django.utils import timezone

from messaging.models import WhatsAppAccount, WhatsAppMessage, WhatsAppMessageStatus

logger = logging.getLogger("messaging.webhooks")

_RANK = {
    WhatsAppMessageStatus.QUEUED: 0,
    WhatsAppMessageStatus.SENT: 1,
    WhatsAppMessageStatus.DELIVERED: 2,
    WhatsAppMessageStatus.READ: 3,
}

_FROM_PROVIDER = {
    "sent": WhatsAppMessageStatus.SENT,
    "delivered": WhatsAppMessageStatus.DELIVERED,
    "read": WhatsAppMessageStatus.READ,
    "failed": WhatsAppMessageStatus.FAILED,
}


def account_matches_message(*, message: WhatsAppMessage, phone_number_id: str) -> bool:
    phone_id = (phone_number_id or "").strip()
    if not phone_id:
        return False
    return WhatsAppAccount.objects.filter(
        organization_id=message.organization_id,
        business_id=message.business_id,
        phone_number_id=phone_id,
        deleted_at__isnull=True,
    ).exists()


def find_business_message(*, provider_message_id: str) -> WhatsAppMessage | None:
    wamid = (provider_message_id or "").strip()
    if not wamid:
        return None
    return WhatsAppMessage.objects.filter(provider_message_id=wamid[:128]).first()


def apply_business_message_status(
    *,
    message: WhatsAppMessage,
    provider_status: str,
    meta_timestamp: int | None = None,
    error_message: str = "",
) -> bool:
    """Update a message already resolved by provider id. Does not trust webhook tenant ids."""
    target = _FROM_PROVIDER.get((provider_status or "").strip().lower())
    if target is None:
        return False
    current = message.status
    if current in {WhatsAppMessageStatus.FAILED, WhatsAppMessageStatus.CANCELLED}:
        return False
    if target == WhatsAppMessageStatus.FAILED:
        if current in {
            WhatsAppMessageStatus.READ,
            WhatsAppMessageStatus.FAILED,
            WhatsAppMessageStatus.CANCELLED,
        }:
            return False
    elif current in _RANK and _RANK.get(target, -1) <= _RANK.get(current, -1):
        return False

    event_time = timezone.now()
    if meta_timestamp:
        try:
            event_time = datetime.fromtimestamp(int(meta_timestamp), tz=UTC)
        except (TypeError, ValueError, OSError):
            event_time = timezone.now()

    message.status = target
    update_fields = ["status", "updated_at"]
    if target == WhatsAppMessageStatus.SENT and not message.sent_at:
        message.sent_at = event_time
        update_fields.append("sent_at")
    elif target == WhatsAppMessageStatus.DELIVERED:
        message.delivered_at = event_time
        update_fields.append("delivered_at")
    elif target == WhatsAppMessageStatus.READ:
        message.read_at = event_time
        update_fields.append("read_at")
    elif target == WhatsAppMessageStatus.FAILED:
        message.failed_at = event_time
        message.failure_code = "PROVIDER_FAILED"
        safe = (error_message or "Delivery failed.")[:500]
        if "token" in safe.lower() or "bearer" in safe.lower():
            safe = "Delivery failed."
        message.failure_message = safe
        update_fields.extend(["failed_at", "failure_code", "failure_message"])
    message.save(update_fields=update_fields)
    logger.info(
        "whatsapp.webhook_status message_id=%s status=%s",
        message.id,
        target,
    )
    return True
