"""Provider-agnostic payment boundary. Views/services must not import Razorpay SDK."""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import uuid4

from django.conf import settings

from payments.exceptions import PaymentProviderError, PaymentSignatureInvalid

logger = logging.getLogger("payments.provider")


@dataclass(frozen=True)
class ProviderOrderResult:
    provider_order_id: str
    amount_minor: int
    currency: str
    status: str = "created"


@dataclass(frozen=True)
class ProviderPaymentResult:
    provider_payment_id: str
    provider_order_id: str
    amount_minor: int
    currency: str
    status: str
    method: str = ""


@dataclass(frozen=True)
class ProviderRefundResult:
    provider_refund_id: str
    amount_minor: int
    currency: str
    status: str


class PaymentProvider(Protocol):
    name: str

    def create_order(
        self,
        *,
        amount_minor: int,
        currency: str,
        receipt: str,
        notes: dict | None = None,
    ) -> ProviderOrderResult: ...

    def fetch_payment(self, *, provider_payment_id: str) -> ProviderPaymentResult: ...

    def fetch_order(self, *, provider_order_id: str) -> ProviderOrderResult: ...

    def verify_payment_signature(
        self,
        *,
        provider_order_id: str,
        provider_payment_id: str,
        signature: str,
    ) -> bool: ...

    def verify_webhook_signature(self, *, raw_body: bytes, signature: str) -> bool: ...

    def refund_payment(
        self,
        *,
        provider_payment_id: str,
        amount_minor: int,
        notes: dict | None = None,
    ) -> ProviderRefundResult: ...


def to_minor_units(amount: Decimal, currency: str = "INR") -> int:
    """Convert major units to provider minor units (paise for INR)."""
    currency = (currency or "INR").upper()
    if currency == "INR":
        return int((amount * 100).quantize(Decimal("1")))
    return int((amount * 100).quantize(Decimal("1")))


def from_minor_units(amount_minor: int, currency: str = "INR") -> Decimal:
    currency = (currency or "INR").upper()
    if currency == "INR":
        return (Decimal(amount_minor) / Decimal("100")).quantize(Decimal("0.01"))
    return (Decimal(amount_minor) / Decimal("100")).quantize(Decimal("0.01"))


class MockPaymentProvider:
    name = "mock"

    def create_order(
        self,
        *,
        amount_minor: int,
        currency: str,
        receipt: str,
        notes: dict | None = None,
    ) -> ProviderOrderResult:
        return ProviderOrderResult(
            provider_order_id=f"order_mock_{uuid4().hex[:16]}",
            amount_minor=amount_minor,
            currency=currency.upper(),
            status="created",
        )

    def fetch_payment(self, *, provider_payment_id: str) -> ProviderPaymentResult:
        return ProviderPaymentResult(
            provider_payment_id=provider_payment_id,
            provider_order_id=f"order_mock_{provider_payment_id[-8:]}",
            amount_minor=10000,
            currency="INR",
            status="captured",
        )

    def fetch_order(self, *, provider_order_id: str) -> ProviderOrderResult:
        return ProviderOrderResult(
            provider_order_id=provider_order_id,
            amount_minor=10000,
            currency="INR",
            status="paid",
        )

    def verify_payment_signature(
        self,
        *,
        provider_order_id: str,
        provider_payment_id: str,
        signature: str,
    ) -> bool:
        expected = hashlib.sha256(
            f"{provider_order_id}|{provider_payment_id}|mock".encode()
        ).hexdigest()
        return hmac.compare_digest(expected, (signature or "").strip())

    def verify_webhook_signature(self, *, raw_body: bytes, signature: str) -> bool:
        secret = (getattr(settings, "RAZORPAY_WEBHOOK_SECRET", "") or "mock_webhook").encode()
        digest = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(digest, (signature or "").strip())

    def refund_payment(
        self,
        *,
        provider_payment_id: str,
        amount_minor: int,
        notes: dict | None = None,
    ) -> ProviderRefundResult:
        return ProviderRefundResult(
            provider_refund_id=f"rfnd_mock_{uuid4().hex[:16]}",
            amount_minor=amount_minor,
            currency="INR",
            status="processed",
        )


class DeferredPaymentProvider:
    name = "deferred"

    def _block(self):
        raise PaymentProviderError(
            "Razorpay provider is deferred. Set RAZORPAY_PROVIDER=mock|razorpay.",
            code="PROVIDER_DEFERRED",
        )

    def create_order(self, **kwargs):
        self._block()

    def fetch_payment(self, **kwargs):
        self._block()

    def fetch_order(self, **kwargs):
        self._block()

    def verify_payment_signature(self, **kwargs):
        self._block()

    def verify_webhook_signature(self, **kwargs):
        self._block()

    def refund_payment(self, **kwargs):
        self._block()


class RazorpayPaymentProvider:
    name = "razorpay"

    def __init__(self):
        key_id = (getattr(settings, "RAZORPAY_KEY_ID", "") or "").strip()
        key_secret = (getattr(settings, "RAZORPAY_KEY_SECRET", "") or "").strip()
        if not key_id or not key_secret:
            raise PaymentProviderError(
                "Razorpay credentials are not configured.",
                code="PROVIDER_NOT_CONFIGURED",
            )
        try:
            import razorpay
        except ImportError as exc:
            raise PaymentProviderError(
                "razorpay package is not installed.",
                code="PROVIDER_NOT_INSTALLED",
            ) from exc
        self._client = razorpay.Client(auth=(key_id, key_secret))
        self._key_secret = key_secret
        self._webhook_secret = (getattr(settings, "RAZORPAY_WEBHOOK_SECRET", "") or "").strip()

    def create_order(
        self,
        *,
        amount_minor: int,
        currency: str,
        receipt: str,
        notes: dict | None = None,
    ) -> ProviderOrderResult:
        try:
            data = self._client.order.create(
                {
                    "amount": amount_minor,
                    "currency": currency.upper(),
                    "receipt": receipt[:40],
                    "notes": notes or {},
                    "payment_capture": 1,
                }
            )
        except Exception as exc:
            logger.exception("payments.razorpay_create_order_failed")
            raise PaymentProviderError("Failed to create payment order.") from exc
        return ProviderOrderResult(
            provider_order_id=str(data["id"]),
            amount_minor=int(data["amount"]),
            currency=str(data.get("currency") or currency).upper(),
            status=str(data.get("status") or "created"),
        )

    def fetch_payment(self, *, provider_payment_id: str) -> ProviderPaymentResult:
        try:
            data = self._client.payment.fetch(provider_payment_id)
        except Exception as exc:
            logger.exception("payments.razorpay_fetch_payment_failed")
            raise PaymentProviderError("Failed to fetch payment.") from exc
        return ProviderPaymentResult(
            provider_payment_id=str(data["id"]),
            provider_order_id=str(data.get("order_id") or ""),
            amount_minor=int(data.get("amount") or 0),
            currency=str(data.get("currency") or "INR").upper(),
            status=str(data.get("status") or ""),
            method=str(data.get("method") or ""),
        )

    def fetch_order(self, *, provider_order_id: str) -> ProviderOrderResult:
        try:
            data = self._client.order.fetch(provider_order_id)
        except Exception as exc:
            logger.exception("payments.razorpay_fetch_order_failed")
            raise PaymentProviderError("Failed to fetch order.") from exc
        return ProviderOrderResult(
            provider_order_id=str(data["id"]),
            amount_minor=int(data.get("amount") or 0),
            currency=str(data.get("currency") or "INR").upper(),
            status=str(data.get("status") or ""),
        )

    def verify_payment_signature(
        self,
        *,
        provider_order_id: str,
        provider_payment_id: str,
        signature: str,
    ) -> bool:
        payload = f"{provider_order_id}|{provider_payment_id}"
        expected = hmac.new(
            self._key_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, (signature or "").strip())

    def verify_webhook_signature(self, *, raw_body: bytes, signature: str) -> bool:
        if not self._webhook_secret:
            return False
        expected = hmac.new(
            self._webhook_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, (signature or "").strip())

    def refund_payment(
        self,
        *,
        provider_payment_id: str,
        amount_minor: int,
        notes: dict | None = None,
    ) -> ProviderRefundResult:
        try:
            data = self._client.payment.refund(
                provider_payment_id,
                {"amount": amount_minor, "notes": notes or {}},
            )
        except Exception as exc:
            logger.exception("payments.razorpay_refund_failed")
            raise PaymentProviderError("Failed to refund payment.") from exc
        return ProviderRefundResult(
            provider_refund_id=str(data["id"]),
            amount_minor=int(data.get("amount") or amount_minor),
            currency=str(data.get("currency") or "INR").upper(),
            status=str(data.get("status") or "processed"),
        )


def get_payment_provider() -> PaymentProvider:
    kind = (getattr(settings, "RAZORPAY_PROVIDER", "mock") or "mock").strip().lower()
    if kind == "mock":
        return MockPaymentProvider()
    if kind == "deferred":
        return DeferredPaymentProvider()
    if kind == "razorpay":
        return RazorpayPaymentProvider()
    raise PaymentProviderError(f"Unknown payment provider: {kind}", code="PROVIDER_UNKNOWN")


def get_public_key_id() -> str:
    kind = (getattr(settings, "RAZORPAY_PROVIDER", "mock") or "mock").strip().lower()
    if kind == "mock":
        return "rzp_test_mock"
    return (getattr(settings, "RAZORPAY_KEY_ID", "") or "").strip()


def require_valid_payment_signature(
    *,
    provider: PaymentProvider,
    provider_order_id: str,
    provider_payment_id: str,
    signature: str,
) -> None:
    ok = provider.verify_payment_signature(
        provider_order_id=provider_order_id,
        provider_payment_id=provider_payment_id,
        signature=signature,
    )
    if not ok:
        raise PaymentSignatureInvalid()
