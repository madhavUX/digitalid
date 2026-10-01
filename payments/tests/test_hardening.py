"""Phase 6.0.1 payment hardening: isolation, mismatches, downgrade guards, ordering."""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from booking.tests.test_public_booking_api import PublicBookingAPITestCase
from businesses.models import Business, BusinessPaymentMode
from payments.exceptions import PaymentAmountInvalid, PaymentNotEligible, RefundNotAllowed
from payments.models import (
    AppointmentPaymentStatus,
    Payment,
    PaymentOrder,
    PaymentOrderStatus,
    PaymentStatus,
)
from payments.providers import MockPaymentProvider
from payments.services import (
    _upsert_payment_from_provider,
    create_payment_order_for_appointment,
    request_refund,
    sync_appointment_payment_status,
    verify_checkout_payment,
)


@override_settings(RAZORPAY_PROVIDER="mock", RAZORPAY_WEBHOOK_SECRET="mock_webhook")
class PaymentHardeningTests(PublicBookingAPITestCase):
    def _enable_full(self, ctx):
        business = Business.objects.get(pk=ctx["business"]["id"])
        business.payment_mode = BusinessPaymentMode.FULL
        business.save(update_fields=["payment_mode", "updated_at"])

    def _book(self, *, email, phone, hhmm="10:00"):
        ctx = self._seed_bookable_monday(
            owner_email=email,
            org_name=f"Hard {email}",
            phone=phone,
            buffer_before_minutes=0,
            buffer_after_minutes=0,
        )
        self._enable_full(ctx)
        payload = self._book_payload(ctx, hhmm, staff_id=ctx["staff"]["id"], phone=phone[-10:])
        created = self._public_create(payload)
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        from booking.models import Appointment

        appointment = Appointment.objects.get(public_reference=created.data["public_reference"])
        return ctx, appointment

    def _sign(self, order_id: str, payment_id: str) -> str:
        return hashlib.sha256(f"{order_id}|{payment_id}|mock".encode()).hexdigest()

    def _remote(
        self, *, payment_id, order_id, amount_minor, currency="INR", status_name="captured"
    ):
        return type(
            "R",
            (),
            {
                "provider_payment_id": payment_id,
                "provider_order_id": order_id,
                "amount_minor": amount_minor,
                "currency": currency,
                "status": status_name,
                "method": "upi",
            },
        )()

    def test_wrong_amount_currency_and_order_rejected(self):
        ctx, appointment = self._book(email="hard1@example.com", phone="+919900002001")
        order = create_payment_order_for_appointment(
            appointment=appointment, idempotency_key="hard-1"
        )
        payment_id = "pay_hard_1"
        signature = self._sign(order["provider_order_id"], payment_id)

        with patch.object(
            MockPaymentProvider,
            "fetch_payment",
            return_value=self._remote(
                payment_id=payment_id,
                order_id=order["provider_order_id"],
                amount_minor=order["amount"] + 100,
            ),
        ):
            with self.assertRaises(PaymentAmountInvalid):
                verify_checkout_payment(
                    appointment=appointment,
                    razorpay_order_id=order["provider_order_id"],
                    razorpay_payment_id=payment_id,
                    razorpay_signature=signature,
                )

        with patch.object(
            MockPaymentProvider,
            "fetch_payment",
            return_value=self._remote(
                payment_id=payment_id,
                order_id=order["provider_order_id"],
                amount_minor=order["amount"],
                currency="USD",
            ),
        ):
            with self.assertRaises(PaymentAmountInvalid):
                verify_checkout_payment(
                    appointment=appointment,
                    razorpay_order_id=order["provider_order_id"],
                    razorpay_payment_id=payment_id,
                    razorpay_signature=signature,
                )

        with patch.object(
            MockPaymentProvider,
            "fetch_payment",
            return_value=self._remote(
                payment_id=payment_id,
                order_id="order_other",
                amount_minor=order["amount"],
            ),
        ):
            with self.assertRaises(PaymentNotEligible):
                verify_checkout_payment(
                    appointment=appointment,
                    razorpay_order_id=order["provider_order_id"],
                    razorpay_payment_id=payment_id,
                    razorpay_signature=signature,
                )

        # Wrong order id for this appointment
        with self.assertRaises(PaymentNotEligible):
            verify_checkout_payment(
                appointment=appointment,
                razorpay_order_id="order_does_not_exist",
                razorpay_payment_id=payment_id,
                razorpay_signature=signature,
            )

    def test_paid_never_downgrades_and_refunded_stays(self):
        ctx, appointment = self._book(email="hard2@example.com", phone="+919900002002")
        order = create_payment_order_for_appointment(
            appointment=appointment, idempotency_key="hard-2"
        )
        row = PaymentOrder.objects.get(public_reference=order["payment_order_id"])
        payment = _upsert_payment_from_provider(
            appointment=appointment,
            order=row,
            provider_payment_id="pay_hard_2",
            provider_order_id=row.provider_order_id,
            signature="",
            amount=appointment.total_price,
            currency="INR",
            status=PaymentStatus.PAID,
            provider_name="mock",
        )
        self.assertEqual(payment.status, PaymentStatus.PAID)

        again = _upsert_payment_from_provider(
            appointment=appointment,
            order=row,
            provider_payment_id="pay_hard_2",
            provider_order_id=row.provider_order_id,
            signature="",
            amount=appointment.total_price,
            currency="INR",
            status=PaymentStatus.FAILED,
            provider_name="mock",
        )
        self.assertEqual(again.status, PaymentStatus.PAID)
        again.refresh_from_db()
        self.assertEqual(again.status, PaymentStatus.PAID)

        pending = _upsert_payment_from_provider(
            appointment=appointment,
            order=row,
            provider_payment_id="pay_hard_2",
            provider_order_id=row.provider_order_id,
            signature="",
            amount=appointment.total_price,
            currency="INR",
            status=PaymentStatus.PENDING,
            provider_name="mock",
        )
        self.assertEqual(pending.status, PaymentStatus.PAID)

        request_refund(
            payment=payment,
            amount=appointment.total_price,
            reason="full",
            idempotency_key="hard-refund-1",
        )
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.REFUNDED)

        revived = _upsert_payment_from_provider(
            appointment=appointment,
            order=row,
            provider_payment_id="pay_hard_2",
            provider_order_id=row.provider_order_id,
            signature="",
            amount=appointment.total_price,
            currency="INR",
            status=PaymentStatus.PAID,
            provider_name="mock",
        )
        self.assertEqual(revived.status, PaymentStatus.REFUNDED)

    def test_webhook_then_verify_and_verify_then_webhook(self):
        ctx, appointment = self._book(email="hard3@example.com", phone="+919900002003")
        order = create_payment_order_for_appointment(
            appointment=appointment, idempotency_key="hard-3"
        )
        amount_minor = order["amount"]
        payment_id = "pay_hard_3"
        payload = {
            "id": "evt_hard_3",
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": payment_id,
                        "order_id": order["provider_order_id"],
                        "amount": amount_minor,
                        "currency": "INR",
                        "status": "captured",
                    }
                }
            },
        }
        raw = json.dumps(payload).encode()
        signature = hmac.new(b"mock_webhook", raw, hashlib.sha256).hexdigest()
        wh = self.public.post(
            reverse("payments-webhooks:webhook-payments-razorpay"),
            data=raw,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=signature,
        )
        self.assertEqual(wh.status_code, 200)
        appointment.refresh_from_db()
        self.assertEqual(appointment.payment_status, AppointmentPaymentStatus.PAID)

        verify_sig = self._sign(order["provider_order_id"], payment_id)
        with patch.object(
            MockPaymentProvider,
            "fetch_payment",
            return_value=self._remote(
                payment_id=payment_id,
                order_id=order["provider_order_id"],
                amount_minor=amount_minor,
            ),
        ):
            state = verify_checkout_payment(
                appointment=appointment,
                razorpay_order_id=order["provider_order_id"],
                razorpay_payment_id=payment_id,
                razorpay_signature=verify_sig,
            )
        self.assertEqual(state["status"], AppointmentPaymentStatus.PAID)
        self.assertEqual(Payment.objects.filter(appointment=appointment).count(), 1)

        # Reverse order on a second booking
        ctx2, appointment2 = self._book(
            email="hard3b@example.com", phone="+919900002013", hhmm="12:00"
        )
        order2 = create_payment_order_for_appointment(
            appointment=appointment2, idempotency_key="hard-3b"
        )
        pid2 = "pay_hard_3b"
        vsig = self._sign(order2["provider_order_id"], pid2)
        with patch.object(
            MockPaymentProvider,
            "fetch_payment",
            return_value=self._remote(
                payment_id=pid2,
                order_id=order2["provider_order_id"],
                amount_minor=order2["amount"],
            ),
        ):
            verify_checkout_payment(
                appointment=appointment2,
                razorpay_order_id=order2["provider_order_id"],
                razorpay_payment_id=pid2,
                razorpay_signature=vsig,
            )
        payload2 = {
            "id": "evt_hard_3b",
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": pid2,
                        "order_id": order2["provider_order_id"],
                        "amount": order2["amount"],
                        "currency": "INR",
                        "status": "captured",
                    }
                }
            },
        }
        raw2 = json.dumps(payload2).encode()
        sig2 = hmac.new(b"mock_webhook", raw2, hashlib.sha256).hexdigest()
        wh2 = self.public.post(
            reverse("payments-webhooks:webhook-payments-razorpay"),
            data=raw2,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=sig2,
        )
        self.assertEqual(wh2.status_code, 200)
        self.assertEqual(Payment.objects.filter(appointment=appointment2).count(), 1)
        appointment2.refresh_from_db()
        self.assertEqual(appointment2.payment_status, AppointmentPaymentStatus.PAID)

    def test_failed_payment_is_retryable(self):
        ctx, appointment = self._book(email="hard4@example.com", phone="+919900002004")
        first = create_payment_order_for_appointment(
            appointment=appointment, idempotency_key="hard-4a"
        )
        row = PaymentOrder.objects.get(public_reference=first["payment_order_id"])
        row.status = PaymentOrderStatus.FAILED
        row.save(update_fields=["status", "updated_at"])
        second = create_payment_order_for_appointment(
            appointment=appointment, idempotency_key="hard-4b"
        )
        self.assertNotEqual(first["payment_order_id"], second["payment_order_id"])
        self.assertEqual(PaymentOrder.objects.filter(appointment=appointment).count(), 2)

    def test_cross_tenant_refund_404(self):
        ctx_a, appointment = self._book(email="hard5a@example.com", phone="+919900002005")
        order = create_payment_order_for_appointment(
            appointment=appointment, idempotency_key="hard-5"
        )
        payment = Payment.objects.create(
            organization_id=appointment.organization_id,
            business_id=appointment.business_id,
            location_id=appointment.location_id,
            appointment=appointment,
            customer_id=appointment.customer_id,
            payment_order=PaymentOrder.objects.get(public_reference=order["payment_order_id"]),
            provider="mock",
            status=PaymentStatus.PAID,
            amount=appointment.total_price,
            currency="INR",
            amount_paid=appointment.total_price,
            provider_payment_id="pay_hard_5",
        )
        ctx_b = self._seed_bookable_monday(
            owner_email="hard5b@example.com",
            org_name="Hard Org B",
            phone="+919900002015",
        )
        self._auth(ctx_b["token"])
        foreign = self.client.post(
            reverse(
                "payments-owner:owner-payment-refund",
                kwargs={
                    "business_id": ctx_b["business"]["id"],
                    "payment_id": payment.id,
                },
            ),
            {"amount": "10.00", "reason": "x", "idempotency_key": "x-tenant"},
            format="json",
        )
        self.assertEqual(foreign.status_code, status.HTTP_404_NOT_FOUND)

        # Same business id from org A but logged in as B still 404 (tenant from membership)
        wrong_biz = self.client.post(
            reverse(
                "payments-owner:owner-payment-refund",
                kwargs={
                    "business_id": ctx_a["business"]["id"],
                    "payment_id": payment.id,
                },
            ),
            {"amount": "10.00", "reason": "x", "idempotency_key": "x-tenant-2"},
            format="json",
        )
        # Business A is not in org B membership context → 404 from tenant resolution or filter
        self.assertIn(wrong_biz.status_code, {status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN})

    def test_duplicate_refund_idempotency(self):
        ctx, appointment = self._book(email="hard6@example.com", phone="+919900002006")
        payment = Payment.objects.create(
            organization_id=appointment.organization_id,
            business_id=appointment.business_id,
            location_id=appointment.location_id,
            appointment=appointment,
            customer_id=appointment.customer_id,
            provider="mock",
            status=PaymentStatus.PAID,
            amount=Decimal("100.00"),
            currency="INR",
            amount_paid=Decimal("100.00"),
            provider_payment_id="pay_hard_6",
        )
        first = request_refund(
            payment=payment,
            amount=Decimal("40.00"),
            reason="partial",
            idempotency_key="dup-refund",
        )
        second = request_refund(
            payment=payment,
            amount=Decimal("40.00"),
            reason="partial",
            idempotency_key="dup-refund",
        )
        self.assertEqual(first.id, second.id)
        payment.refresh_from_db()
        self.assertEqual(payment.amount_refunded, Decimal("40.00"))
        with self.assertRaises(RefundNotAllowed):
            request_refund(
                payment=payment,
                amount=Decimal("100.00"),
                reason="over",
                idempotency_key="over-refund",
            )
        sync_appointment_payment_status(appointment=appointment)
        appointment.refresh_from_db()
        self.assertEqual(appointment.payment_status, AppointmentPaymentStatus.PARTIALLY_PAID)
