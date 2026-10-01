"""HTTP views for payments: public checkout + owner refunds + Razorpay webhook."""

from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation

from django.http import JsonResponse
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from booking.public_services import get_appointment_by_public_reference
from core.mixins import TenantContextMixin
from core.permissions import HasOrganizationContext, IsOrganizationOwner
from payments.exceptions import (
    PaymentAlreadyPaid,
    PaymentAmountInvalid,
    PaymentError,
    PaymentNotEligible,
    PaymentSignatureInvalid,
    RefundNotAllowed,
)
from payments.models import Payment
from payments.services import (
    create_payment_order_for_appointment,
    process_razorpay_webhook,
    request_refund,
    serialize_public_payment_state,
    verify_checkout_payment,
)

logger = logging.getLogger("payments.views")


class PublicPaymentWriteThrottle(AnonRateThrottle):
    scope = "public_payment_write"


class PaymentAPIError(APIException):
    status_code = 400
    default_detail = "Payment request is invalid."
    default_code = "payment_error"

    def __init__(self, detail=None, *, code=None, status_code=None):
        if status_code is not None:
            self.status_code = status_code
        resolved = code or self.default_code
        self.error_code = resolved
        super().__init__(detail=detail, code=resolved)


def _raise_payment(exc: PaymentError, *, status_code: int = 400):
    raise PaymentAPIError(detail=exc.message, code=exc.code, status_code=status_code)


class PublicPaymentOrderCreateView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicPaymentWriteThrottle]

    def post(self, request, public_reference: str):
        appointment = get_appointment_by_public_reference(public_reference)
        key = request.data.get("idempotency_key") or request.headers.get("Idempotency-Key") or ""
        try:
            payload = create_payment_order_for_appointment(
                appointment=appointment,
                idempotency_key=str(key),
            )
        except PaymentAlreadyPaid as exc:
            _raise_payment(exc, status_code=409)
        except PaymentNotEligible as exc:
            _raise_payment(exc, status_code=400)
        except PaymentError as exc:
            _raise_payment(exc, status_code=400)
        return Response(payload, status=status.HTTP_201_CREATED)


class PublicPaymentVerifyView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicPaymentWriteThrottle]

    def post(self, request, public_reference: str):
        appointment = get_appointment_by_public_reference(public_reference)
        try:
            payload = verify_checkout_payment(
                appointment=appointment,
                razorpay_order_id=str(request.data.get("razorpay_order_id") or ""),
                razorpay_payment_id=str(request.data.get("razorpay_payment_id") or ""),
                razorpay_signature=str(request.data.get("razorpay_signature") or ""),
            )
        except PaymentSignatureInvalid as exc:
            _raise_payment(exc, status_code=400)
        except PaymentAlreadyPaid:
            return Response(
                serialize_public_payment_state(appointment=appointment),
                status=status.HTTP_200_OK,
            )
        except (PaymentNotEligible, PaymentAmountInvalid, PaymentError) as exc:
            _raise_payment(exc, status_code=400)
        return Response(payload, status=status.HTTP_200_OK)


class PublicPaymentStatusView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicPaymentWriteThrottle]

    def get(self, request, public_reference: str):
        appointment = get_appointment_by_public_reference(public_reference)
        payment = (
            Payment.objects.filter(appointment_id=appointment.id).order_by("-created_at").first()
        )
        return Response(serialize_public_payment_state(appointment=appointment, payment=payment))


class RazorpayWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        raw_body = request.body or b""
        signature = request.META.get("HTTP_X_RAZORPAY_SIGNATURE", "")
        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JsonResponse({"error": "Bad request"}, status=400)
        try:
            result = process_razorpay_webhook(
                raw_body=raw_body,
                signature=signature,
                payload=payload if isinstance(payload, dict) else {},
            )
        except PaymentSignatureInvalid:
            logger.warning("payments.webhook_invalid_signature")
            return JsonResponse({"error": "Invalid signature"}, status=403)
        except Exception:
            logger.exception("payments.webhook_failed")
            return JsonResponse({"ok": True, "processed": False})
        return JsonResponse({"ok": True, **result})


class OwnerPaymentRefundView(TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext, IsOrganizationOwner]

    def post(self, request, business_id, payment_id):
        payment = (
            Payment.objects.filter(
                pk=payment_id,
                organization=request.organization,
                business_id=business_id,
            )
            .select_related("appointment")
            .first()
        )
        if payment is None:
            raise PaymentAPIError(detail="Payment not found.", code="NOT_FOUND", status_code=404)
        try:
            amount = Decimal(str(request.data.get("amount")))
        except (InvalidOperation, TypeError, ValueError):
            raise PaymentAPIError(
                detail="Invalid refund amount.",
                code="INVALID_AMOUNT",
                status_code=400,
            ) from None
        try:
            refund = request_refund(
                payment=payment,
                amount=amount,
                reason=str(request.data.get("reason") or ""),
                idempotency_key=str(
                    request.data.get("idempotency_key")
                    or request.headers.get("Idempotency-Key")
                    or ""
                ),
                actor=request.user,
            )
        except (PaymentError, RefundNotAllowed) as exc:
            _raise_payment(exc, status_code=400)
        return Response(
            {
                "id": str(refund.id),
                "status": refund.status,
                "amount": str(refund.amount),
                "currency": refund.currency,
                "processed_at": refund.processed_at.isoformat() if refund.processed_at else None,
            },
            status=status.HTTP_201_CREATED,
        )
