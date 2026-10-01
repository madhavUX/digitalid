"""Meta WhatsApp Cloud API webhook handling."""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import UTC, datetime

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from booking.models import NotificationDelivery, NotificationStatus, WhatsAppWebhookEvent

logger = logging.getLogger(__name__)

_PROVIDER_RANK = {
    "sent": 1,
    "delivered": 2,
    "read": 3,
    "failed": 4,
}


def verify_meta_signature(*, raw_body: bytes, signature_header: str | None) -> bool:
    app_secret = getattr(settings, "META_WHATSAPP_APP_SECRET", "") or ""
    if not app_secret:
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    provided = signature_header.removeprefix("sha256=").strip()
    expected = hmac.new(
        app_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, provided)


def verify_webhook_subscribe(*, mode: str | None, token: str | None) -> bool:
    expected = getattr(settings, "META_WHATSAPP_VERIFY_TOKEN", "") or ""
    return mode == "subscribe" and bool(expected) and token == expected


@transaction.atomic
def apply_whatsapp_status_update(
    *,
    provider_message_id: str,
    provider_status: str,
    meta_timestamp: int | None = None,
    error_message: str = "",
    phone_number_id: str = "",
) -> bool:
    """Apply a Meta status callback. Returns True if a delivery row was updated."""
    wamid = (provider_message_id or "").strip()
    status = (provider_status or "").strip().lower()
    if not wamid or status not in _PROVIDER_RANK:
        return False

    from messaging.webhooks import (
        account_matches_message,
        apply_business_message_status,
        find_business_message,
    )

    delivery = NotificationDelivery.objects.filter(provider_message_id=wamid).first()
    business_message = (
        None if delivery is not None else find_business_message(provider_message_id=wamid)
    )
    if business_message is not None and not account_matches_message(
        message=business_message,
        phone_number_id=phone_number_id,
    ):
        logger.info("whatsapp.webhook_account_mismatch status=%s", status)
        return False

    try:
        WhatsAppWebhookEvent.objects.create(
            provider_message_id=wamid[:128],
            provider_status=status[:32],
            meta_timestamp=meta_timestamp,
        )
    except IntegrityError:
        # Duplicate webhook delivery — already processed.
        return False

    if delivery is not None:
        delivery = NotificationDelivery.objects.select_for_update().filter(pk=delivery.pk).first()
    if delivery is None and business_message is None:
        logger.warning(
            "whatsapp.webhook_unknown_message_id status=%s",
            status,
        )
        return False
    if delivery is None:
        from messaging.models import WhatsAppMessage

        locked = WhatsAppMessage.objects.select_for_update().get(pk=business_message.pk)
        return apply_business_message_status(
            message=locked,
            provider_status=status,
            meta_timestamp=meta_timestamp,
            error_message=error_message,
        )

    current = (delivery.provider_status or "").lower()
    if (
        current in _PROVIDER_RANK
        and status in _PROVIDER_RANK
        and status != "failed"
        and _PROVIDER_RANK[status] < _PROVIDER_RANK[current]
    ):
        # Do not regress (e.g. read → delivered).
        return False

    event_time = timezone.now()
    if meta_timestamp:
        try:
            event_time = datetime.fromtimestamp(int(meta_timestamp), tz=UTC)
        except (TypeError, ValueError, OSError):
            event_time = timezone.now()

    delivery.provider_status = status
    update_fields = ["provider_status", "updated_at"]

    if status == "sent":
        if delivery.status != NotificationStatus.SENT:
            delivery.status = NotificationStatus.SENT
            update_fields.append("status")
        if not delivery.sent_at:
            delivery.sent_at = event_time
            update_fields.append("sent_at")
    elif status == "delivered":
        delivery.delivered_at = event_time
        update_fields.append("delivered_at")
        if delivery.status != NotificationStatus.SENT:
            delivery.status = NotificationStatus.SENT
            update_fields.append("status")
    elif status == "read":
        delivery.read_at = event_time
        update_fields.append("read_at")
        if not delivery.delivered_at:
            delivery.delivered_at = event_time
            update_fields.append("delivered_at")
        if delivery.status != NotificationStatus.SENT:
            delivery.status = NotificationStatus.SENT
            update_fields.append("status")
    elif status == "failed":
        delivery.status = NotificationStatus.FAILED
        delivery.failed_at = event_time
        delivery.error_class = "PERMANENT"
        if error_message:
            delivery.last_error = error_message[:2000]
            update_fields.append("last_error")
        update_fields.extend(["status", "failed_at", "error_class"])

    delivery.save(update_fields=update_fields)
    return True


def process_meta_webhook_payload(payload: dict) -> int:
    """Process Meta webhook JSON. Returns number of status updates applied."""
    applied = 0
    if not isinstance(payload, dict):
        return 0
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value") or {}
            if not isinstance(value, dict):
                continue
            metadata = value.get("metadata") or {}
            phone_number_id = ""
            if isinstance(metadata, dict):
                phone_number_id = str(metadata.get("phone_number_id") or "")
            statuses = value.get("statuses") or []
            if isinstance(statuses, list):
                for item in statuses:
                    if not isinstance(item, dict):
                        continue
                    errors = item.get("errors") or []
                    error_message = ""
                    if isinstance(errors, list) and errors:
                        first = errors[0]
                        if isinstance(first, dict):
                            error_message = str(first.get("title") or first.get("message") or "")
                    if apply_whatsapp_status_update(
                        provider_message_id=str(item.get("id") or ""),
                        provider_status=str(item.get("status") or ""),
                        meta_timestamp=_as_int(item.get("timestamp")),
                        error_message=error_message,
                        phone_number_id=phone_number_id,
                    ):
                        applied += 1
            messages = value.get("messages") or []
            if isinstance(messages, list) and messages:
                from messaging.inbound import record_inbound_messages

                record_inbound_messages(phone_number_id=phone_number_id, messages=messages)
    return applied


def _as_int(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
