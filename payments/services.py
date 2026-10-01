"""Payment domain services. Provider verification/webhook is authoritative."""

from __future__ import annotations

import hashlib
import logging
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from booking.models import Appointment, AppointmentStatus
from businesses.models import BusinessPaymentMode
from payments.exceptions import (
    PaymentAlreadyPaid,
    PaymentAmountInvalid,
    PaymentError,
    PaymentNotEligible,
    PaymentProviderError,
    RefundNotAllowed,
)
from payments.models import (
    AppointmentPaymentStatus,
    Payment,
    PaymentOrder,
    PaymentOrderStatus,
    PaymentProviderKind,
    PaymentStatus,
    PaymentWebhookEvent,
    Refund,
    RefundStatus,
    WebhookEventStatus,
)
from payments.providers import (
    from_minor_units,
    get_payment_provider,
    get_public_key_id,
    require_valid_payment_signature,
    to_minor_units,
)

logger = logging.getLogger("payments.services")

PAYABLE_APPOINTMENT_STATUSES = frozenset(
    {
        AppointmentStatus.PENDING,
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.CHECKED_IN,
    }
)

_TERMINAL_PAYMENT_STATUSES = frozenset(
    {
        PaymentStatus.PAID,
        PaymentStatus.PARTIALLY_REFUNDED,
        PaymentStatus.REFUNDED,
    }
)


def business_payment_mode(business) -> str:
    return getattr(business, "payment_mode", None) or BusinessPaymentMode.NONE


def resolve_payable_amount(*, appointment: Appointment) -> Decimal | None:
    """Server-side amount from appointment snapshots. Never trust the client.

    NONE → no payment.
    FULL → appointment.total_price.
    DEPOSIT → appointment.deposit_amount when > 0; otherwise no payment required.
    """
    mode = business_payment_mode(appointment.business)
    if mode == BusinessPaymentMode.NONE:
        return None
    if mode == BusinessPaymentMode.FULL:
        amount = appointment.total_price or Decimal("0.00")
        return amount if amount > 0 else None
    if mode == BusinessPaymentMode.DEPOSIT:
        amount = appointment.deposit_amount or Decimal("0.00")
        return amount if amount > 0 else None
    return None


def initial_appointment_payment_status(*, appointment: Appointment) -> str:
    amount = resolve_payable_amount(appointment=appointment)
    if amount is None:
        return AppointmentPaymentStatus.NOT_REQUIRED
    return AppointmentPaymentStatus.PENDING


def appointment_requires_payment(*, appointment: Appointment) -> bool:
    return (
        appointment.payment_status
        in {
            AppointmentPaymentStatus.PENDING,
            AppointmentPaymentStatus.PARTIALLY_PAID,
        }
        and resolve_payable_amount(appointment=appointment) is not None
    )


def _assert_payment_eligible(appointment: Appointment) -> Decimal:
    if appointment.deleted_at is not None:
        raise PaymentNotEligible("Appointment is not available.")
    if appointment.status not in PAYABLE_APPOINTMENT_STATUSES:
        raise PaymentNotEligible("Appointment status does not allow payment.")
    if appointment.payment_status == AppointmentPaymentStatus.PAID:
        raise PaymentAlreadyPaid()
    if appointment.payment_status == AppointmentPaymentStatus.REFUNDED:
        raise PaymentNotEligible("Appointment payment was refunded.")
    if appointment.payment_status == AppointmentPaymentStatus.NOT_REQUIRED:
        raise PaymentNotEligible("Online payment is not required for this appointment.")
    amount = resolve_payable_amount(appointment=appointment)
    if amount is None or amount <= 0:
        raise PaymentNotEligible("No payable amount for this appointment.")
    return amount


def serialize_public_payment_state(
    *, appointment: Appointment, payment: Payment | None = None
) -> dict:
    payload = {
        "status": appointment.payment_status,
        "payment_required": appointment_requires_payment(appointment=appointment),
        "currency": appointment.currency,
        "amount": str(resolve_payable_amount(appointment=appointment) or Decimal("0.00")),
        "paid_at": None,
        "payment_reference": None,
    }
    if payment is not None:
        payload["status"] = (
            AppointmentPaymentStatus.PAID
            if payment.status == PaymentStatus.PAID
            else appointment.payment_status
        )
        payload["paid_at"] = payment.paid_at.isoformat() if payment.paid_at else None
        payload["payment_reference"] = payment.public_reference
        payload["amount"] = str(payment.amount_paid or payment.amount)
        payload["currency"] = payment.currency
    return payload


@transaction.atomic
def create_payment_order_for_appointment(
    *,
    appointment: Appointment,
    idempotency_key: str,
) -> dict:
    key = (idempotency_key or "").strip()
    if not key or len(key) > 255:
        raise PaymentError("Invalid idempotency key.", code="INVALID_IDEMPOTENCY_KEY")

    appointment = (
        Appointment.objects.select_for_update()
        .select_related("organization", "business", "location", "customer")
        .filter(pk=appointment.pk)
        .first()
    )
    if appointment is None:
        raise PaymentNotEligible("Appointment is not available.")

    existing = PaymentOrder.objects.filter(
        organization_id=appointment.organization_id,
        idempotency_key=key,
    ).first()
    if existing is not None:
        return _checkout_payload(existing)

    amount = _assert_payment_eligible(appointment)
    currency = (appointment.currency or "INR").upper()
    provider = get_payment_provider()
    amount_minor = to_minor_units(amount, currency)
    if amount_minor < 100 and currency == "INR":
        raise PaymentAmountInvalid("Amount must be at least ₹1.00.")

    order = PaymentOrder(
        organization_id=appointment.organization_id,
        business_id=appointment.business_id,
        location_id=appointment.location_id,
        appointment=appointment,
        customer_id=appointment.customer_id,
        provider=_provider_kind(provider.name),
        status=PaymentOrderStatus.CREATED,
        amount=amount,
        currency=currency,
        idempotency_key=key,
        metadata={"appointment_public_reference": appointment.public_reference},
    )
    try:
        with transaction.atomic():
            order.save()
    except IntegrityError:
        existing = PaymentOrder.objects.filter(
            organization_id=appointment.organization_id,
            idempotency_key=key,
        ).first()
        if existing is None:
            raise
        return _checkout_payload(existing)

    try:
        remote = provider.create_order(
            amount_minor=amount_minor,
            currency=currency,
            receipt=order.public_reference,
            notes={
                "appointment": appointment.public_reference,
                "business": str(appointment.business_id),
            },
        )
    except PaymentProviderError:
        order.status = PaymentOrderStatus.FAILED
        order.save(update_fields=["status", "updated_at"])
        raise

    order.provider_order_id = remote.provider_order_id
    order.status = PaymentOrderStatus.ATTEMPTED
    order.save(update_fields=["provider_order_id", "status", "updated_at"])
    return _checkout_payload(order)


def _provider_kind(name: str) -> str:
    if name == "mock":
        return PaymentProviderKind.MOCK
    return PaymentProviderKind.RAZORPAY


def _checkout_payload(order: PaymentOrder) -> dict:
    return {
        "payment_order_id": order.public_reference,
        "provider": order.provider,
        "provider_order_id": order.provider_order_id or "",
        "amount": to_minor_units(order.amount, order.currency),
        "currency": order.currency,
        "key_id": get_public_key_id(),
        "status": order.status,
    }


@transaction.atomic
def verify_checkout_payment(
    *,
    appointment: Appointment,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> dict:
    appointment = (
        Appointment.objects.select_for_update()
        .select_related("organization", "business", "location", "customer")
        .filter(pk=appointment.pk)
        .first()
    )
    if appointment is None or appointment.deleted_at is not None:
        raise PaymentNotEligible("Appointment is not available.")

    order_id = (razorpay_order_id or "").strip()
    payment_id = (razorpay_payment_id or "").strip()
    signature = (razorpay_signature or "").strip()
    if not order_id or not payment_id or not signature:
        raise PaymentError("Missing payment verification fields.", code="INVALID_PAYLOAD")

    order = (
        PaymentOrder.objects.select_for_update()
        .filter(
            provider_order_id=order_id,
            appointment_id=appointment.id,
            organization_id=appointment.organization_id,
            business_id=appointment.business_id,
        )
        .first()
    )
    if order is None:
        raise PaymentNotEligible("Payment order was not found for this appointment.")

    existing = (
        Payment.objects.select_for_update()
        .filter(
            provider_payment_id=payment_id,
            organization_id=appointment.organization_id,
        )
        .first()
    )
    if existing is not None and existing.status in _TERMINAL_PAYMENT_STATUSES:
        sync_appointment_payment_status(appointment=appointment)
        return serialize_public_payment_state(appointment=appointment, payment=existing)

    provider = get_payment_provider()
    require_valid_payment_signature(
        provider=provider,
        provider_order_id=order_id,
        provider_payment_id=payment_id,
        signature=signature,
    )

    remote = provider.fetch_payment(provider_payment_id=payment_id)
    if remote.provider_order_id and remote.provider_order_id != order_id:
        raise PaymentNotEligible("Payment does not belong to this order.")

    expected_minor = to_minor_units(order.amount, order.currency)
    if remote.amount_minor != expected_minor:
        raise PaymentAmountInvalid("Paid amount does not match the order.")
    if (remote.currency or "").upper() != order.currency.upper():
        raise PaymentAmountInvalid("Paid currency does not match the order.")

    status = _map_provider_payment_status(remote.status)
    payment = _upsert_payment_from_provider(
        appointment=appointment,
        order=order,
        provider_payment_id=payment_id,
        provider_order_id=order_id,
        signature=signature,
        amount=from_minor_units(remote.amount_minor, remote.currency),
        currency=remote.currency.upper(),
        status=status,
        provider_name=provider.name,
    )
    if status == PaymentStatus.PAID:
        order.status = PaymentOrderStatus.PAID
        order.save(update_fields=["status", "updated_at"])
    elif status == PaymentStatus.FAILED:
        order.status = PaymentOrderStatus.FAILED
        order.save(update_fields=["status", "updated_at"])

    sync_appointment_payment_status(appointment=appointment)
    appointment.refresh_from_db()
    return serialize_public_payment_state(appointment=appointment, payment=payment)


def _map_provider_payment_status(raw: str) -> str:
    value = (raw or "").strip().lower()
    if value in {"captured", "paid"}:
        return PaymentStatus.PAID
    if value in {"authorized"}:
        return PaymentStatus.AUTHORIZED
    if value in {"failed"}:
        return PaymentStatus.FAILED
    if value in {"refunded"}:
        return PaymentStatus.REFUNDED
    return PaymentStatus.PENDING


def _upsert_payment_from_provider(
    *,
    appointment: Appointment,
    order: PaymentOrder | None,
    provider_payment_id: str,
    provider_order_id: str,
    signature: str,
    amount: Decimal,
    currency: str,
    status: str,
    provider_name: str,
) -> Payment:
    now = timezone.now()
    payment = (
        Payment.objects.select_for_update()
        .filter(
            provider=PaymentProviderKind.RAZORPAY
            if provider_name == "razorpay"
            else PaymentProviderKind.MOCK,
            provider_payment_id=provider_payment_id,
        )
        .first()
    )
    if payment is None:
        payment = Payment(
            organization_id=appointment.organization_id,
            business_id=appointment.business_id,
            location_id=appointment.location_id,
            appointment=appointment,
            customer_id=appointment.customer_id,
            payment_order=order,
            provider=_provider_kind(provider_name),
            amount=amount,
            currency=currency,
            provider_order_id=provider_order_id,
            provider_payment_id=provider_payment_id,
        )

    # Never downgrade paid/refunded terminal money states via provider upsert.
    if payment.status == PaymentStatus.REFUNDED:
        return payment
    if payment.status == PaymentStatus.PARTIALLY_REFUNDED:
        return payment
    if payment.status == PaymentStatus.PAID and status != PaymentStatus.PAID:
        return payment

    payment.provider_signature = (signature or "")[:255]
    payment.amount = amount
    payment.currency = currency
    payment.provider_order_id = provider_order_id
    payment.status = status
    if status == PaymentStatus.PAID:
        payment.amount_paid = amount
        payment.paid_at = payment.paid_at or now
        payment.failed_at = None
        payment.failure_code = ""
        payment.failure_reason = ""
    elif status == PaymentStatus.FAILED:
        payment.failed_at = now
        payment.failure_code = payment.failure_code or "provider_failed"
        payment.failure_reason = payment.failure_reason or "Payment failed"
    payment.save()
    return payment


def sync_appointment_payment_status(*, appointment: Appointment) -> None:
    """Update lightweight Appointment.payment_status from Payment records only."""
    payments = list(Payment.objects.filter(appointment_id=appointment.id).order_by("-created_at"))
    if not payments:
        return
    if any(p.status == PaymentStatus.REFUNDED for p in payments) and all(
        p.status in {PaymentStatus.REFUNDED, PaymentStatus.FAILED, PaymentStatus.CANCELLED}
        for p in payments
        if p.amount_paid > 0 or p.status == PaymentStatus.REFUNDED
    ):
        # If any fully refunded and no outstanding paid remainder.
        paid = sum((p.amount_paid for p in payments), Decimal("0.00"))
        refunded = sum((p.amount_refunded for p in payments), Decimal("0.00"))
        if refunded >= paid > 0:
            _set_appointment_payment_status(appointment, AppointmentPaymentStatus.REFUNDED)
            return

    paid_total = sum(
        (
            p.amount_paid - p.amount_refunded
            for p in payments
            if p.status in _TERMINAL_PAYMENT_STATUSES
        ),
        Decimal("0.00"),
    )
    due = resolve_payable_amount(appointment=appointment) or Decimal("0.00")
    if paid_total <= 0:
        if appointment.payment_status == AppointmentPaymentStatus.NOT_REQUIRED:
            return
        if any(p.status == PaymentStatus.FAILED for p in payments):
            _set_appointment_payment_status(appointment, AppointmentPaymentStatus.PENDING)
        return
    if due > 0 and paid_total < due:
        _set_appointment_payment_status(appointment, AppointmentPaymentStatus.PARTIALLY_PAID)
        return
    if any(p.status == PaymentStatus.PARTIALLY_REFUNDED for p in payments):
        _set_appointment_payment_status(appointment, AppointmentPaymentStatus.PARTIALLY_PAID)
        return
    _set_appointment_payment_status(appointment, AppointmentPaymentStatus.PAID)


def _set_appointment_payment_status(appointment: Appointment, status: str) -> None:
    if appointment.payment_status == status:
        return
    appointment.payment_status = status
    appointment.save(update_fields=["payment_status", "updated_at"])


@transaction.atomic
def request_refund(
    *,
    payment: Payment,
    amount: Decimal,
    reason: str,
    idempotency_key: str,
    actor=None,
) -> Refund:
    key = (idempotency_key or "").strip()
    if not key:
        raise PaymentError("Invalid idempotency key.", code="INVALID_IDEMPOTENCY_KEY")
    if amount is None or amount <= 0:
        raise RefundNotAllowed("Refund amount must be positive.")

    payment = Payment.objects.select_for_update().select_related("appointment").get(pk=payment.pk)
    existing = Refund.objects.filter(
        organization_id=payment.organization_id,
        idempotency_key=key,
    ).first()
    if existing is not None:
        return existing

    if payment.status not in {
        PaymentStatus.PAID,
        PaymentStatus.PARTIALLY_REFUNDED,
    }:
        raise RefundNotAllowed("Only paid payments can be refunded.")
    if amount > payment.refundable_amount:
        raise RefundNotAllowed("Refund amount exceeds refundable balance.")

    refund = Refund.objects.create(
        organization_id=payment.organization_id,
        business_id=payment.business_id,
        payment=payment,
        amount=amount,
        currency=payment.currency,
        status=RefundStatus.PENDING,
        reason=(reason or "")[:255],
        idempotency_key=key,
    )
    provider = get_payment_provider()
    try:
        remote = provider.refund_payment(
            provider_payment_id=payment.provider_payment_id,
            amount_minor=to_minor_units(amount, payment.currency),
            notes={"reason": (reason or "")[:100]},
        )
    except PaymentProviderError as exc:
        refund.status = RefundStatus.FAILED
        refund.failure_reason = str(exc)[:255]
        refund.save(update_fields=["status", "failure_reason", "updated_at"])
        raise

    refund.provider_refund_id = remote.provider_refund_id
    refund.status = RefundStatus.PROCESSED
    refund.processed_at = timezone.now()
    refund.save(update_fields=["provider_refund_id", "status", "processed_at", "updated_at"])
    payment.amount_refunded = (payment.amount_refunded or Decimal("0.00")) + amount
    if payment.amount_refunded >= payment.amount_paid:
        payment.status = PaymentStatus.REFUNDED
        payment.refunded_at = timezone.now()
    else:
        payment.status = PaymentStatus.PARTIALLY_REFUNDED
    payment.save(update_fields=["amount_refunded", "status", "refunded_at", "updated_at"])
    sync_appointment_payment_status(appointment=payment.appointment)
    return refund


def process_razorpay_webhook(*, raw_body: bytes, signature: str, payload: dict) -> dict:
    provider = get_payment_provider()
    if not provider.verify_webhook_signature(raw_body=raw_body, signature=signature or ""):
        from payments.exceptions import PaymentSignatureInvalid

        raise PaymentSignatureInvalid("Webhook signature is invalid.")

    event_type = str(payload.get("event") or "")
    provider_event_id = str(
        payload.get("id") or payload.get("event_id") or hashlib.sha256(raw_body).hexdigest()
    )
    payload_hash = hashlib.sha256(raw_body).hexdigest()

    try:
        with transaction.atomic():
            event = PaymentWebhookEvent.objects.create(
                provider=_provider_kind(provider.name),
                provider_event_id=provider_event_id,
                event_type=event_type[:128],
                payload_hash=payload_hash,
                status=WebhookEventStatus.RECEIVED,
            )
    except IntegrityError:
        return {"duplicate": True, "processed": False}

    try:
        applied = _apply_webhook_event(event_type=event_type, payload=payload)
        event.status = WebhookEventStatus.PROCESSED if applied else WebhookEventStatus.IGNORED
        event.processed_at = timezone.now()
        event.save(update_fields=["status", "processed_at", "updated_at"])
        return {"duplicate": False, "processed": applied}
    except Exception as exc:
        logger.exception("payments.webhook_processing_failed")
        event.status = WebhookEventStatus.FAILED
        event.error_message = str(exc)[:255]
        event.processed_at = timezone.now()
        event.save(update_fields=["status", "error_message", "processed_at", "updated_at"])
        raise


def _apply_webhook_event(*, event_type: str, payload: dict) -> bool:
    entity = ((payload.get("payload") or {}).get("payment") or {}).get("entity") or {}
    if not entity and "refund" in event_type:
        entity = ((payload.get("payload") or {}).get("refund") or {}).get("entity") or {}
    if not entity and event_type.startswith("order."):
        entity = ((payload.get("payload") or {}).get("order") or {}).get("entity") or {}

    if event_type in {"payment.captured", "payment.authorized", "order.paid"}:
        return _apply_payment_webhook(event_type=event_type, entity=entity)
    if event_type == "payment.failed":
        return _apply_payment_failed(entity=entity)
    if event_type in {"refund.created", "refund.processed", "refund.failed"}:
        return _apply_refund_webhook(event_type=event_type, entity=entity)
    return False


@transaction.atomic
def _apply_payment_webhook(*, event_type: str, entity: dict) -> bool:
    payment_id = str(entity.get("id") or "")
    order_id = str(entity.get("order_id") or "")
    if not payment_id:
        return False
    order = None
    if order_id:
        order = (
            PaymentOrder.objects.select_for_update()
            .select_related("appointment", "appointment__business")
            .filter(provider_order_id=order_id)
            .first()
        )
    if order is None:
        return False
    amount_minor = int(entity.get("amount") or 0)
    currency = str(entity.get("currency") or order.currency).upper()
    if amount_minor and amount_minor != to_minor_units(order.amount, order.currency):
        logger.warning("payments.webhook_amount_mismatch order=%s", order.public_reference)
        return False
    status = PaymentStatus.AUTHORIZED if event_type == "payment.authorized" else PaymentStatus.PAID
    if event_type == "order.paid":
        status = PaymentStatus.PAID
    payment = _upsert_payment_from_provider(
        appointment=order.appointment,
        order=order,
        provider_payment_id=payment_id,
        provider_order_id=order_id,
        signature="",
        amount=from_minor_units(
            amount_minor or to_minor_units(order.amount, order.currency), currency
        ),
        currency=currency,
        status=status,
        provider_name=get_payment_provider().name,
    )
    if status == PaymentStatus.PAID:
        order.status = PaymentOrderStatus.PAID
        order.save(update_fields=["status", "updated_at"])
    sync_appointment_payment_status(appointment=order.appointment)
    return payment is not None


@transaction.atomic
def _apply_payment_failed(*, entity: dict) -> bool:
    payment_id = str(entity.get("id") or "")
    order_id = str(entity.get("order_id") or "")
    if not order_id:
        return False
    order = (
        PaymentOrder.objects.select_for_update()
        .select_related("appointment")
        .filter(provider_order_id=order_id)
        .first()
    )
    if order is None:
        return False
    if order.status == PaymentOrderStatus.PAID:
        return False
    order.status = PaymentOrderStatus.FAILED
    order.save(update_fields=["status", "updated_at"])
    if payment_id:
        _upsert_payment_from_provider(
            appointment=order.appointment,
            order=order,
            provider_payment_id=payment_id,
            provider_order_id=order_id,
            signature="",
            amount=order.amount,
            currency=order.currency,
            status=PaymentStatus.FAILED,
            provider_name=get_payment_provider().name,
        )
    return True


@transaction.atomic
def _apply_refund_webhook(*, event_type: str, entity: dict) -> bool:
    provider_refund_id = str(entity.get("id") or "")
    payment_id = str(entity.get("payment_id") or "")
    if not payment_id:
        return False
    payment = (
        Payment.objects.select_for_update()
        .select_related("appointment")
        .filter(provider_payment_id=payment_id)
        .first()
    )
    if payment is None:
        return False
    if event_type == "refund.failed":
        return False
    amount_minor = int(entity.get("amount") or 0)
    amount = from_minor_units(amount_minor, payment.currency) if amount_minor else Decimal("0.00")
    if amount <= 0:
        return False
    if provider_refund_id and Refund.objects.filter(provider_refund_id=provider_refund_id).exists():
        return False
    # Apply refund totals idempotently when webhook arrives without prior request_refund.
    new_refunded = payment.amount_refunded + amount
    if new_refunded > payment.amount_paid:
        return False
    payment.amount_refunded = new_refunded
    if payment.amount_refunded >= payment.amount_paid:
        payment.status = PaymentStatus.REFUNDED
        payment.refunded_at = timezone.now()
    else:
        payment.status = PaymentStatus.PARTIALLY_REFUNDED
    payment.save(update_fields=["amount_refunded", "status", "refunded_at", "updated_at"])
    if provider_refund_id:
        Refund.objects.get_or_create(
            organization_id=payment.organization_id,
            idempotency_key=f"webhook:{provider_refund_id}",
            defaults={
                "business_id": payment.business_id,
                "payment": payment,
                "amount": amount,
                "currency": payment.currency,
                "status": RefundStatus.PROCESSED,
                "provider_refund_id": provider_refund_id,
                "reason": "webhook",
                "processed_at": timezone.now(),
            },
        )
    sync_appointment_payment_status(appointment=payment.appointment)
    return True
