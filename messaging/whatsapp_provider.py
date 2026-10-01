"""WhatsApp Business Platform provider boundary (mock | meta | deferred).

This is the business-owned connection. Booking transactional notifications
continue to use ``booking.whatsapp`` and platform env credentials.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

import requests
from django.conf import settings

logger = logging.getLogger("messaging.whatsapp")

GRAPH_BASE = "https://graph.facebook.com"


class WhatsAppBusinessProviderError(Exception):
    def __init__(self, message: str, *, code: str = "PROVIDER_ERROR", transient: bool = False):
        super().__init__(message)
        self.code = code
        self.transient = transient


@dataclass(frozen=True)
class WhatsAppAccountSnapshot:
    phone_number_id: str
    business_account_id: str
    display_phone_number: str
    verified_name: str


@dataclass(frozen=True)
class WhatsAppSendResult:
    provider_message_id: str


@dataclass(frozen=True)
class WhatsAppTemplateStatusSnapshot:
    name: str
    language: str
    status: str
    provider_template_id: str


@dataclass(frozen=True)
class WhatsAppRemoteTemplate:
    name: str
    language: str
    status: str
    provider_template_id: str
    category: str = ""
    body: str = ""


class WhatsAppBusinessProvider(Protocol):
    name: str

    def configure(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        business_account_id: str,
    ) -> WhatsAppAccountSnapshot: ...

    def get_business_status(
        self,
        *,
        access_token: str,
        phone_number_id: str,
    ) -> WhatsAppAccountSnapshot: ...

    def send_message(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        to: str,
        body: str,
    ) -> WhatsAppSendResult: ...

    def send_template_message(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        to: str,
        template_name: str,
        language: str,
        variables: list[str],
    ) -> WhatsAppSendResult: ...

    def fetch_template_status(
        self,
        *,
        access_token: str,
        business_account_id: str,
        name: str,
        language: str,
    ) -> WhatsAppTemplateStatusSnapshot: ...

    def list_templates(
        self,
        *,
        access_token: str,
        business_account_id: str,
    ) -> list[WhatsAppRemoteTemplate]: ...

    def get_template(
        self,
        *,
        access_token: str,
        business_account_id: str,
        name: str,
        language: str,
    ) -> WhatsAppRemoteTemplate: ...

    def submit_template(
        self,
        *,
        access_token: str,
        business_account_id: str,
        name: str,
        language: str,
        category: str,
        body: str,
    ) -> WhatsAppRemoteTemplate: ...

    def disconnect(self, *, access_token: str) -> None: ...


class MockWhatsAppBusinessProvider:
    """In-memory provider for tests and local development. No network."""

    name = "mock"

    def __init__(self) -> None:
        self.configured: list[str] = []
        self.sent: list[tuple[str, str]] = []
        self.fail_send = False
        self.fail_transient = False
        self.fail_configure = False
        self.remote_templates: list[WhatsAppRemoteTemplate] = []

    def configure(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        business_account_id: str,
    ) -> WhatsAppAccountSnapshot:
        token = (access_token or "").strip()
        phone_id = (phone_number_id or "").strip()
        account_id = (business_account_id or "").strip()
        if self.fail_configure or token in {"", "invalid"} or not phone_id or not account_id:
            raise WhatsAppBusinessProviderError(
                "WhatsApp credentials were rejected.",
                code="INVALID_CREDENTIALS",
            )
        self.configured.append(phone_id)
        return WhatsAppAccountSnapshot(
            phone_number_id=phone_id,
            business_account_id=account_id,
            display_phone_number="",
            verified_name="Mock Business",
        )

    def get_business_status(
        self,
        *,
        access_token: str,
        phone_number_id: str,
    ) -> WhatsAppAccountSnapshot:
        if not (access_token or "").strip() or (access_token or "").startswith("revoked"):
            raise WhatsAppBusinessProviderError(
                "WhatsApp authorization expired.",
                code="REAUTH_REQUIRED",
            )
        return self.configure(
            access_token=access_token,
            phone_number_id=phone_number_id,
            business_account_id="mock-waba",
        )

    def send_message(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        to: str,
        body: str,
    ) -> WhatsAppSendResult:
        if not (access_token or "").strip() or (access_token or "").startswith("revoked"):
            raise WhatsAppBusinessProviderError(
                "WhatsApp authorization expired.",
                code="REAUTH_REQUIRED",
            )
        if self.fail_transient:
            raise WhatsAppBusinessProviderError(
                "WhatsApp rate limited the send.",
                code="RATE_LIMITED",
                transient=True,
            )
        if self.fail_send:
            raise WhatsAppBusinessProviderError(
                "WhatsApp send failed.",
                code="PROVIDER_ERROR",
            )
        message_id = f"wamid.mock.{uuid4().hex[:16]}"
        self.sent.append((to, message_id))
        logger.info(
            "whatsapp.mock_send phone_number_id=%s body_chars=%s provider_message_id=%s",
            phone_number_id,
            len(body or ""),
            message_id,
        )
        return WhatsAppSendResult(provider_message_id=message_id)

    def send_template_message(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        to: str,
        template_name: str,
        language: str,
        variables: list[str],
    ) -> WhatsAppSendResult:
        del template_name, language, variables
        return self.send_message(
            access_token=access_token,
            phone_number_id=phone_number_id,
            to=to,
            body="template",
        )

    def fetch_template_status(
        self,
        *,
        access_token: str,
        business_account_id: str,
        name: str,
        language: str,
    ) -> WhatsAppTemplateStatusSnapshot:
        del access_token
        return WhatsAppTemplateStatusSnapshot(
            name=name,
            language=language,
            status="APPROVED",
            provider_template_id=f"mock-template-{(business_account_id or 'unknown')[:32]}",
        )

    def list_templates(
        self,
        *,
        access_token: str,
        business_account_id: str,
    ) -> list[WhatsAppRemoteTemplate]:
        del access_token, business_account_id
        return list(self.remote_templates)

    def get_template(
        self,
        *,
        access_token: str,
        business_account_id: str,
        name: str,
        language: str,
    ) -> WhatsAppRemoteTemplate:
        del access_token, business_account_id
        for item in self.remote_templates:
            if item.name == name and item.language == language:
                return item
        raise WhatsAppBusinessProviderError("WhatsApp template was not found.", code="NOT_FOUND")

    def submit_template(
        self,
        *,
        access_token: str,
        business_account_id: str,
        name: str,
        language: str,
        category: str,
        body: str,
    ) -> WhatsAppRemoteTemplate:
        del access_token
        created = WhatsAppRemoteTemplate(
            name=name,
            language=language,
            status="PENDING",
            provider_template_id=f"mock-submit-{(business_account_id or 'acct')[:16]}-{name[:20]}",
            category=category,
            body=body,
        )
        self.remote_templates.append(created)
        return created

    def disconnect(self, *, access_token: str) -> None:
        del access_token
        return None


class DeferredWhatsAppBusinessProvider:
    name = "deferred"

    def configure(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        business_account_id: str,
    ) -> WhatsAppAccountSnapshot:
        del access_token, phone_number_id, business_account_id
        raise WhatsAppBusinessProviderError(
            "WhatsApp Business connection is not configured.",
            code="CONFIG_ERROR",
        )

    def get_business_status(
        self,
        *,
        access_token: str,
        phone_number_id: str,
    ) -> WhatsAppAccountSnapshot:
        del access_token, phone_number_id
        raise WhatsAppBusinessProviderError(
            "WhatsApp Business connection is not configured.",
            code="CONFIG_ERROR",
        )

    def send_message(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        to: str,
        body: str,
    ) -> WhatsAppSendResult:
        del access_token, phone_number_id, to, body
        raise WhatsAppBusinessProviderError(
            "WhatsApp Business sending is not configured.",
            code="CONFIG_ERROR",
        )

    def send_template_message(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        to: str,
        template_name: str,
        language: str,
        variables: list[str],
    ) -> WhatsAppSendResult:
        del access_token, phone_number_id, to, template_name, language, variables
        raise WhatsAppBusinessProviderError(
            "WhatsApp Business sending is not configured.",
            code="CONFIG_ERROR",
        )

    def fetch_template_status(
        self,
        *,
        access_token: str,
        business_account_id: str,
        name: str,
        language: str,
    ) -> WhatsAppTemplateStatusSnapshot:
        del access_token, business_account_id, name, language
        raise WhatsAppBusinessProviderError(
            "WhatsApp Business connection is not configured.",
            code="CONFIG_ERROR",
        )

    def list_templates(
        self,
        *,
        access_token: str,
        business_account_id: str,
    ) -> list[WhatsAppRemoteTemplate]:
        del access_token, business_account_id
        raise WhatsAppBusinessProviderError(
            "WhatsApp Business connection is not configured.",
            code="CONFIG_ERROR",
        )

    def get_template(
        self,
        *,
        access_token: str,
        business_account_id: str,
        name: str,
        language: str,
    ) -> WhatsAppRemoteTemplate:
        del access_token, business_account_id, name, language
        raise WhatsAppBusinessProviderError(
            "WhatsApp Business connection is not configured.",
            code="CONFIG_ERROR",
        )

    def submit_template(
        self,
        *,
        access_token: str,
        business_account_id: str,
        name: str,
        language: str,
        category: str,
        body: str,
    ) -> WhatsAppRemoteTemplate:
        del access_token, business_account_id, name, language, category, body
        raise WhatsAppBusinessProviderError(
            "WhatsApp template submission is not configured.",
            code="CONFIG_ERROR",
        )

    def disconnect(self, *, access_token: str) -> None:
        del access_token
        return None


class RealWhatsAppBusinessProvider:
    """Meta WhatsApp Cloud API. Credentials are passed in; never read from the client."""

    name = "meta"

    def _version(self) -> str:
        return (getattr(settings, "META_WHATSAPP_API_VERSION", "") or "v21.0").strip()

    def _headers(self, access_token: str) -> dict[str, str]:
        token = (access_token or "").strip()
        if not token:
            raise WhatsAppBusinessProviderError(
                "WhatsApp authorization required.",
                code="REAUTH_REQUIRED",
            )
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _raise_for_status(self, response: requests.Response, *, action: str) -> None:
        status = response.status_code
        if status in {401, 190}:
            raise WhatsAppBusinessProviderError(
                "WhatsApp authorization expired.",
                code="REAUTH_REQUIRED",
            )
        if status == 403:
            raise WhatsAppBusinessProviderError(
                "Insufficient permission for WhatsApp Business.",
                code="PERMISSION_DENIED",
            )
        if status == 429:
            raise WhatsAppBusinessProviderError(
                "WhatsApp rate limit reached.",
                code="RATE_LIMITED",
            )
        if status >= 400:
            logger.info("whatsapp.api_error action=%s status=%s", action, status)
            raise WhatsAppBusinessProviderError(
                f"WhatsApp API request failed during {action}.",
                code="PROVIDER_ERROR",
            )

    def configure(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        business_account_id: str,
    ) -> WhatsAppAccountSnapshot:
        snapshot = self.get_business_status(
            access_token=access_token,
            phone_number_id=phone_number_id,
        )
        return WhatsAppAccountSnapshot(
            phone_number_id=snapshot.phone_number_id,
            business_account_id=(business_account_id or "").strip(),
            display_phone_number=snapshot.display_phone_number,
            verified_name=snapshot.verified_name,
        )

    def get_business_status(
        self,
        *,
        access_token: str,
        phone_number_id: str,
    ) -> WhatsAppAccountSnapshot:
        phone_id = (phone_number_id or "").strip()
        if not phone_id:
            raise WhatsAppBusinessProviderError(
                "WhatsApp phone number id is required.",
                code="INVALID_CREDENTIALS",
            )
        url = f"{GRAPH_BASE}/{self._version()}/{phone_id}"
        try:
            response = requests.get(
                url,
                headers=self._headers(access_token),
                params={"fields": "display_phone_number,verified_name"},
                timeout=20,
            )
        except requests.RequestException as exc:
            raise WhatsAppBusinessProviderError(
                "Unable to reach WhatsApp API.",
                code="PROVIDER_ERROR",
            ) from exc
        self._raise_for_status(response, action="get_business_status")
        body = response.json() if response.content else {}
        return WhatsAppAccountSnapshot(
            phone_number_id=phone_id,
            business_account_id="",
            display_phone_number=str(body.get("display_phone_number") or ""),
            verified_name=str(body.get("verified_name") or ""),
        )

    def send_message(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        to: str,
        body: str,
    ) -> WhatsAppSendResult:
        return self._post_message(
            access_token=access_token,
            phone_number_id=phone_number_id,
            payload={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": body},
            },
        )

    def send_template_message(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        to: str,
        template_name: str,
        language: str,
        variables: list[str],
    ) -> WhatsAppSendResult:
        parameters = [{"type": "text", "text": value} for value in variables]
        template: dict = {
            "name": template_name,
            "language": {"code": language or "en"},
        }
        if parameters:
            template["components"] = [{"type": "body", "parameters": parameters}]
        return self._post_message(
            access_token=access_token,
            phone_number_id=phone_number_id,
            payload={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": template,
            },
        )

    def _post_message(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        payload: dict,
    ) -> WhatsAppSendResult:
        phone_id = (phone_number_id or "").strip()
        url = f"{GRAPH_BASE}/{self._version()}/{phone_id}/messages"
        try:
            response = requests.post(
                url,
                headers=self._headers(access_token),
                json=payload,
                timeout=20,
            )
        except requests.RequestException as exc:
            raise WhatsAppBusinessProviderError(
                "Unable to reach WhatsApp API.",
                code="PROVIDER_ERROR",
            ) from exc
        self._raise_for_status(response, action="send_message")
        body = response.json() if response.content else {}
        messages = body.get("messages") or []
        message_id = ""
        if messages and isinstance(messages[0], dict):
            message_id = str(messages[0].get("id") or "")
        if not message_id:
            raise WhatsAppBusinessProviderError(
                "WhatsApp did not return a message id.",
                code="PROVIDER_ERROR",
            )
        logger.info("whatsapp.sent phone_number_id=%s provider_message_id=%s", phone_id, message_id)
        return WhatsAppSendResult(provider_message_id=message_id)

    def fetch_template_status(
        self,
        *,
        access_token: str,
        business_account_id: str,
        name: str,
        language: str,
    ) -> WhatsAppTemplateStatusSnapshot:
        """Read an existing Meta template status. Does not create or submit templates."""
        account_id = (business_account_id or "").strip()
        url = f"{GRAPH_BASE}/{self._version()}/{account_id}/message_templates"
        try:
            response = requests.get(
                url,
                headers=self._headers(access_token),
                params={"name": name, "language": language},
                timeout=20,
            )
        except requests.RequestException as exc:
            raise WhatsAppBusinessProviderError(
                "Unable to reach WhatsApp API.",
                code="PROVIDER_ERROR",
            ) from exc
        self._raise_for_status(response, action="fetch_template_status")
        body = response.json() if response.content else {}
        data = body.get("data") or []
        if not data or not isinstance(data[0], dict):
            raise WhatsAppBusinessProviderError(
                "WhatsApp template was not found.",
                code="NOT_FOUND",
            )
        row = data[0]
        status_value = str(row.get("status") or "PENDING").upper()
        if status_value not in {"DRAFT", "PENDING", "APPROVED", "REJECTED", "DISABLED"}:
            status_value = "PENDING"
        return WhatsAppTemplateStatusSnapshot(
            name=name,
            language=language,
            status=status_value,
            provider_template_id=str(row.get("id") or ""),
        )

    def list_templates(
        self,
        *,
        access_token: str,
        business_account_id: str,
    ) -> list[WhatsAppRemoteTemplate]:
        account_id = (business_account_id or "").strip()
        url = f"{GRAPH_BASE}/{self._version()}/{account_id}/message_templates"
        try:
            response = requests.get(
                url,
                headers=self._headers(access_token),
                params={"limit": 100},
                timeout=20,
            )
        except requests.RequestException as exc:
            raise WhatsAppBusinessProviderError(
                "Unable to reach WhatsApp API.",
                code="PROVIDER_ERROR",
            ) from exc
        self._raise_for_status(response, action="list_templates")
        body = response.json() if response.content else {}
        rows = []
        for item in body.get("data") or []:
            if isinstance(item, dict):
                rows.append(_remote_from_graph(item))
        return rows

    def get_template(
        self,
        *,
        access_token: str,
        business_account_id: str,
        name: str,
        language: str,
    ) -> WhatsAppRemoteTemplate:
        snapshot = self.fetch_template_status(
            access_token=access_token,
            business_account_id=business_account_id,
            name=name,
            language=language,
        )
        return WhatsAppRemoteTemplate(
            name=snapshot.name,
            language=snapshot.language,
            status=snapshot.status,
            provider_template_id=snapshot.provider_template_id,
        )

    def submit_template(
        self,
        *,
        access_token: str,
        business_account_id: str,
        name: str,
        language: str,
        category: str,
        body: str,
    ) -> WhatsAppRemoteTemplate:
        """Submit a template to Meta. A successful response is not local approval."""
        account_id = (business_account_id or "").strip()
        url = f"{GRAPH_BASE}/{self._version()}/{account_id}/message_templates"
        payload = {
            "name": name,
            "language": language,
            "category": category,
            "components": [{"type": "BODY", "text": body}],
        }
        try:
            response = requests.post(
                url,
                headers=self._headers(access_token),
                json=payload,
                timeout=20,
            )
        except requests.RequestException as exc:
            raise WhatsAppBusinessProviderError(
                "Unable to reach WhatsApp API.",
                code="PROVIDER_ERROR",
            ) from exc
        self._raise_for_status(response, action="submit_template")
        row = response.json() if response.content else {}
        status_value = str(row.get("status") or "PENDING").upper()
        if status_value not in {"PENDING", "APPROVED", "REJECTED"}:
            status_value = "PENDING"
        return WhatsAppRemoteTemplate(
            name=name,
            language=language,
            status=status_value,
            provider_template_id=str(row.get("id") or ""),
            category=category,
            body=body,
        )

    def disconnect(self, *, access_token: str) -> None:
        # Meta has no general token-revoke for Cloud API user tokens here.
        del access_token
        return None


def _remote_from_graph(item: dict) -> WhatsAppRemoteTemplate:
    language = item.get("language")
    if isinstance(language, dict):
        language = language.get("code") or ""
    body = ""
    for component in item.get("components") or []:
        if isinstance(component, dict) and str(component.get("type") or "").upper() == "BODY":
            body = str(component.get("text") or "")[:4000]
            break
    status_value = str(item.get("status") or "PENDING").upper()
    return WhatsAppRemoteTemplate(
        name=str(item.get("name") or ""),
        language=str(language or ""),
        status=status_value,
        provider_template_id=str(item.get("id") or ""),
        category=str(item.get("category") or ""),
        body=body,
    )


_MOCK: MockWhatsAppBusinessProvider | None = None


def get_whatsapp_business_provider() -> WhatsAppBusinessProvider:
    name = (getattr(settings, "WHATSAPP_BUSINESS_PROVIDER", "deferred") or "deferred").lower()
    if name == "mock":
        global _MOCK
        if _MOCK is None:
            _MOCK = MockWhatsAppBusinessProvider()
        return _MOCK
    if name == "meta":
        return RealWhatsAppBusinessProvider()
    if name in {"deferred", "disabled"}:
        return DeferredWhatsAppBusinessProvider()
    raise WhatsAppBusinessProviderError(
        "Unknown WhatsApp Business provider.",
        code="CONFIG_ERROR",
    )


def reset_mock_whatsapp_business_provider() -> MockWhatsAppBusinessProvider:
    global _MOCK
    _MOCK = MockWhatsAppBusinessProvider()
    return _MOCK
