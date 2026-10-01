"""Meta WhatsApp Cloud API provider (templates only)."""

from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from django.conf import settings

from booking.whatsapp import (
    WhatsAppProviderError,
    WhatsAppSendResult,
    mask_phone,
    normalize_whatsapp_recipient,
)

logger = logging.getLogger(__name__)

DEFAULT_GRAPH_HOST = "https://graph.facebook.com"


class MetaWhatsAppProvider:
    """Send approved WhatsApp template messages via Meta Cloud API."""

    timeout_seconds = 15

    def send(
        self,
        *,
        to: str,
        notification_type: str,
        snapshot: dict[str, Any],
        notification_id: UUID,
    ) -> WhatsAppSendResult:
        phone_number_id = getattr(settings, "META_WHATSAPP_PHONE_NUMBER_ID", "") or ""
        access_token = getattr(settings, "META_WHATSAPP_ACCESS_TOKEN", "") or ""
        api_version = getattr(settings, "META_WHATSAPP_API_VERSION", "") or ""
        if not phone_number_id or not access_token or not api_version:
            raise WhatsAppProviderError(
                "Meta WhatsApp is not configured (missing credentials).",
                permanent=True,
            )

        recipient = normalize_whatsapp_recipient(to)
        template_name, language, components = self._build_template(
            notification_type=notification_type,
            snapshot=snapshot or {},
        )
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
                "components": components,
            },
        }
        url = f"{DEFAULT_GRAPH_HOST}/{api_version}/{phone_number_id}/messages"
        return self._post_json(
            url=url,
            access_token=access_token,
            payload=payload,
            notification_id=notification_id,
            recipient=recipient,
            template_name=template_name,
        )

    def _build_template(
        self,
        *,
        notification_type: str,
        snapshot: dict[str, Any],
    ) -> tuple[str, str, list[dict[str, Any]]]:
        language = getattr(settings, "WHATSAPP_TEMPLATE_LANGUAGE", "en") or "en"
        if notification_type == "BOOKING_CONFIRMATION":
            name = getattr(settings, "WHATSAPP_BOOKING_CONFIRMATION_TEMPLATE", "") or ""
            if not name:
                raise WhatsAppProviderError(
                    "WHATSAPP_BOOKING_CONFIRMATION_TEMPLATE is not configured.",
                    permanent=True,
                )
            fields = _split_fields(
                getattr(
                    settings,
                    "WHATSAPP_CONFIRMATION_BODY_FIELDS",
                    "business_name,service_name,staff_name,date_label,time_label,public_reference",
                )
            )
            components = [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": _snapshot_field(snapshot, field)}
                        for field in fields
                    ],
                }
            ]
            button = _url_button_component(
                snapshot=snapshot,
                index=getattr(settings, "WHATSAPP_CONFIRMATION_URL_BUTTON_INDEX", "") or "",
                url_field="manage_url",
            )
            if button:
                components.append(button)
            return name, language, components

        if notification_type == "BOOKING_CANCELLATION":
            name = getattr(settings, "WHATSAPP_BOOKING_CANCELLATION_TEMPLATE", "") or ""
            if not name:
                raise WhatsAppProviderError(
                    "WHATSAPP_BOOKING_CANCELLATION_TEMPLATE is not configured.",
                    permanent=True,
                )
            fields = _split_fields(
                getattr(
                    settings,
                    "WHATSAPP_CANCELLATION_BODY_FIELDS",
                    "business_name,service_name,date_label,time_label,public_reference",
                )
            )
            components = [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": _snapshot_field(snapshot, field)}
                        for field in fields
                    ],
                }
            ]
            button = _url_button_component(
                snapshot=snapshot,
                index=getattr(settings, "WHATSAPP_CANCELLATION_URL_BUTTON_INDEX", "") or "",
                url_field="book_again_url",
            )
            if button:
                components.append(button)
            return name, language, components

        if notification_type in ("REMINDER_24H", "REMINDER_1H"):
            reminder_language = (
                getattr(settings, "WHATSAPP_REMINDER_TEMPLATE_LANGUAGE", "") or ""
            ).strip() or language
            if notification_type == "REMINDER_24H":
                name = getattr(settings, "WHATSAPP_REMINDER_24H_TEMPLATE", "") or ""
                if not name:
                    raise WhatsAppProviderError(
                        "WHATSAPP_REMINDER_24H_TEMPLATE is not configured.",
                        permanent=True,
                    )
                fields = _split_fields(
                    getattr(
                        settings,
                        "WHATSAPP_REMINDER_24H_BODY_FIELDS",
                        "business_name,service_name,staff_name,date_label,time_label,public_reference",
                    )
                )
                button_index = getattr(settings, "WHATSAPP_REMINDER_24H_URL_BUTTON_INDEX", "") or ""
            else:
                name = getattr(settings, "WHATSAPP_REMINDER_1H_TEMPLATE", "") or ""
                if not name:
                    raise WhatsAppProviderError(
                        "WHATSAPP_REMINDER_1H_TEMPLATE is not configured.",
                        permanent=True,
                    )
                fields = _split_fields(
                    getattr(
                        settings,
                        "WHATSAPP_REMINDER_1H_BODY_FIELDS",
                        "business_name,service_name,staff_name,time_label,public_reference",
                    )
                )
                button_index = getattr(settings, "WHATSAPP_REMINDER_1H_URL_BUTTON_INDEX", "") or ""
            components = [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": _snapshot_field(snapshot, field)}
                        for field in fields
                    ],
                }
            ]
            button = _url_button_component(
                snapshot=snapshot,
                index=button_index,
                url_field="manage_url",
            )
            if button:
                components.append(button)
            return name, reminder_language, components

        raise WhatsAppProviderError(
            f"Unsupported notification_type for Meta: {notification_type}",
            permanent=True,
        )

    def _post_json(
        self,
        *,
        url: str,
        access_token: str,
        payload: dict[str, Any],
        notification_id: UUID,
        recipient: str,
        template_name: str,
    ) -> WhatsAppSendResult:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        logger.info(
            "whatsapp.meta_send notification_id=%s recipient=%s template=%s",
            notification_id,
            mask_phone(f"+{recipient}"),
            template_name,
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
                context=ssl.create_default_context(),
            ) as response:
                raw = response.read().decode("utf-8")
                status = getattr(response, "status", 200)
        except urllib.error.HTTPError as exc:
            err_body = ""
            try:
                err_body = exc.read().decode("utf-8")
            except Exception:
                err_body = ""
            raise _map_meta_http_error(exc.code, err_body) from exc
        except urllib.error.URLError as exc:
            raise WhatsAppProviderError(
                f"Meta WhatsApp connection failure: {exc.reason}",
                permanent=False,
            ) from exc
        except TimeoutError as exc:
            raise WhatsAppProviderError(
                "Meta WhatsApp request timed out.",
                permanent=False,
            ) from exc

        if status >= 500:
            raise WhatsAppProviderError(
                f"Meta WhatsApp server error ({status}).",
                permanent=False,
                status_code=status,
            )
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise WhatsAppProviderError(
                "Malformed Meta WhatsApp response.",
                permanent=False,
                status_code=status,
            ) from exc

        message_id = _extract_wamid(data)
        if not message_id:
            raise WhatsAppProviderError(
                "Meta WhatsApp response missing message id.",
                permanent=False,
                status_code=status,
            )
        return WhatsAppSendResult(provider_message_id=message_id[:128])


def _split_fields(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def _snapshot_field(snapshot: dict[str, Any], field: str) -> str:
    if field == "date_label" and not snapshot.get("date_label"):
        starts = snapshot.get("starts_at") or ""
        return starts[:10] if starts else ""
    if field == "time_label" and not snapshot.get("time_label"):
        starts = snapshot.get("starts_at") or ""
        ends = snapshot.get("ends_at") or ""
        if "T" in starts:
            start_t = starts.split("T", 1)[1][:5]
            end_t = ends.split("T", 1)[1][:5] if "T" in ends else ""
            return f"{start_t} – {end_t}" if end_t else start_t
        return ""
    value = snapshot.get(field)
    if value is None:
        return ""
    text = str(value).strip()
    # Meta rejects empty template parameters.
    return text or "-"


def _url_button_component(
    *,
    snapshot: dict[str, Any],
    index: str,
    url_field: str,
) -> dict[str, Any] | None:
    if index == "":
        return None
    url = (snapshot.get(url_field) or "").strip()
    if not url:
        return None
    # Meta dynamic URL buttons expect the suffix after the fixed template prefix.
    # Prefer the final path segment (manage token or location slug).
    path = urlparse(url).path.rstrip("/")
    suffix = path.rsplit("/", 1)[-1] if path else url
    return {
        "type": "button",
        "sub_type": "url",
        "index": str(index),
        "parameters": [{"type": "text", "text": suffix}],
    }


def _extract_wamid(data: dict[str, Any]) -> str:
    messages = data.get("messages")
    if isinstance(messages, list) and messages:
        first = messages[0]
        if isinstance(first, dict):
            mid = first.get("id")
            if isinstance(mid, str) and mid:
                return mid
    return ""


def _map_meta_http_error(status_code: int, body: str) -> WhatsAppProviderError:
    code = None
    message = f"Meta WhatsApp error ({status_code})."
    try:
        payload = json.loads(body) if body else {}
        err = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(err, dict):
            code = err.get("code")
            msg = err.get("message")
            if isinstance(msg, str) and msg:
                message = msg[:500]
    except json.JSONDecodeError:
        pass

    permanent = status_code in {400, 401, 403, 404} or code in {
        100,
        131008,
        131009,
        132000,
        132001,
        132005,
        132007,
        132012,
        132015,
        132016,
    }
    if status_code == 429 or status_code >= 500:
        permanent = False
    return WhatsAppProviderError(
        message,
        permanent=permanent,
        status_code=status_code,
    )
