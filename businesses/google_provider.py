"""Google Business Profile provider abstraction (mock + real OAuth boundary)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlencode
from uuid import uuid4

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URI = "https://oauth2.googleapis.com/revoke"
GOOGLE_USERINFO_URI = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_ACCOUNT_MGMT_BASE = "https://mybusinessaccountmanagement.googleapis.com/v1"
GOOGLE_BUSINESS_INFO_BASE = "https://mybusinessbusinessinformation.googleapis.com/v1"


class GoogleBusinessProviderError(Exception):
    """Provider-side failure (mock or live API)."""

    def __init__(self, message: str, *, code: str = "PROVIDER_ERROR"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class GoogleProfileSnapshot:
    google_location_id: str
    google_account_id: str
    booking_url: str | None = None
    google_email: str | None = None


@dataclass(frozen=True)
class GoogleAccountSummary:
    name: str
    display_name: str
    account_type: str = ""


@dataclass(frozen=True)
class GoogleLocationSummary:
    name: str
    title: str
    store_code: str | None = None
    website_uri: str | None = None
    address: str | None = None
    phone: str | None = None


def _format_google_address(storefront: dict | None) -> str | None:
    if not isinstance(storefront, dict):
        return None
    parts: list[str] = []
    for line in storefront.get("addressLines") or []:
        cleaned = str(line or "").strip()
        if cleaned:
            parts.append(cleaned)
    for key in ("locality", "administrativeArea", "postalCode", "regionCode"):
        cleaned = str(storefront.get(key) or "").strip()
        if cleaned:
            parts.append(cleaned)
    return ", ".join(parts) if parts else None


def _normalize_location_resource_name(name: str) -> str:
    """Google patch/get expect ``locations/{id}``; list may return account-prefixed names."""
    cleaned = (name or "").strip()
    if not cleaned:
        return ""
    if cleaned.startswith("locations/"):
        return cleaned
    marker = "/locations/"
    if marker in cleaned:
        return f"locations/{cleaned.split(marker, 1)[1]}"
    if "/" not in cleaned:
        return f"locations/{cleaned}"
    return cleaned


@dataclass(frozen=True)
class GoogleBookingUrlUpdateResult:
    success: bool
    provider_reference: str
    booking_url: str
    message: str = ""


@dataclass(frozen=True)
class OAuthTokenBundle:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scopes: str
    google_account_id: str
    google_email: str


class GoogleBusinessProvider(Protocol):
    name: str

    def supports_oauth_connect(self) -> bool: ...

    def get_authorization_url(self, *, state: str) -> str: ...

    def exchange_code(self, *, code: str) -> OAuthTokenBundle: ...

    def refresh_credentials(self, *, refresh_token: str) -> OAuthTokenBundle: ...

    def revoke_credentials(self, *, token: str) -> None: ...

    def connect(self, *, location_id: str, business_id: str) -> GoogleProfileSnapshot: ...

    def disconnect(self, *, google_location_id: str) -> None: ...

    def get_profile(self, *, google_location_id: str) -> GoogleProfileSnapshot: ...

    def list_accounts(self, *, access_token: str) -> list[GoogleAccountSummary]: ...

    def list_locations(
        self,
        *,
        access_token: str,
        account_name: str,
    ) -> list[GoogleLocationSummary]: ...

    def get_location(
        self,
        *,
        access_token: str,
        location_name: str,
    ) -> GoogleLocationSummary: ...

    def update_booking_url(
        self,
        *,
        google_location_id: str,
        booking_url: str,
        access_token: str | None = None,
    ) -> GoogleBookingUrlUpdateResult: ...


def google_oauth_configured() -> bool:
    return bool(
        getattr(settings, "GOOGLE_BUSINESS_ENABLED", False)
        and (getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "") or "").strip()
        and (getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "") or "").strip()
        and (getattr(settings, "GOOGLE_OAUTH_REDIRECT_URI", "") or "").strip()
        and (getattr(settings, "GOOGLE_TOKEN_ENCRYPTION_KEY", "") or "").strip()
    )


def google_business_scopes() -> str:
    return (
        getattr(settings, "GOOGLE_BUSINESS_SCOPES", "")
        or "https://www.googleapis.com/auth/business.manage"
    ).strip()


def _mock_default_accounts() -> list[GoogleAccountSummary]:
    return [
        GoogleAccountSummary(
            name="accounts/mock-primary",
            display_name="Primary GBP Account",
            account_type="PERSONAL",
        ),
        GoogleAccountSummary(
            name="accounts/mock-secondary",
            display_name="Secondary GBP Account",
            account_type="LOCATION_GROUP",
        ),
    ]


def _mock_default_locations() -> dict[str, list[GoogleLocationSummary]]:
    return {
        "accounts/mock-primary": [
            GoogleLocationSummary(
                name="accounts/mock-primary/locations/loc-main",
                title="Main Street Salon",
                store_code="MAIN",
                website_uri=None,
                address="12 Main St, Hyderabad",
                phone="+919876543210",
            ),
            GoogleLocationSummary(
                name="accounts/mock-primary/locations/loc-downtown",
                title="Downtown Salon",
                store_code="DT",
                website_uri="https://example.com/old",
                address="88 Downtown Rd, Hyderabad",
                phone="+919876543211",
            ),
        ],
        "accounts/mock-secondary": [
            GoogleLocationSummary(
                name="accounts/mock-secondary/locations/loc-west",
                title="Westside Studio",
                store_code="WEST",
                website_uri=None,
                address="5 West Ave, Hyderabad",
                phone=None,
            ),
        ],
    }


class MockGoogleBusinessProvider:
    """Test/dev provider: in-memory fake Google accounts/locations, no network."""

    name = "mock"

    def __init__(self):
        self._profiles: dict[str, GoogleProfileSnapshot] = {}
        self._location_catalog: dict[str, GoogleLocationSummary] = {}
        self._accounts = _mock_default_accounts()
        self._locations_by_account = _mock_default_locations()
        self._rebuild_location_catalog()
        self.updated_urls: list[tuple[str, str]] = []
        self.authorization_urls: list[str] = []
        self.exchanged_codes: list[str] = []
        self.list_accounts_calls: list[str] = []
        self.list_locations_calls: list[tuple[str, str]] = []
        self.fail_list_accounts = False
        self.fail_list_locations = False
        self.fail_update = False

    def _rebuild_location_catalog(self) -> None:
        self._location_catalog = {}
        for locations in self._locations_by_account.values():
            for loc in locations:
                self._location_catalog[loc.name] = loc

    def supports_oauth_connect(self) -> bool:
        return True

    def get_authorization_url(self, *, state: str) -> str:
        url = f"https://mock.google/oauth?state={state}"
        self.authorization_urls.append(url)
        return url

    def exchange_code(self, *, code: str) -> OAuthTokenBundle:
        self.exchanged_codes.append(code)
        if code in {"", "invalid", "deny"}:
            raise GoogleBusinessProviderError(
                "Invalid authorization code.",
                code="INVALID_GRANT",
            )
        return OAuthTokenBundle(
            access_token=f"mock-access-{code}",
            refresh_token=f"mock-refresh-{code}",
            expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
            scopes=google_business_scopes(),
            google_account_id=f"mock-acct-{code[:8]}",
            google_email="owner@example.com",
        )

    def refresh_credentials(self, *, refresh_token: str) -> OAuthTokenBundle:
        if not refresh_token or refresh_token.startswith("revoked"):
            raise GoogleBusinessProviderError(
                "Refresh token revoked.",
                code="REAUTH_REQUIRED",
            )
        return OAuthTokenBundle(
            access_token=f"mock-access-refreshed-{uuid4().hex[:8]}",
            refresh_token=refresh_token,
            expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
            scopes=google_business_scopes(),
            google_account_id="mock-acct",
            google_email="owner@example.com",
        )

    def revoke_credentials(self, *, token: str) -> None:
        return None

    def list_accounts(self, *, access_token: str) -> list[GoogleAccountSummary]:
        cleaned = (access_token or "").strip()
        if not cleaned:
            raise GoogleBusinessProviderError(
                "Missing access token.",
                code="REAUTH_REQUIRED",
            )
        self.list_accounts_calls.append(cleaned)
        if self.fail_list_accounts:
            raise GoogleBusinessProviderError(
                "Unable to list Google Business accounts.",
                code="PROVIDER_ERROR",
            )
        if cleaned.startswith("revoked"):
            raise GoogleBusinessProviderError(
                "Google authorization expired.",
                code="REAUTH_REQUIRED",
            )
        return list(self._accounts)

    def list_locations(
        self,
        *,
        access_token: str,
        account_name: str,
    ) -> list[GoogleLocationSummary]:
        cleaned_token = (access_token or "").strip()
        cleaned_account = (account_name or "").strip()
        if not cleaned_token:
            raise GoogleBusinessProviderError(
                "Missing access token.",
                code="REAUTH_REQUIRED",
            )
        if not cleaned_account:
            raise GoogleBusinessProviderError(
                "Google Business account is required.",
                code="ACCOUNT_SELECTION_REQUIRED",
            )
        self.list_locations_calls.append((cleaned_token, cleaned_account))
        if self.fail_list_locations:
            raise GoogleBusinessProviderError(
                "Unable to list Google Business locations.",
                code="PROVIDER_ERROR",
            )
        if cleaned_token.startswith("revoked"):
            raise GoogleBusinessProviderError(
                "Google authorization expired.",
                code="REAUTH_REQUIRED",
            )
        locations = self._locations_by_account.get(cleaned_account)
        if locations is None:
            raise GoogleBusinessProviderError(
                "Google Business account not found.",
                code="NOT_FOUND",
            )
        return list(locations)

    def get_location(
        self,
        *,
        access_token: str,
        location_name: str,
    ) -> GoogleLocationSummary:
        del access_token
        cleaned = (location_name or "").strip()
        location = self._location_catalog.get(cleaned)
        if location is None:
            profile = self._profiles.get(cleaned)
            if profile is not None:
                return GoogleLocationSummary(
                    name=cleaned,
                    title=cleaned.split("/")[-1],
                    website_uri=profile.booking_url,
                )
            raise GoogleBusinessProviderError(
                "Google Business location not found.",
                code="NOT_FOUND",
            )
        profile = self._profiles.get(cleaned)
        if profile and profile.booking_url:
            return GoogleLocationSummary(
                name=location.name,
                title=location.title,
                store_code=location.store_code,
                website_uri=profile.booking_url,
            )
        return location

    def connect(self, *, location_id: str, business_id: str) -> GoogleProfileSnapshot:
        google_location_id = f"mock-loc-{location_id}"
        google_account_id = f"mock-acct-{business_id}"
        snapshot = GoogleProfileSnapshot(
            google_location_id=google_location_id,
            google_account_id=google_account_id,
            booking_url=None,
            google_email="owner@example.com",
        )
        self._profiles[google_location_id] = snapshot
        logger.info(
            "google.mock_connect location_id=%s business_id=%s google_location_id=%s",
            location_id,
            business_id,
            google_location_id,
        )
        return snapshot

    def disconnect(self, *, google_location_id: str) -> None:
        self._profiles.pop(google_location_id, None)
        logger.info("google.mock_disconnect google_location_id=%s", google_location_id)

    def get_profile(self, *, google_location_id: str) -> GoogleProfileSnapshot:
        profile = self._profiles.get(google_location_id)
        if profile is None:
            raise GoogleBusinessProviderError(
                "Google location not found in mock provider.",
                code="NOT_FOUND",
            )
        return profile

    def update_booking_url(
        self,
        *,
        google_location_id: str,
        booking_url: str,
        access_token: str | None = None,
    ) -> GoogleBookingUrlUpdateResult:
        del access_token
        if not google_location_id:
            raise GoogleBusinessProviderError(
                "Select a Google Business Profile location before syncing.",
                code="GOOGLE_LOCATION_SELECTION_REQUIRED",
            )
        if self.fail_update:
            raise GoogleBusinessProviderError(
                "Mock provider update failed.",
                code="PROVIDER_ERROR",
            )
        existing = self._profiles.get(google_location_id)
        if existing is None and google_location_id not in self._location_catalog:
            raise GoogleBusinessProviderError(
                "Google Business location not found.",
                code="NOT_FOUND",
            )
        account_id = existing.google_account_id if existing else "mock-acct"
        email = existing.google_email if existing else "owner@example.com"
        updated = GoogleProfileSnapshot(
            google_location_id=google_location_id,
            google_account_id=account_id,
            booking_url=booking_url,
            google_email=email,
        )
        self._profiles[google_location_id] = updated
        if google_location_id in self._location_catalog:
            loc = self._location_catalog[google_location_id]
            self._location_catalog[google_location_id] = GoogleLocationSummary(
                name=loc.name,
                title=loc.title,
                store_code=loc.store_code,
                website_uri=booking_url,
                address=loc.address,
                phone=loc.phone,
            )
        self.updated_urls.append((google_location_id, booking_url))
        reference = f"mock-sync-{uuid4().hex[:12]}"
        logger.info(
            "google.mock_update_booking_url google_location_id=%s reference=%s",
            google_location_id,
            reference,
        )
        return GoogleBookingUrlUpdateResult(
            success=True,
            provider_reference=reference,
            booking_url=booking_url,
            message="Mock booking URL updated.",
        )


class DeferredGoogleBusinessProvider:
    """Placeholder when Google is disabled / unconfigured."""

    name = "deferred"

    def supports_oauth_connect(self) -> bool:
        return False

    def get_authorization_url(self, *, state: str) -> str:
        raise GoogleBusinessProviderError(
            "Google Business OAuth is not configured.",
            code="CONFIG_ERROR",
        )

    def exchange_code(self, *, code: str) -> OAuthTokenBundle:
        raise GoogleBusinessProviderError(
            "Google Business OAuth is not configured.",
            code="CONFIG_ERROR",
        )

    def refresh_credentials(self, *, refresh_token: str) -> OAuthTokenBundle:
        raise GoogleBusinessProviderError(
            "Google Business OAuth is not configured.",
            code="CONFIG_ERROR",
        )

    def revoke_credentials(self, *, token: str) -> None:
        return None

    def connect(self, *, location_id: str, business_id: str) -> GoogleProfileSnapshot:
        raise GoogleBusinessProviderError(
            "Google OAuth connection is not available yet.",
            code="OAUTH_DEFERRED",
        )

    def disconnect(self, *, google_location_id: str) -> None:
        return None

    def get_profile(self, *, google_location_id: str) -> GoogleProfileSnapshot:
        raise GoogleBusinessProviderError(
            "Google OAuth connection is not available yet.",
            code="OAUTH_DEFERRED",
        )

    def list_accounts(self, *, access_token: str) -> list[GoogleAccountSummary]:
        raise GoogleBusinessProviderError(
            "Google Business account listing is not available yet.",
            code="OAUTH_DEFERRED",
        )

    def list_locations(
        self,
        *,
        access_token: str,
        account_name: str,
    ) -> list[GoogleLocationSummary]:
        raise GoogleBusinessProviderError(
            "Google Business location listing is not available yet.",
            code="OAUTH_DEFERRED",
        )

    def get_location(
        self,
        *,
        access_token: str,
        location_name: str,
    ) -> GoogleLocationSummary:
        raise GoogleBusinessProviderError(
            "Google Business location lookup is not available yet.",
            code="OAUTH_DEFERRED",
        )

    def update_booking_url(
        self,
        *,
        google_location_id: str,
        booking_url: str,
        access_token: str | None = None,
    ) -> GoogleBookingUrlUpdateResult:
        raise GoogleBusinessProviderError(
            "Google Business URL sync is not available yet.",
            code="OAUTH_DEFERRED",
        )


class RealGoogleBusinessProvider:
    """Live Google OAuth + Business Profile API boundary."""

    name = "google"

    def supports_oauth_connect(self) -> bool:
        return google_oauth_configured()

    def _client_id(self) -> str:
        return (getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "") or "").strip()

    def _client_secret(self) -> str:
        return (getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "") or "").strip()

    def _redirect_uri(self) -> str:
        return (getattr(settings, "GOOGLE_OAUTH_REDIRECT_URI", "") or "").strip()

    def _require_config(self) -> None:
        if not google_oauth_configured():
            raise GoogleBusinessProviderError(
                "Google Business OAuth is not configured.",
                code="CONFIG_ERROR",
            )

    def _require_access_token(self, access_token: str | None) -> str:
        cleaned = (access_token or "").strip()
        if not cleaned:
            raise GoogleBusinessProviderError(
                "Google authorization required.",
                code="REAUTH_REQUIRED",
            )
        return cleaned

    def _auth_headers(self, access_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    def _raise_for_status(self, response: requests.Response, *, action: str) -> None:
        status = response.status_code
        if status == 401:
            raise GoogleBusinessProviderError(
                "Google authorization expired. Reconnect required.",
                code="REAUTH_REQUIRED",
            )
        if status == 403:
            raise GoogleBusinessProviderError(
                "Insufficient permission for Google Business Profile.",
                code="PERMISSION_DENIED",
            )
        if status == 429:
            raise GoogleBusinessProviderError(
                "Google rate limit reached. Try again later.",
                code="RATE_LIMITED",
            )
        if status == 404:
            raise GoogleBusinessProviderError(
                f"Google Business resource not found during {action}.",
                code="NOT_FOUND",
            )
        if status >= 400:
            logger.info("google.api_error action=%s status=%s", action, status)
            raise GoogleBusinessProviderError(
                f"Google Business API request failed during {action}.",
                code="PROVIDER_ERROR",
            )

    def get_authorization_url(self, *, state: str) -> str:
        self._require_config()
        params = {
            "client_id": self._client_id(),
            "redirect_uri": self._redirect_uri(),
            "response_type": "code",
            "scope": google_business_scopes(),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        }
        return f"{GOOGLE_AUTH_URI}?{urlencode(params)}"

    def _parse_token_response(self, payload: dict) -> OAuthTokenBundle:
        access = (payload.get("access_token") or "").strip()
        if not access:
            raise GoogleBusinessProviderError(
                "Google token response missing access token.",
                code="TOKEN_EXCHANGE_FAILED",
            )
        refresh = payload.get("refresh_token")
        if refresh is not None:
            refresh = (refresh or "").strip() or None
        expires_in = payload.get("expires_in")
        expires_at = None
        if expires_in is not None:
            try:
                expires_at = datetime.now(tz=UTC) + timedelta(seconds=int(expires_in))
            except (TypeError, ValueError):
                expires_at = None
        scope = (payload.get("scope") or google_business_scopes()).strip()
        account_id = ""
        email = ""
        try:
            info = requests.get(
                GOOGLE_USERINFO_URI,
                headers={"Authorization": f"Bearer {access}"},
                timeout=15,
            )
            if info.status_code == 200:
                body = info.json()
                account_id = str(body.get("sub") or "")
                email = str(body.get("email") or "")
        except Exception:
            logger.info("google.userinfo_fetch_skipped")
        return OAuthTokenBundle(
            access_token=access,
            refresh_token=refresh,
            expires_at=expires_at,
            scopes=scope,
            google_account_id=account_id,
            google_email=email,
        )

    def exchange_code(self, *, code: str) -> OAuthTokenBundle:
        self._require_config()
        cleaned = (code or "").strip()
        if not cleaned:
            raise GoogleBusinessProviderError(
                "Missing authorization code.",
                code="INVALID_GRANT",
            )
        try:
            response = requests.post(
                GOOGLE_TOKEN_URI,
                data={
                    "code": cleaned,
                    "client_id": self._client_id(),
                    "client_secret": self._client_secret(),
                    "redirect_uri": self._redirect_uri(),
                    "grant_type": "authorization_code",
                },
                timeout=20,
            )
        except requests.RequestException as exc:
            logger.info("google.token_exchange_network_error")
            raise GoogleBusinessProviderError(
                "Unable to reach Google token endpoint.",
                code="TOKEN_EXCHANGE_FAILED",
            ) from exc
        if response.status_code >= 400:
            logger.info(
                "google.token_exchange_failed status=%s",
                response.status_code,
            )
            raise GoogleBusinessProviderError(
                "Google authorization code exchange failed.",
                code="INVALID_GRANT",
            )
        return self._parse_token_response(response.json())

    def refresh_credentials(self, *, refresh_token: str) -> OAuthTokenBundle:
        self._require_config()
        cleaned = (refresh_token or "").strip()
        if not cleaned:
            raise GoogleBusinessProviderError(
                "Missing refresh token.",
                code="REAUTH_REQUIRED",
            )
        try:
            response = requests.post(
                GOOGLE_TOKEN_URI,
                data={
                    "client_id": self._client_id(),
                    "client_secret": self._client_secret(),
                    "refresh_token": cleaned,
                    "grant_type": "refresh_token",
                },
                timeout=20,
            )
        except requests.RequestException as exc:
            raise GoogleBusinessProviderError(
                "Unable to refresh Google credentials.",
                code="TOKEN_REFRESH_FAILED",
            ) from exc
        if response.status_code in {400, 401}:
            raise GoogleBusinessProviderError(
                "Google authorization expired. Reconnect required.",
                code="REAUTH_REQUIRED",
            )
        if response.status_code >= 400:
            raise GoogleBusinessProviderError(
                "Google token refresh failed.",
                code="TOKEN_REFRESH_FAILED",
            )
        bundle = self._parse_token_response(response.json())
        if not bundle.refresh_token:
            bundle = OAuthTokenBundle(
                access_token=bundle.access_token,
                refresh_token=cleaned,
                expires_at=bundle.expires_at,
                scopes=bundle.scopes,
                google_account_id=bundle.google_account_id,
                google_email=bundle.google_email,
            )
        return bundle

    def revoke_credentials(self, *, token: str) -> None:
        cleaned = (token or "").strip()
        if not cleaned:
            return
        try:
            requests.post(GOOGLE_REVOKE_URI, data={"token": cleaned}, timeout=10)
        except requests.RequestException:
            logger.info("google.revoke_network_error")

    def connect(self, *, location_id: str, business_id: str) -> GoogleProfileSnapshot:
        del location_id, business_id
        raise GoogleBusinessProviderError(
            "Use OAuth authorization for Google connections.",
            code="OAUTH_REQUIRED",
        )

    def disconnect(self, *, google_location_id: str) -> None:
        del google_location_id
        return None

    def get_profile(self, *, google_location_id: str) -> GoogleProfileSnapshot:
        del google_location_id
        raise GoogleBusinessProviderError(
            "Google Business Profile selection is required.",
            code="GOOGLE_LOCATION_SELECTION_REQUIRED",
        )

    def list_accounts(self, *, access_token: str) -> list[GoogleAccountSummary]:
        token = self._require_access_token(access_token)
        try:
            response = requests.get(
                f"{GOOGLE_ACCOUNT_MGMT_BASE}/accounts",
                headers=self._auth_headers(token),
                timeout=20,
            )
        except requests.RequestException as exc:
            raise GoogleBusinessProviderError(
                "Unable to reach Google Business accounts API.",
                code="PROVIDER_ERROR",
            ) from exc
        self._raise_for_status(response, action="list_accounts")
        payload = response.json()
        accounts: list[GoogleAccountSummary] = []
        for item in payload.get("accounts") or []:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            accounts.append(
                GoogleAccountSummary(
                    name=name,
                    display_name=str(item.get("accountName") or name),
                    account_type=str(item.get("type") or ""),
                )
            )
        return accounts

    def list_locations(
        self,
        *,
        access_token: str,
        account_name: str,
    ) -> list[GoogleLocationSummary]:
        token = self._require_access_token(access_token)
        cleaned_account = (account_name or "").strip()
        if not cleaned_account:
            raise GoogleBusinessProviderError(
                "Google Business account is required.",
                code="ACCOUNT_SELECTION_REQUIRED",
            )
        try:
            response = requests.get(
                f"{GOOGLE_BUSINESS_INFO_BASE}/{cleaned_account}/locations",
                headers=self._auth_headers(token),
                params={
                    "readMask": "name,title,storeCode,websiteUri,phoneNumbers,storefrontAddress",
                    "pageSize": 100,
                },
                timeout=20,
            )
        except requests.RequestException as exc:
            raise GoogleBusinessProviderError(
                "Unable to reach Google Business locations API.",
                code="PROVIDER_ERROR",
            ) from exc
        self._raise_for_status(response, action="list_locations")
        payload = response.json()
        locations: list[GoogleLocationSummary] = []
        for item in payload.get("locations") or []:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            website = item.get("websiteUri")
            phones = item.get("phoneNumbers") if isinstance(item.get("phoneNumbers"), dict) else {}
            phone = str((phones or {}).get("primaryPhone") or "").strip() or None
            locations.append(
                GoogleLocationSummary(
                    name=name,
                    title=str(item.get("title") or name),
                    store_code=(str(item.get("storeCode")) if item.get("storeCode") else None),
                    website_uri=(str(website) if website else None),
                    address=_format_google_address(item.get("storefrontAddress")),
                    phone=phone,
                )
            )
        return locations

    def get_location(
        self,
        *,
        access_token: str,
        location_name: str,
    ) -> GoogleLocationSummary:
        token = self._require_access_token(access_token)
        cleaned = _normalize_location_resource_name(location_name)
        if not cleaned:
            raise GoogleBusinessProviderError(
                "Google Business location is required.",
                code="GOOGLE_LOCATION_SELECTION_REQUIRED",
            )
        try:
            response = requests.get(
                f"{GOOGLE_BUSINESS_INFO_BASE}/{cleaned}",
                headers=self._auth_headers(token),
                params={
                    "readMask": "name,title,storeCode,websiteUri,phoneNumbers,storefrontAddress"
                },
                timeout=20,
            )
        except requests.RequestException as exc:
            raise GoogleBusinessProviderError(
                "Unable to reach Google Business location API.",
                code="PROVIDER_ERROR",
            ) from exc
        self._raise_for_status(response, action="get_location")
        item = response.json()
        website = item.get("websiteUri")
        phones = item.get("phoneNumbers") if isinstance(item.get("phoneNumbers"), dict) else {}
        phone = str((phones or {}).get("primaryPhone") or "").strip() or None
        return GoogleLocationSummary(
            name=str(item.get("name") or cleaned),
            title=str(item.get("title") or cleaned),
            store_code=(str(item.get("storeCode")) if item.get("storeCode") else None),
            website_uri=(str(website) if website else None),
            address=_format_google_address(item.get("storefrontAddress")),
            phone=phone,
        )

    def update_booking_url(
        self,
        *,
        google_location_id: str,
        booking_url: str,
        access_token: str | None = None,
    ) -> GoogleBookingUrlUpdateResult:
        cleaned_location = _normalize_location_resource_name(google_location_id)
        cleaned_url = (booking_url or "").strip()
        if not cleaned_location:
            raise GoogleBusinessProviderError(
                "Select a Google Business Profile location before syncing.",
                code="GOOGLE_LOCATION_SELECTION_REQUIRED",
            )
        if not cleaned_url:
            raise GoogleBusinessProviderError(
                "Booking URL is required.",
                code="INVALID_URL",
            )
        token = self._require_access_token(access_token)
        current = self.get_location(access_token=token, location_name=cleaned_location)
        if current.website_uri == cleaned_url:
            return GoogleBookingUrlUpdateResult(
                success=True,
                provider_reference=f"google-noop-{uuid4().hex[:12]}",
                booking_url=cleaned_url,
                message="Booking URL already synced.",
            )
        try:
            response = requests.patch(
                f"{GOOGLE_BUSINESS_INFO_BASE}/{cleaned_location}",
                headers=self._auth_headers(token),
                params={"updateMask": "websiteUri"},
                json={"websiteUri": cleaned_url},
                timeout=20,
            )
        except requests.RequestException as exc:
            raise GoogleBusinessProviderError(
                "Unable to update Google Business location URL.",
                code="PROVIDER_ERROR",
            ) from exc
        self._raise_for_status(response, action="update_booking_url")
        reference = f"google-sync-{uuid4().hex[:12]}"
        logger.info(
            "google.update_booking_url google_location_id=%s reference=%s",
            cleaned_location,
            reference,
        )
        return GoogleBookingUrlUpdateResult(
            success=True,
            provider_reference=reference,
            booking_url=cleaned_url,
            message="Booking URL synced to Google Business Profile.",
        )


_MOCK_SINGLETON: MockGoogleBusinessProvider | None = None


def get_google_business_provider() -> GoogleBusinessProvider:
    name = (getattr(settings, "GOOGLE_BUSINESS_PROVIDER", "deferred") or "deferred").lower()
    if name == "mock":
        global _MOCK_SINGLETON
        if _MOCK_SINGLETON is None:
            _MOCK_SINGLETON = MockGoogleBusinessProvider()
        return _MOCK_SINGLETON
    if name == "google":
        return RealGoogleBusinessProvider()
    if name in {"deferred", "disabled"}:
        return DeferredGoogleBusinessProvider()
    raise GoogleBusinessProviderError(
        f"Unknown GOOGLE_BUSINESS_PROVIDER={name!r}. Use 'mock', 'google', or 'deferred'.",
        code="CONFIG_ERROR",
    )


def reset_mock_google_business_provider() -> MockGoogleBusinessProvider:
    """Test helper: replace the process-wide mock provider."""
    global _MOCK_SINGLETON
    _MOCK_SINGLETON = MockGoogleBusinessProvider()
    return _MOCK_SINGLETON
