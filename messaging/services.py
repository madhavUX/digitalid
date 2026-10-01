"""WhatsApp Business connection, templates, and queued outbound messages."""

from __future__ import annotations

import logging

from django.db import IntegrityError, transaction
from django.db.models import Count
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from businesses.services import get_business_for_organization
from customers.services import normalize_public_phone
from messaging.models import (
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
from messaging.variables import validate_variable_names
from messaging.whatsapp_crypto import (
    WhatsAppCryptoError,
    decrypt_token,
    encrypt_token,
    require_encryption_configured,
)
from messaging.whatsapp_provider import (
    WhatsAppBusinessProviderError,
    get_whatsapp_business_provider,
)

logger = logging.getLogger("messaging.services")

_ALLOWED_STATUSES = {
    WhatsAppMessageStatus.QUEUED: {
        WhatsAppMessageStatus.SENT,
        WhatsAppMessageStatus.FAILED,
        WhatsAppMessageStatus.CANCELLED,
    },
    WhatsAppMessageStatus.SENT: {
        WhatsAppMessageStatus.DELIVERED,
        WhatsAppMessageStatus.FAILED,
    },
    WhatsAppMessageStatus.DELIVERED: {WhatsAppMessageStatus.READ},
    WhatsAppMessageStatus.READ: set(),
    WhatsAppMessageStatus.FAILED: {WhatsAppMessageStatus.QUEUED},
    WhatsAppMessageStatus.CANCELLED: set(),
}


def _provider_name() -> str:
    provider = get_whatsapp_business_provider()
    return getattr(provider, "name", "deferred")


def serialize_account(account: WhatsAppAccount) -> dict:
    connected = account.status == WhatsAppConnectionStatus.CONNECTED
    return {
        "id": str(account.id),
        "business_id": str(account.business_id),
        "connected": connected,
        "status": account.status,
        "phone_number_id": account.phone_number_id or None,
        "business_account_id": account.business_account_id or None,
        "display_phone_number": account.display_phone_number or None,
        "verified_name": account.verified_name or None,
        "token_expires_at": (
            account.token_expires_at.isoformat() if account.token_expires_at else None
        ),
        "connected_at": account.connected_at.isoformat() if account.connected_at else None,
        "disconnected_at": (
            account.disconnected_at.isoformat() if account.disconnected_at else None
        ),
        "last_error_code": account.last_error_code or None,
        "last_error_message": account.last_error_message or None,
        "provider": _provider_name(),
        "connect_available": _provider_name() in {"mock", "meta"},
    }


def serialize_template(template: MessageTemplate) -> dict:
    return {
        "id": str(template.id),
        "business_id": str(template.business_id),
        "name": template.name,
        "language": template.language,
        "category": template.category,
        "provider_template_id": template.provider_template_id or None,
        "purpose": template.purpose or None,
        "status": template.status,
        "provider_status": template.provider_status or None,
        "body": template.body,
        "variables": list(template.variables or []),
    }


def serialize_message(message: WhatsAppMessage) -> dict:
    customer = message.customer if message.customer_id else None
    appointment = message.appointment if message.appointment_id else None
    return {
        "id": str(message.id),
        "business_id": str(message.business_id),
        "customer_id": str(message.customer_id) if message.customer_id else None,
        "customer_name": customer.full_name if customer is not None else None,
        "appointment_id": str(message.appointment_id) if message.appointment_id else None,
        "appointment_reference": appointment.public_reference if appointment is not None else None,
        "phone_number": message.phone_number,
        "purpose": message.purpose or None,
        "message_type": message.message_type,
        "template_name": message.template_name or None,
        "template_language": message.template_language or None,
        "provider_message_id": message.provider_message_id or None,
        "status": message.status,
        "failure_code": message.failure_code or None,
        "failure_message": message.failure_message or None,
        "sent_at": message.sent_at.isoformat() if message.sent_at else None,
        "delivered_at": message.delivered_at.isoformat() if message.delivered_at else None,
        "read_at": message.read_at.isoformat() if message.read_at else None,
        "failed_at": message.failed_at.isoformat() if message.failed_at else None,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def _message_counts(*, organization, business) -> dict:
    grouped = (
        WhatsAppMessage.objects.filter(organization=organization, business=business)
        .values("status")
        .annotate(total=Count("id"))
    )
    counts = {status: 0 for status, _label in WhatsAppMessageStatus.choices}
    for row in grouped:
        counts[row["status"]] = row["total"]
    return counts


def get_or_create_account(*, organization, business, actor=None) -> WhatsAppAccount:
    account = (
        WhatsAppAccount.objects.filter(organization=organization, business=business)
        .order_by("-updated_at")
        .first()
    )
    if account is not None:
        return account
    return WhatsAppAccount.objects.create(
        organization=organization,
        business=business,
        status=WhatsAppConnectionStatus.DISCONNECTED,
        created_by=actor,
        updated_by=actor,
    )


def get_whatsapp_status(*, organization, business_id) -> dict:
    business = get_business_for_organization(organization=organization, business_id=business_id)
    account = get_or_create_account(organization=organization, business=business)
    payload = serialize_account(account)
    payload["message_counts"] = _message_counts(organization=organization, business=business)
    from messaging.models import WhatsAppInboundMessage
    from messaging.reminders import reminder_summary

    payload["reminder_24h"] = reminder_summary(organization=organization, business=business)
    payload["reminder_1h"] = reminder_summary(
        organization=organization,
        business=business,
        notification_type="APPOINTMENT_REMINDER_1H",
    )
    payload["review_request"] = reminder_summary(
        organization=organization,
        business=business,
        notification_type="REVIEW_REQUEST",
    )
    payload["inbound_count"] = WhatsAppInboundMessage.objects.filter(
        organization=organization,
        business=business,
    ).count()
    return payload


@transaction.atomic
def connect_whatsapp_account(
    *,
    organization,
    business_id,
    actor,
    access_token: str,
    phone_number_id: str,
    business_account_id: str,
    display_phone_number: str = "",
) -> dict:
    business = get_business_for_organization(organization=organization, business_id=business_id)
    require_encryption_configured()
    account = get_or_create_account(organization=organization, business=business, actor=actor)
    account = WhatsAppAccount.objects.select_for_update().get(pk=account.pk)
    provider = get_whatsapp_business_provider()
    phone = ""
    if (display_phone_number or "").strip():
        phone = normalize_public_phone(display_phone_number)
    try:
        snapshot = provider.configure(
            access_token=access_token,
            phone_number_id=phone_number_id,
            business_account_id=business_account_id,
        )
    except WhatsAppBusinessProviderError as exc:
        account.status = (
            WhatsAppConnectionStatus.REAUTH_REQUIRED
            if exc.code == "REAUTH_REQUIRED"
            else WhatsAppConnectionStatus.ERROR
        )
        account.last_error_code = exc.code
        account.last_error_message = str(exc)[:500]
        account.updated_by = actor
        account.save(
            update_fields=[
                "status",
                "last_error_code",
                "last_error_message",
                "updated_by",
                "updated_at",
            ]
        )
        raise ValidationError({"status": str(exc), "error_code": exc.code}) from None

    display = phone or snapshot.display_phone_number or ""
    if display and not display.startswith("+") and display.replace(" ", "").isdigit():
        display = normalize_public_phone(f"+{display.lstrip('+')}")
    account.phone_number_id = snapshot.phone_number_id[:64]
    account.business_account_id = (snapshot.business_account_id or business_account_id)[:64]
    account.display_phone_number = display[:20]
    account.verified_name = (snapshot.verified_name or "")[:255]
    account.access_token_encrypted = encrypt_token(access_token)
    account.status = WhatsAppConnectionStatus.CONNECTED
    account.connected_at = timezone.now()
    account.disconnected_at = None
    account.last_error_code = ""
    account.last_error_message = ""
    account.updated_by = actor
    account.save()
    logger.info("whatsapp.connected business_id=%s", business.id)
    return serialize_account(account)


@transaction.atomic
def disconnect_whatsapp_account(*, organization, business_id, actor) -> dict:
    business = get_business_for_organization(organization=organization, business_id=business_id)
    account = get_or_create_account(organization=organization, business=business, actor=actor)
    account = WhatsAppAccount.objects.select_for_update().get(pk=account.pk)
    token = ""
    try:
        token = decrypt_token(account.access_token_encrypted)
    except WhatsAppCryptoError:
        token = ""
    if token:
        try:
            get_whatsapp_business_provider().disconnect(access_token=token)
        except WhatsAppBusinessProviderError:
            logger.info("whatsapp.disconnect_provider_skipped business_id=%s", business.id)
    account.status = WhatsAppConnectionStatus.DISCONNECTED
    account.access_token_encrypted = ""
    account.token_expires_at = None
    account.disconnected_at = timezone.now()
    account.last_error_code = ""
    account.last_error_message = ""
    account.updated_by = actor
    account.save(
        update_fields=[
            "status",
            "access_token_encrypted",
            "token_expires_at",
            "disconnected_at",
            "last_error_code",
            "last_error_message",
            "updated_by",
            "updated_at",
        ]
    )
    return serialize_account(account)


def list_templates(*, organization, business_id):
    business = get_business_for_organization(organization=organization, business_id=business_id)
    return MessageTemplate.objects.filter(organization=organization, business=business)


@transaction.atomic
def create_template(
    *,
    organization,
    business_id,
    actor,
    name: str,
    language: str = "en",
    category: str = WhatsAppTemplateCategory.CUSTOM,
    purpose: str = "",
    body: str = "",
    variables: list | None = None,
    status: str = WhatsAppTemplateStatus.DRAFT,
) -> dict:
    business = get_business_for_organization(organization=organization, business_id=business_id)
    cleaned_name = (name or "").strip()
    cleaned_language = (language or "en").strip()
    if not cleaned_name:
        raise ValidationError({"name": "Template name is required."})
    if category not in WhatsAppTemplateCategory.values:
        raise ValidationError({"category": "Invalid template category."})
    cleaned_purpose = (purpose or "").strip()
    if cleaned_purpose and cleaned_purpose not in WhatsAppTemplatePurpose.values:
        raise ValidationError({"purpose": "Invalid template purpose."})
    try:
        cleaned_variables = validate_variable_names(variables)
    except ValueError:
        raise ValidationError(
            {"variables": "Variables must use the allowed template names."}
        ) from None
    if status not in WhatsAppTemplateStatus.values:
        raise ValidationError({"status": "Invalid template status."})
    try:
        template = MessageTemplate.objects.create(
            organization=organization,
            business=business,
            name=cleaned_name,
            purpose=cleaned_purpose,
            language=cleaned_language,
            category=category,
            status=status,
            body=body or "",
            variables=cleaned_variables,
            created_by=actor,
            updated_by=actor,
        )
    except IntegrityError as exc:
        raise ValidationError(
            {"name": "A template with this name and language already exists."}
        ) from exc
    return serialize_template(template)


def get_template(*, organization, business_id, template_id) -> MessageTemplate:
    business = get_business_for_organization(organization=organization, business_id=business_id)
    template = MessageTemplate.objects.filter(
        organization=organization,
        business=business,
        pk=template_id,
    ).first()
    if template is None:
        raise NotFound()
    return template


@transaction.atomic
def update_template(*, organization, business_id, template_id, actor, **fields) -> dict:
    template = get_template(
        organization=organization,
        business_id=business_id,
        template_id=template_id,
    )
    if "name" in fields and fields["name"] is not None:
        template.name = (fields["name"] or "").strip()
    if "language" in fields and fields["language"] is not None:
        template.language = (fields["language"] or "en").strip()
    if "category" in fields and fields["category"] is not None:
        if fields["category"] not in WhatsAppTemplateCategory.values:
            raise ValidationError({"category": "Invalid template category."})
        template.category = fields["category"]
    if "purpose" in fields and fields["purpose"] is not None:
        cleaned_purpose = (fields["purpose"] or "").strip()
        if cleaned_purpose and cleaned_purpose not in WhatsAppTemplatePurpose.values:
            raise ValidationError({"purpose": "Invalid template purpose."})
        template.purpose = cleaned_purpose
    if "body" in fields and fields["body"] is not None:
        template.body = fields["body"]
    if "variables" in fields and fields["variables"] is not None:
        try:
            template.variables = validate_variable_names(fields["variables"])
        except ValueError:
            raise ValidationError(
                {"variables": "Variables must use the allowed template names."}
            ) from None
    if "status" in fields and fields["status"] is not None:
        if fields["status"] not in WhatsAppTemplateStatus.values:
            raise ValidationError({"status": "Invalid template status."})
        template.status = fields["status"]
    if "provider_template_id" in fields and fields["provider_template_id"] is not None:
        template.provider_template_id = (fields["provider_template_id"] or "")[:128]
    template.updated_by = actor
    try:
        template.save()
    except IntegrityError as exc:
        raise ValidationError(
            {"name": "A template with this name and language already exists."}
        ) from exc
    return serialize_template(template)


@transaction.atomic
def delete_template(*, organization, business_id, template_id, actor) -> None:
    template = get_template(
        organization=organization,
        business_id=business_id,
        template_id=template_id,
    )
    template.soft_delete(actor=actor)


def list_messages(
    *,
    organization,
    business_id,
    appointment_id=None,
    purpose: str = "",
    message_type: str = "",
    status: str = "",
    created_after=None,
    created_before=None,
):
    business = get_business_for_organization(organization=organization, business_id=business_id)
    queryset = WhatsAppMessage.objects.filter(
        organization=organization, business=business
    ).select_related("customer", "appointment")
    if appointment_id:
        queryset = queryset.filter(appointment_id=appointment_id)
    if purpose:
        queryset = queryset.filter(purpose=purpose)
    if message_type:
        queryset = queryset.filter(message_type=message_type)
    if status:
        queryset = queryset.filter(status=status)
    if created_after is not None:
        queryset = queryset.filter(created_at__gte=created_after)
    if created_before is not None:
        queryset = queryset.filter(created_at__lte=created_before)
    return queryset.order_by("-created_at")


def list_inbound_messages(
    *,
    organization,
    business_id,
    customer_id=None,
    phone: str = "",
    message_type: str = "",
    processing_status: str = "",
    date_from=None,
    date_to=None,
):
    from messaging.models import WhatsAppInboundMessage

    business = get_business_for_organization(organization=organization, business_id=business_id)
    queryset = WhatsAppInboundMessage.objects.filter(
        organization=organization, business=business
    ).select_related("customer")
    if customer_id:
        queryset = queryset.filter(customer_id=customer_id)
    if phone:
        queryset = queryset.filter(phone_number=normalize_public_phone(phone))
    if message_type:
        queryset = queryset.filter(message_type=message_type)
    if processing_status:
        queryset = queryset.filter(processing_status=processing_status)
    if date_from is not None:
        queryset = queryset.filter(created_at__gte=date_from)
    if date_to is not None:
        queryset = queryset.filter(created_at__lte=date_to)
    return queryset.order_by("-created_at", "-id")


def serialize_inbound_message(message) -> dict:
    customer = message.customer if message.customer_id else None
    return {
        "id": str(message.id),
        "customer_name": customer.full_name if customer is not None else None,
        "phone_number": _mask_phone(message.phone_number),
        "message_type": message.message_type,
        "text": message.text,
        "provider_timestamp": (
            message.provider_timestamp.isoformat() if message.provider_timestamp else None
        ),
        "processing_status": message.processing_status,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def _mask_phone(phone: str) -> str:
    value = phone or ""
    if len(value) <= 7:
        return "****"
    return f"{value[:3]}******{value[-4:]}"


def _load_access_token(account: WhatsAppAccount) -> str:
    try:
        token = decrypt_token(account.access_token_encrypted)
    except WhatsAppCryptoError as exc:
        account.status = WhatsAppConnectionStatus.REAUTH_REQUIRED
        account.last_error_code = "DECRYPT_FAILED"
        account.last_error_message = "Stored credentials are unreadable."
        account.save(
            update_fields=["status", "last_error_code", "last_error_message", "updated_at"]
        )
        raise ValidationError(
            {"status": "Reconnect WhatsApp Business.", "error_code": "REAUTH_REQUIRED"}
        ) from exc
    if not token or account.status != WhatsAppConnectionStatus.CONNECTED:
        raise ValidationError(
            {"status": "WhatsApp Business is not connected.", "error_code": "NOT_CONNECTED"}
        )
    return token


def _normalize_recipient(phone: str) -> str:
    e164 = normalize_public_phone(phone)
    return e164.lstrip("+")


@transaction.atomic
def queue_whatsapp_message(
    *,
    organization,
    business_id,
    actor=None,
    phone_number: str,
    message_type: str = WhatsAppMessageType.TEXT,
    body: str = "",
    template_name: str = "",
    template_language: str = "",
    variables: list | None = None,
    rendered_text: str = "",
    customer_id=None,
    appointment_id=None,
    idempotency_key: str = "",
    purpose: str = "",
) -> WhatsAppMessage:
    """Create a QUEUED outbound message and schedule async delivery. Idempotent by key."""
    business = get_business_for_organization(organization=organization, business_id=business_id)
    key = (idempotency_key or "").strip()[:255]
    if key:
        existing = WhatsAppMessage.objects.filter(business=business, idempotency_key=key).first()
        if existing is not None:
            return existing

    recipient = _normalize_recipient(phone_number)
    if message_type not in WhatsAppMessageType.values:
        raise ValidationError({"message_type": "Invalid message type."})
    payload = {}
    if message_type == WhatsAppMessageType.TEXT:
        payload = {"body": body or ""}
    else:
        payload = {
            "template_name": template_name,
            "language": template_language or "en",
            "variables": [str(item) for item in (variables or [])],
        }
        if rendered_text:
            payload["rendered_text"] = rendered_text[:4000]
    try:
        message = WhatsAppMessage.objects.create(
            organization=organization,
            business=business,
            phone_number=f"+{recipient}",
            purpose=(purpose or "")[:32],
            message_type=message_type,
            template_name=(template_name or "")[:128],
            template_language=(template_language or "")[:16],
            payload=payload,
            status=WhatsAppMessageStatus.QUEUED,
            idempotency_key=key,
            customer_id=customer_id,
            appointment_id=appointment_id,
            created_by=actor,
            updated_by=actor,
        )
    except IntegrityError:
        if key:
            existing = WhatsAppMessage.objects.filter(
                business=business, idempotency_key=key
            ).first()
            if existing is not None:
                return existing
        raise
    message_id = str(message.id)

    def _schedule() -> None:
        from messaging.tasks import deliver_whatsapp_message

        deliver_whatsapp_message.delay(message_id)

    transaction.on_commit(_schedule)
    return message


def mark_message_status(
    message: WhatsAppMessage,
    new_status: str,
    *,
    provider_message_id: str = "",
    failure_code: str = "",
    failure_message: str = "",
) -> WhatsAppMessage:
    allowed = _ALLOWED_STATUSES.get(message.status, set())
    if new_status not in allowed and new_status != message.status:
        raise ValidationError({"status": "Invalid message status transition."})
    now = timezone.now()
    message.status = new_status
    if provider_message_id:
        message.provider_message_id = provider_message_id[:128]
    if new_status == WhatsAppMessageStatus.SENT:
        message.sent_at = now
        message.failure_code = ""
        message.failure_message = ""
    elif new_status == WhatsAppMessageStatus.DELIVERED:
        message.delivered_at = now
    elif new_status == WhatsAppMessageStatus.READ:
        message.read_at = now
    elif new_status == WhatsAppMessageStatus.FAILED:
        message.failed_at = now
        message.failure_code = (failure_code or "PROVIDER_ERROR")[:64]
        message.failure_message = (failure_message or "Send failed.")[:500]
    message.save()
    return message


def deliver_queued_message(*, message_id: str) -> str | None:
    """Send one queued message. Returns ``retry`` when a transient error should be retried."""
    from customers.retention_automation import note_retention_message_delivery
    from messaging.reminders import message_blocked_by_reminder, note_message_delivery

    def _note(message):
        note_message_delivery(message)
        note_retention_message_delivery(message)

    message = (
        WhatsAppMessage.objects.select_related("business", "organization")
        .filter(pk=message_id)
        .first()
    )
    if message is None or message.status != WhatsAppMessageStatus.QUEUED:
        return None
    if message_blocked_by_reminder(message):
        mark_message_status(message, WhatsAppMessageStatus.CANCELLED)
        _note(message)
        return None
    account = (
        WhatsAppAccount.objects.filter(
            organization_id=message.organization_id,
            business_id=message.business_id,
            status=WhatsAppConnectionStatus.CONNECTED,
        )
        .order_by("-updated_at")
        .first()
    )
    if account is None:
        mark_message_status(
            message,
            WhatsAppMessageStatus.FAILED,
            failure_code="NOT_CONNECTED",
            failure_message="WhatsApp Business is not connected.",
        )
        _note(message)
        return None
    try:
        token = _load_access_token(account)
    except ValidationError as exc:
        detail = getattr(exc, "detail", {}) or {}
        code = "REAUTH_REQUIRED"
        if isinstance(detail, dict) and detail.get("error_code"):
            code = str(detail["error_code"])
        mark_message_status(
            message,
            WhatsAppMessageStatus.FAILED,
            failure_code=code,
            failure_message="WhatsApp authorization is not usable.",
        )
        _note(message)
        return None

    provider = get_whatsapp_business_provider()
    to = message.phone_number.lstrip("+")
    try:
        if message.message_type == WhatsAppMessageType.TEMPLATE:
            payload = message.payload or {}
            result = provider.send_template_message(
                access_token=token,
                phone_number_id=account.phone_number_id,
                to=to,
                template_name=message.template_name,
                language=message.template_language or "en",
                variables=list(payload.get("variables") or []),
            )
        else:
            result = provider.send_message(
                access_token=token,
                phone_number_id=account.phone_number_id,
                to=to,
                body=str((message.payload or {}).get("body") or ""),
            )
    except WhatsAppBusinessProviderError as exc:
        message.delivery_attempts = (message.delivery_attempts or 0) + 1
        message.save(update_fields=["delivery_attempts", "updated_at"])
        if exc.code == "REAUTH_REQUIRED":
            account.status = WhatsAppConnectionStatus.REAUTH_REQUIRED
            account.last_error_code = exc.code
            account.last_error_message = str(exc)[:500]
            account.save(
                update_fields=[
                    "status",
                    "last_error_code",
                    "last_error_message",
                    "updated_at",
                ]
            )
        if exc.transient and message.delivery_attempts < 3:
            logger.info(
                "whatsapp.delivery_retry message_id=%s code=%s attempt=%s",
                message.id,
                exc.code,
                message.delivery_attempts,
            )
            return "retry"
        mark_message_status(
            message,
            WhatsAppMessageStatus.FAILED,
            failure_code=exc.code,
            failure_message=str(exc),
        )
        _note(message)
        logger.info(
            "whatsapp.delivery_failed message_id=%s code=%s",
            message.id,
            exc.code,
        )
        return None

    mark_message_status(
        message,
        WhatsAppMessageStatus.SENT,
        provider_message_id=result.provider_message_id,
    )
    _note(message)
    return None


def sync_template_provider_status(*, organization, business_id, template_id) -> dict:
    """Read provider template status. Does not create or submit templates."""
    template = get_template(
        organization=organization,
        business_id=business_id,
        template_id=template_id,
    )
    account = (
        WhatsAppAccount.objects.filter(
            organization=organization,
            business_id=template.business_id,
            status=WhatsAppConnectionStatus.CONNECTED,
            deleted_at__isnull=True,
        )
        .order_by("-updated_at")
        .first()
    )
    if account is None:
        raise ValidationError(
            {"status": "WhatsApp Business is not connected.", "error_code": "NOT_CONNECTED"}
        )
    token = _load_access_token(account)
    snapshot = get_whatsapp_business_provider().fetch_template_status(
        access_token=token,
        business_account_id=account.business_account_id,
        name=template.name,
        language=template.language,
    )
    if snapshot.provider_template_id:
        template.provider_template_id = snapshot.provider_template_id[:128]
    template.provider_status = (snapshot.status or "")[:32]
    template.save(update_fields=["provider_status", "provider_template_id", "updated_at"])
    return serialize_template(template)


def sync_whatsapp_templates(*, organization, business_id, actor) -> dict:
    """Copy provider template metadata. Does not replace a local body or local status."""
    business = get_business_for_organization(organization=organization, business_id=business_id)
    account = (
        WhatsAppAccount.objects.filter(
            organization=organization,
            business=business,
            status=WhatsAppConnectionStatus.CONNECTED,
            deleted_at__isnull=True,
        )
        .order_by("-updated_at")
        .first()
    )
    if account is None:
        raise ValidationError(
            {"status": "WhatsApp Business is not connected.", "error_code": "NOT_CONNECTED"}
        )
    token = _load_access_token(account)
    remote = get_whatsapp_business_provider().list_templates(
        access_token=token,
        business_account_id=account.business_account_id,
    )
    created = updated = 0
    for item in remote:
        if not item.name or not item.language:
            continue
        local = MessageTemplate.objects.filter(
            organization=organization,
            business=business,
            name=item.name[:128],
            language=item.language[:16],
            deleted_at__isnull=True,
        ).first()
        if local is None:
            MessageTemplate.objects.create(
                organization=organization,
                business=business,
                name=item.name[:128],
                language=item.language[:16],
                category=item.category
                if item.category in WhatsAppTemplateCategory.values
                else "CUSTOM",
                status=WhatsAppTemplateStatus.DRAFT,
                provider_status=(item.status or "")[:32],
                provider_template_id=(item.provider_template_id or "")[:128],
                body=(item.body or "")[:4000],
                created_by=actor,
                updated_by=actor,
            )
            created += 1
            continue
        local.provider_status = (item.status or "")[:32]
        if item.provider_template_id:
            local.provider_template_id = item.provider_template_id[:128]
        if not (local.body or "").strip() and item.body:
            local.body = item.body[:4000]
        local.updated_by = actor
        local.save()
        updated += 1
    return {"created": created, "updated": updated}


def submit_whatsapp_template(*, organization, business_id, template_id, actor) -> dict:
    """Send a local template to the provider. Mock returns PENDING, not APPROVED."""
    import re

    template = get_template(
        organization=organization,
        business_id=business_id,
        template_id=template_id,
    )
    if not re.fullmatch(r"[a-z0-9_]{1,128}", template.name or ""):
        raise ValidationError({"name": "Use lowercase letters, numbers, and underscores."})
    if not template.language:
        raise ValidationError({"language": "Language is required."})
    if template.category not in WhatsAppTemplateCategory.values:
        raise ValidationError({"category": "Category is not supported."})
    account = (
        WhatsAppAccount.objects.filter(
            organization=organization,
            business_id=template.business_id,
            status=WhatsAppConnectionStatus.CONNECTED,
            deleted_at__isnull=True,
        )
        .order_by("-updated_at")
        .first()
    )
    if account is None:
        raise ValidationError(
            {"status": "WhatsApp Business is not connected.", "error_code": "NOT_CONNECTED"}
        )
    token = _load_access_token(account)
    result = get_whatsapp_business_provider().submit_template(
        access_token=token,
        business_account_id=account.business_account_id,
        name=template.name,
        language=template.language,
        category=template.category,
        body=template.body or "",
    )
    template.provider_template_id = (result.provider_template_id or "")[:128]
    template.provider_status = (result.status or "PENDING")[:32]
    template.updated_by = actor
    template.save(
        update_fields=["provider_template_id", "provider_status", "updated_by", "updated_at"]
    )
    return serialize_template(template)
