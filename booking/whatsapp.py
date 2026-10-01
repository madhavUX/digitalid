"""WhatsApp provider abstraction — booking code never imports Meta SDK details."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WhatsAppSendResult:
    provider_message_id: str


class WhatsAppProviderError(Exception):
    """Raised for any provider-side failure (timeout, 4xx, 5xx, malformed)."""

    def __init__(
        self,
        message: str,
        *,
        permanent: bool = False,
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.permanent = permanent
        self.status_code = status_code


class WhatsAppProvider(Protocol):
    def send(
        self,
        *,
        to: str,
        notification_type: str,
        snapshot: dict[str, Any],
        notification_id: UUID,
    ) -> WhatsAppSendResult: ...


class LoggingWhatsAppProvider:
    """Dev/test provider: logs sanitized intent, never calls external APIs."""

    def send(
        self,
        *,
        to: str,
        notification_type: str,
        snapshot: dict[str, Any],
        notification_id: UUID,
    ) -> WhatsAppSendResult:
        message_id = f"mock-wa-{notification_id}"
        body = (snapshot or {}).get("text") or ""
        logger.info(
            "whatsapp.mock_send notification_id=%s type=%s recipient=%s "
            "body_chars=%s provider_message_id=%s",
            notification_id,
            notification_type,
            mask_phone(to),
            len(body),
            message_id,
        )
        return WhatsAppSendResult(provider_message_id=message_id)

    # Back-compat for older call sites/tests
    def send_text(self, *, to: str, body: str, notification_id: UUID) -> WhatsAppSendResult:
        return self.send(
            to=to,
            notification_type="TEXT",
            snapshot={"text": body},
            notification_id=notification_id,
        )


class DisabledWhatsAppProvider:
    def send(
        self,
        *,
        to: str,
        notification_type: str,
        snapshot: dict[str, Any],
        notification_id: UUID,
    ) -> WhatsAppSendResult:
        raise WhatsAppProviderError("WhatsApp provider is disabled.", permanent=True)


def mask_phone(phone: str) -> str:
    cleaned = (phone or "").strip()
    if len(cleaned) <= 4:
        return "****"
    return f"{cleaned[:3]}******{cleaned[-4:]}"


def normalize_whatsapp_recipient(phone: str) -> str:
    """Return digits-only international number for Meta (no leading +)."""
    cleaned = (phone or "").strip().replace(" ", "").replace("-", "")
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]
    if not cleaned.isdigit() or len(cleaned) < 8:
        raise WhatsAppProviderError(
            "Invalid WhatsApp recipient phone number.",
            permanent=True,
        )
    return cleaned


def get_whatsapp_provider() -> WhatsAppProvider:
    from django.conf import settings

    if not getattr(settings, "WHATSAPP_ENABLED", False):
        return DisabledWhatsAppProvider()
    name = (getattr(settings, "WHATSAPP_PROVIDER", "mock") or "mock").lower()
    if name == "mock":
        return LoggingWhatsAppProvider()
    if name == "meta":
        from booking.meta_whatsapp import MetaWhatsAppProvider

        return MetaWhatsAppProvider()
    raise WhatsAppProviderError(
        f"Unknown WHATSAPP_PROVIDER={name!r}. Use 'mock' or 'meta'.",
        permanent=True,
    )
