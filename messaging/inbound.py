"""Persist inbound WhatsApp texts. Does not reply."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from django.db import IntegrityError, transaction

from customers.models import Customer
from customers.services import normalize_public_phone
from messaging.models import (
    WhatsAppAccount,
    WhatsAppInboundMessage,
    WhatsAppInboundProcessingStatus,
)

logger = logging.getLogger("messaging.inbound")


def record_inbound_messages(*, phone_number_id: str, messages: list) -> int:
    phone_id = (phone_number_id or "").strip()
    if not phone_id or not isinstance(messages, list):
        return 0
    account = (
        WhatsAppAccount.objects.filter(phone_number_id=phone_id, deleted_at__isnull=True)
        .order_by("-updated_at")
        .first()
    )
    if account is None:
        logger.info("whatsapp.inbound_ignored reason=unknown_phone_number_id")
        return 0
    stored = 0
    for item in messages:
        if _store_one(account, item):
            stored += 1
    return stored


def _store_one(account: WhatsAppAccount, item) -> bool:
    if not isinstance(item, dict):
        return False
    message_type = str(item.get("type") or "").lower()
    if message_type != "text":
        logger.info("whatsapp.inbound_ignored reason=unsupported_type type=%s", message_type[:32])
        return False
    provider_id = str(item.get("id") or "").strip()[:128]
    if not provider_id:
        return False
    raw_from = str(item.get("from") or "").strip()
    if raw_from.isdigit():
        raw_from = f"+{raw_from}"
    try:
        phone = normalize_public_phone(raw_from)
    except Exception:
        logger.info("whatsapp.inbound_ignored reason=invalid_phone")
        return False
    text = ""
    body = item.get("text") or {}
    if isinstance(body, dict):
        text = str(body.get("body") or "")[:1000]
    customer = Customer.objects.filter(
        organization_id=account.organization_id,
        business_id=account.business_id,
        phone=phone,
        deleted_at__isnull=True,
    ).first()
    stamp = None
    raw_stamp = item.get("timestamp")
    if raw_stamp:
        try:
            stamp = datetime.fromtimestamp(int(raw_stamp), tz=UTC)
        except (TypeError, ValueError, OSError):
            stamp = None
    try:
        with transaction.atomic():
            WhatsAppInboundMessage.objects.create(
                organization_id=account.organization_id,
                business_id=account.business_id,
                whatsapp_account=account,
                customer=customer,
                provider_message_id=provider_id,
                phone_number=phone,
                message_type="TEXT",
                text=text,
                provider_timestamp=stamp,
                processing_status=WhatsAppInboundProcessingStatus.RECEIVED,
            )
    except IntegrityError:
        return False
    return True
