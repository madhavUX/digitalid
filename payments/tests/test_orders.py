"""Phase 6 payment foundation tests (orders, verify, webhooks, refunds)."""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from booking.models import Appointment, AppointmentStatus
from booking.tests.test_public_booking_api import PublicBookingAPITestCase
from businesses.models import Business, BusinessPaymentMode
from payments.models import (
    AppointmentPaymentStatus,
    Payment,
    PaymentOrder,
    PaymentStatus,
    PaymentWebhookEvent,
    RefundStatus,
)
from payments.providers import MockPaymentProvider, to_minor_units
from payments.services import create_payment_order_for_appointment, request_refund


@override_settings(RAZORPAY_PROVIDER="mock", RAZORPAY_WEBHOOK_SECRET="mock_webhook")
class PaymentFoundationTests(PublicBookingAPITestCase):
    def _enable_full_payment(self, ctx):
        business = Business.objects.get(pk=ctx["business"]["id"])
        business.payment_mode = BusinessPaymentMode.FULL
        business.save(update_fields=["payment_mode", "updated_at"])
        return business

    def _book_paid_required(self, *, email, phone, hhmm="10:00"):
        ctx = self._seed_bookable_monday(
            owner_email=email,
            org_name=f"Pay {email}",
            phone=phone,
            buffer_before_minutes=0,
            buffer_after_minutes=0,
        )
        self._enable_full_payment(ctx)
        payload = self._book_payload(ctx, hhmm, staff_id=ctx["staff"]["id"], phone=phone[-10:])
        created = self._public_create(payload)
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        self.assertTrue(created.data["payment_required"])
        self.assertEqual(created.data["payment_status"], AppointmentPaymentStatus.PENDING)
        appointment = Appointment.objects.get(public_reference=created.data["public_reference"])
        return ctx, appointment, created.data

    def test_order_create_verify_and_idempotency(self):
        ctx, appointment, body = self._book_paid_required(
            email="pay1@example.com", phone="+919900001001"
        )
        order_path = reverse(
            "public-booking-payment-order",
            kwargs={"public_reference": appointment.public_reference},
        )
        first = self.public.post(order_path, {"idempotency_key": "pay-key-1"}, format="json")
        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.data)
        self.assertEqual(first.data["provider"], "mock")
        self.assertTrue(first.data["provider_order_id"])
        self.assertEqual(first.data["amount"], to_minor_units(appointment.total_price, "INR"))
        self.assertEqual(first.data["key_id"], "rzp_test_mock")

        second = self.public.post(order_path, {"idempotency_key": "pay-key-1"}, format="json")
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.data["payment_order_id"], first.data["payment_order_id"])
        self.assertEqual(PaymentOrder.objects.filter(appointment=appointment).count(), 1)

        order = PaymentOrder.objects.get(public_reference=first.data["payment_order_id"])
        payment_id = "pay_mock_ok1"
        signature = hashlib.sha256(
            f"{order.provider_order_id}|{payment_id}|mock".encode()
        ).hexdigest()

        with patch.object(
            MockPaymentProvider,
            "fetch_payment",
            return_value=type(
                "R",
                (),
                {
                    "provider_payment_id": payment_id,
                    "provider_order_id": order.provider_order_id,
                    "amount_minor": first.data["amount"],
                    "currency": "INR",
                    "status": "captured",
                    "method": "upi",
                },
            )(),
        ):
            verify = self.public.post(
                reverse(
                    "public-booking-payment-verify",
                    kwargs={"public_reference": appointment.public_reference},
                ),
                {
                    "razorpay_order_id": order.provider_order_id,
                    "razorpay_payment_id": payment_id,
                    "razorpay_signature": signature,
                },
                format="json",
            )
        self.assertEqual(verify.status_code, status.HTTP_200_OK, verify.data)
        self.assertEqual(verify.data["status"], AppointmentPaymentStatus.PAID)
        self.assertIsNotNone(verify.data["payment_reference"])
        appointment.refresh_from_db()
        self.assertEqual(appointment.payment_status, AppointmentPaymentStatus.PAID)
        self.assertEqual(appointment.source, "ONLINE")
        self.assertIsNone(appointment.acquisition_source)

        # Repeated verify is idempotent
        with patch.object(
            MockPaymentProvider,
            "fetch_payment",
            return_value=type(
                "R",
                (),
                {
                    "provider_payment_id": payment_id,
                    "provider_order_id": order.provider_order_id,
                    "amount_minor": first.data["amount"],
                    "currency": "INR",
                    "status": "captured",
                    "method": "upi",
                },
            )(),
        ):
            again = self.public.post(
                reverse(
                    "public-booking-payment-verify",
                    kwargs={"public_reference": appointment.public_reference},
                ),
                {
                    "razorpay_order_id": order.provider_order_id,
                    "razorpay_payment_id": payment_id,
                    "razorpay_signature": signature,
                },
                format="json",
            )
        self.assertEqual(again.status_code, status.HTTP_200_OK)
        self.assertEqual(Payment.objects.filter(appointment=appointment).count(), 1)

    def test_invalid_signature_and_cancelled_rejected(self):
        ctx, appointment, _ = self._book_paid_required(
            email="pay2@example.com", phone="+919900001002"
        )
        order = create_payment_order_for_appointment(
            appointment=appointment, idempotency_key="pay-key-2"
        )
        bad = self.public.post(
            reverse(
                "public-booking-payment-verify",
                kwargs={"public_reference": appointment.public_reference},
            ),
            {
                "razorpay_order_id": order["provider_order_id"],
                "razorpay_payment_id": "pay_x",
                "razorpay_signature": "bad",
            },
            format="json",
        )
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)

        appointment.status = AppointmentStatus.CANCELLED
        appointment.save(update_fields=["status", "updated_at"])
        cancelled = self.public.post(
            reverse(
                "public-booking-payment-order",
                kwargs={"public_reference": appointment.public_reference},
            ),
            {"idempotency_key": "pay-key-2b"},
            format="json",
        )
        self.assertEqual(cancelled.status_code, status.HTTP_400_BAD_REQUEST)

    def test_webhook_captured_and_duplicate(self):
        ctx, appointment, _ = self._book_paid_required(
            email="pay3@example.com", phone="+919900001003"
        )
        order = create_payment_order_for_appointment(
            appointment=appointment, idempotency_key="pay-key-3"
        )
        amount_minor = order["amount"]
        payload = {
            "id": "evt_test_1",
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_wh_1",
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
        url = reverse("payments-webhooks:webhook-payments-razorpay")
        first = self.public.post(
            url, data=raw, content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE=signature
        )
        self.assertEqual(first.status_code, 200)
        appointment.refresh_from_db()
        self.assertEqual(appointment.payment_status, AppointmentPaymentStatus.PAID)

        second = self.public.post(
            url, data=raw, content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE=signature
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(PaymentWebhookEvent.objects.count(), 1)

        bad_sig = self.public.post(
            url, data=raw, content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE="nope"
        )
        self.assertEqual(bad_sig.status_code, 403)

    def test_refund_and_permissions(self):
        ctx, appointment, _ = self._book_paid_required(
            email="pay4@example.com", phone="+919900001004"
        )
        order = create_payment_order_for_appointment(
            appointment=appointment, idempotency_key="pay-key-4"
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
            provider_order_id=order["provider_order_id"],
            provider_payment_id="pay_ref_1",
        )
        appointment.payment_status = AppointmentPaymentStatus.PAID
        appointment.save(update_fields=["payment_status", "updated_at"])

        refund = request_refund(
            payment=payment,
            amount=appointment.total_price,
            reason="customer request",
            idempotency_key="refund-1",
        )
        self.assertEqual(refund.status, RefundStatus.PROCESSED)
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.REFUNDED)
        appointment.refresh_from_db()
        self.assertEqual(appointment.payment_status, AppointmentPaymentStatus.REFUNDED)

        # Over-refund rejected
        payment2 = Payment.objects.create(
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
            provider_payment_id="pay_ref_2",
        )
        from payments.exceptions import RefundNotAllowed

        with self.assertRaises(RefundNotAllowed):
            request_refund(
                payment=payment2,
                amount=Decimal("150.00"),
                reason="too much",
                idempotency_key="refund-2",
            )

        path = reverse(
            "payments-owner:owner-payment-refund",
            kwargs={"business_id": ctx["business"]["id"], "payment_id": payment2.id},
        )
        self._auth(ctx["token"])
        ok = self.client.post(
            path,
            {"amount": "40.00", "reason": "partial", "idempotency_key": "refund-api-1"},
            format="json",
        )
        self.assertEqual(ok.status_code, status.HTTP_201_CREATED, ok.data)
        payment2.refresh_from_db()
        self.assertEqual(payment2.status, PaymentStatus.PARTIALLY_REFUNDED)

    def test_none_mode_skips_payment(self):
        ctx = self._seed_bookable_monday(
            owner_email="pay5@example.com",
            org_name="Pay None",
            phone="+919900001005",
            buffer_before_minutes=0,
            buffer_after_minutes=0,
        )
        payload = self._book_payload(ctx, "10:00", staff_id=ctx["staff"]["id"], phone="9900001005")
        created = self._public_create(payload)
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertFalse(created.data["payment_required"])
        self.assertEqual(created.data["payment_status"], AppointmentPaymentStatus.NOT_REQUIRED)
        blocked = self.public.post(
            reverse(
                "public-booking-payment-order",
                kwargs={"public_reference": created.data["public_reference"]},
            ),
            {"idempotency_key": "noop"},
            format="json",
        )
        self.assertEqual(blocked.status_code, status.HTTP_400_BAD_REQUEST)
