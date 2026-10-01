"""Google Business Profile integration — OAuth, credentials, URL sync."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from businesses.google_crypto import (
    GoogleCryptoError,
    decrypt_token,
    encrypt_token,
    require_encryption_configured,
)
from businesses.google_provider import (
    GoogleBusinessProviderError,
    get_google_business_provider,
    google_oauth_configured,
)
from businesses.models import (
    GoogleBusinessConnection,
    GoogleConnectionStatus,
    GoogleOAuthState,
    GoogleSyncStatus,
    WebsiteStatus,
)
from businesses.services import get_business_for_organization
from locations.services import get_location_for_business
from sites.provisioning_services import provisioned_public_url
from sites.services import booking_url_for_location

logger = logging.getLogger(__name__)

OAUTH_STATE_TTL_MINUTES = 15


def _get_launch_profile(*, organization, business, location):
    from businesses.models import BusinessLaunchProfile

    return (
        BusinessLaunchProfile.objects.filter(
            organization=organization,
            business=business,
            location=location,
            deleted_at__isnull=True,
        )
        .select_related("location", "business")
        .first()
    )


def resolve_canonical_google_urls(*, organization, business, location) -> dict:
    if not location.is_active or location.deleted_at is not None:
        return {
            "syncable": False,
            "reason": "LOCATION_INACTIVE",
            "website_url": None,
            "booking_url": None,
            "website_status": None,
            "subdomain": None,
        }
    if not business.is_active or business.deleted_at is not None:
        return {
            "syncable": False,
            "reason": "BUSINESS_INACTIVE",
            "website_url": None,
            "booking_url": None,
            "website_status": None,
            "subdomain": None,
        }

    profile = _get_launch_profile(
        organization=organization,
        business=business,
        location=location,
    )
    website_status = profile.website_status if profile else None
    subdomain = profile.subdomain if profile and profile.subdomain else None
    website_url = provisioned_public_url(subdomain) if subdomain else None
    booking_url = booking_url_for_location(location)

    published = bool(profile and profile.website_status == WebsiteStatus.PUBLISHED and subdomain)
    if not published:
        return {
            "syncable": False,
            "reason": "WEBSITE_NOT_PUBLISHED",
            "website_url": website_url,
            "booking_url": booking_url,
            "website_status": website_status,
            "subdomain": subdomain,
        }

    return {
        "syncable": True,
        "reason": None,
        "website_url": website_url,
        "booking_url": booking_url,
        "website_status": website_status,
        "subdomain": subdomain,
    }


def _hash_state(raw_state: str) -> str:
    return hashlib.sha256(raw_state.encode("utf-8")).hexdigest()


def _provider_kind_name() -> str:
    return (getattr(settings, "GOOGLE_BUSINESS_PROVIDER", "deferred") or "deferred").lower()


def get_or_create_google_connection(
    *,
    organization,
    business_id,
    location_id,
    actor=None,
) -> GoogleBusinessConnection:
    business = get_business_for_organization(
        organization=organization,
        business_id=business_id,
    )
    location = get_location_for_business(
        organization=organization,
        business=business,
        location_id=location_id,
    )
    connection, created = GoogleBusinessConnection.objects.get_or_create(
        organization=organization,
        business=business,
        location=location,
        defaults={
            "status": GoogleConnectionStatus.NOT_CONNECTED,
            "provider": _provider_kind_name(),
            "created_by": actor,
            "updated_by": actor,
        },
    )
    if created:
        logger.info(
            "google.connection_created business_id=%s location_id=%s",
            business_id,
            location_id,
        )
    return connection


def serialize_google_connection(
    connection: GoogleBusinessConnection,
    *,
    urls: dict | None = None,
) -> dict:
    urls = urls or resolve_canonical_google_urls(
        organization=connection.organization,
        business=connection.business,
        location=connection.location,
    )
    connected = connection.status in {
        GoogleConnectionStatus.CONNECTED,
        GoogleConnectionStatus.LOCATION_SELECTION_REQUIRED,
        GoogleConnectionStatus.SYNCING,
    }
    location_selected = bool(connection.google_location_id)
    account_selected = bool(connection.google_business_account_name)
    website_sync_available = bool(urls.get("syncable") and connected and location_selected)
    oauth_available = _provider_kind_name() in {"mock", "google"} and (
        _provider_kind_name() == "mock" or google_oauth_configured()
    )
    synced = (
        location_selected
        and connection.last_sync_status == GoogleSyncStatus.SUCCESS
        and bool(connection.last_synced_booking_url)
    )
    return {
        "id": str(connection.id),
        "business_id": str(connection.business_id),
        "location_id": str(connection.location_id),
        "connected": connected,
        "status": connection.status,
        "provider": connection.provider or _provider_kind_name(),
        "google_account": {
            "id": connection.google_account_id or None,
            "email": connection.google_email or None,
        },
        "google_business_account": {
            "name": connection.google_business_account_name or None,
            "selected": account_selected,
        },
        "google_location": {
            "id": connection.google_location_id or None,
            "display_name": connection.google_location_display_name or None,
            "selected": location_selected,
        },
        "google_location_id": connection.google_location_id or None,
        "google_account_id": connection.google_account_id or None,
        "google_location_display_name": connection.google_location_display_name or None,
        "account_selected": account_selected,
        "location_selected": location_selected,
        "mapped": location_selected
        and connection.status
        in {
            GoogleConnectionStatus.CONNECTED,
            GoogleConnectionStatus.SYNCING,
        },
        "synced": synced,
        "website_sync_available": website_sync_available,
        "last_synced_booking_url": connection.last_synced_booking_url or None,
        "last_sync_status": connection.last_sync_status,
        "last_synced_at": (
            connection.last_synced_at.isoformat() if connection.last_synced_at else None
        ),
        "connected_at": (connection.connected_at.isoformat() if connection.connected_at else None),
        "token_expires_at": (
            connection.token_expires_at.isoformat() if connection.token_expires_at else None
        ),
        "last_error_code": connection.last_error_code or None,
        "last_error_message": connection.last_error_message or None,
        "website_url": urls.get("website_url"),
        "booking_url": urls.get("booking_url"),
        "syncable": bool(urls.get("syncable")),
        "sync_block_reason": urls.get("reason"),
        "oauth_available": oauth_available,
        "selection_required": connection.status
        == GoogleConnectionStatus.LOCATION_SELECTION_REQUIRED
        or (connected and not location_selected),
    }


def get_google_connection_status(
    *,
    organization,
    business_id,
    location_id,
) -> dict:
    connection = get_or_create_google_connection(
        organization=organization,
        business_id=business_id,
        location_id=location_id,
    )
    return serialize_google_connection(connection)


def create_oauth_state(
    *,
    user,
    organization,
    business,
    location,
) -> str:
    raw = secrets.token_urlsafe(32)
    GoogleOAuthState.objects.create(
        state_hash=_hash_state(raw),
        user=user,
        organization=organization,
        business=business,
        location=location,
        expires_at=timezone.now() + timedelta(minutes=OAUTH_STATE_TTL_MINUTES),
    )
    return raw


@transaction.atomic
def consume_oauth_state(*, raw_state: str, user=None) -> GoogleOAuthState:
    cleaned = (raw_state or "").strip()
    if not cleaned:
        raise ValidationError({"state": "Invalid OAuth state."})
    state_hash = _hash_state(cleaned)
    try:
        row = GoogleOAuthState.objects.select_for_update().get(state_hash=state_hash)
    except GoogleOAuthState.DoesNotExist as exc:
        raise ValidationError({"state": "Invalid OAuth state."}) from exc
    if row.used_at is not None:
        raise ValidationError({"state": "OAuth state has already been used."})
    if row.expires_at <= timezone.now():
        raise ValidationError({"state": "OAuth state has expired."})
    if user is not None and row.user_id != user.id:
        raise ValidationError({"state": "OAuth state does not match this user."})
    row.used_at = timezone.now()
    row.save(update_fields=["used_at", "updated_at"])
    return row


def _store_encrypted_tokens(
    connection: GoogleBusinessConnection,
    *,
    access_token: str,
    refresh_token: str | None,
    preserve_existing_refresh: bool,
) -> None:
    require_encryption_configured()
    connection.access_token_encrypted = encrypt_token(access_token)
    if refresh_token:
        connection.refresh_token_encrypted = encrypt_token(refresh_token)
    elif not preserve_existing_refresh:
        # Explicit clear only when intentionally disconnecting (handled elsewhere).
        pass
    # Never overwrite an existing refresh token with empty/null on reconnect.


def _clear_encrypted_tokens(connection: GoogleBusinessConnection) -> None:
    connection.access_token_encrypted = ""
    connection.refresh_token_encrypted = ""
    connection.token_expires_at = None
    connection.scopes = ""


def ensure_valid_access_token(connection: GoogleBusinessConnection) -> str:
    """Return a usable access token, refreshing once if needed."""
    try:
        access = decrypt_token(connection.access_token_encrypted)
    except GoogleCryptoError as exc:
        connection.status = GoogleConnectionStatus.REAUTH_REQUIRED
        connection.last_error_code = "DECRYPT_FAILED"
        connection.last_error_message = "Stored credentials are unreadable."
        connection.save(
            update_fields=[
                "status",
                "last_error_code",
                "last_error_message",
                "updated_at",
            ]
        )
        raise ValidationError({"status": "Reconnect Google Business Profile."}) from exc

    expires = connection.token_expires_at
    if access and expires and expires > timezone.now() + timedelta(seconds=60):
        return access

    try:
        refresh = decrypt_token(connection.refresh_token_encrypted)
    except GoogleCryptoError as exc:
        connection.status = GoogleConnectionStatus.REAUTH_REQUIRED
        connection.save(update_fields=["status", "updated_at"])
        raise ValidationError({"status": "Reconnect Google Business Profile."}) from exc

    if not refresh:
        connection.status = GoogleConnectionStatus.REAUTH_REQUIRED
        connection.last_error_code = "REAUTH_REQUIRED"
        connection.last_error_message = "Missing refresh token."
        connection.save(
            update_fields=[
                "status",
                "last_error_code",
                "last_error_message",
                "updated_at",
            ]
        )
        raise ValidationError({"status": "Reconnect Google Business Profile."})

    provider = get_google_business_provider()
    try:
        bundle = provider.refresh_credentials(refresh_token=refresh)
    except GoogleBusinessProviderError as exc:
        if exc.code == "REAUTH_REQUIRED":
            connection.status = GoogleConnectionStatus.REAUTH_REQUIRED
        else:
            connection.status = GoogleConnectionStatus.ERROR
        connection.last_error_code = exc.code
        connection.last_error_message = str(exc)
        connection.save(
            update_fields=[
                "status",
                "last_error_code",
                "last_error_message",
                "updated_at",
            ]
        )
        raise ValidationError({"status": str(exc), "error_code": exc.code}) from None

    _store_encrypted_tokens(
        connection,
        access_token=bundle.access_token,
        refresh_token=bundle.refresh_token,
        preserve_existing_refresh=True,
    )
    connection.token_expires_at = bundle.expires_at
    if bundle.scopes:
        connection.scopes = bundle.scopes[:500]
    connection.save(
        update_fields=[
            "access_token_encrypted",
            "refresh_token_encrypted",
            "token_expires_at",
            "scopes",
            "updated_at",
        ]
    )
    return bundle.access_token


def _connection_for_google_ops(
    *,
    organization,
    business_id,
    location_id,
    actor=None,
    for_update: bool = False,
) -> GoogleBusinessConnection:
    connection = get_or_create_google_connection(
        organization=organization,
        business_id=business_id,
        location_id=location_id,
        actor=actor,
    )
    qs = GoogleBusinessConnection.objects.select_related("business", "location", "organization")
    if for_update:
        qs = qs.select_for_update()
    return qs.get(pk=connection.pk)


def _require_oauth_ready(connection: GoogleBusinessConnection) -> None:
    if connection.status == GoogleConnectionStatus.REAUTH_REQUIRED:
        raise ValidationError(
            {
                "status": "Reconnect Google Business Profile.",
                "error_code": "REAUTH_REQUIRED",
            }
        )
    if connection.status in {
        GoogleConnectionStatus.NOT_CONNECTED,
        GoogleConnectionStatus.DISCONNECTED,
    }:
        raise ValidationError(
            {
                "status": "Connect Google Business Profile first.",
                "error_code": "NOT_CONNECTED",
            }
        )
    if not connection.access_token_encrypted and not connection.refresh_token_encrypted:
        # Mock direct-connect may map without encrypted tokens.
        if connection.provider == "mock" and connection.google_location_id:
            return
        if connection.provider == "mock" and connection.status in {
            GoogleConnectionStatus.CONNECTED,
            GoogleConnectionStatus.LOCATION_SELECTION_REQUIRED,
        }:
            return
        raise ValidationError(
            {
                "status": "Connect Google Business Profile first.",
                "error_code": "NOT_CONNECTED",
            }
        )


def _mark_reauth(connection: GoogleBusinessConnection, *, actor=None, message: str) -> None:
    connection.status = GoogleConnectionStatus.REAUTH_REQUIRED
    connection.last_error_code = "REAUTH_REQUIRED"
    connection.last_error_message = message
    update_fields = [
        "status",
        "last_error_code",
        "last_error_message",
        "updated_at",
    ]
    if actor is not None:
        connection.updated_by = actor
        update_fields.append("updated_by")
    connection.save(update_fields=update_fields)


def _serialize_account(summary) -> dict:
    return {
        "name": summary.name,
        "display_name": summary.display_name,
        "account_type": summary.account_type or None,
    }


def _serialize_location(summary) -> dict:
    return {
        "id": summary.name,
        "name": summary.name,
        "title": summary.title,
        "store_code": summary.store_code,
        "address": summary.address,
        "phone": summary.phone,
        "website_uri": summary.website_uri,
    }


def list_google_business_accounts(
    *,
    organization,
    business_id,
    location_id,
    actor,
) -> dict:
    connection = _connection_for_google_ops(
        organization=organization,
        business_id=business_id,
        location_id=location_id,
        actor=actor,
        for_update=False,
    )
    _require_oauth_ready(connection)

    access_token = None
    if connection.access_token_encrypted or connection.refresh_token_encrypted:
        try:
            access_token = ensure_valid_access_token(connection)
        except ValidationError:
            connection.refresh_from_db()
            raise
    elif connection.provider == "mock":
        access_token = "mock-access-list"

    provider = get_google_business_provider()
    try:
        accounts = provider.list_accounts(access_token=access_token or "")
    except GoogleBusinessProviderError as exc:
        if exc.code == "REAUTH_REQUIRED":
            _mark_reauth(connection, actor=actor, message=str(exc))
        raise ValidationError({"status": str(exc), "error_code": exc.code}) from None

    auto_selected = False
    if len(accounts) == 1 and not connection.google_business_account_name:
        connection.google_business_account_name = accounts[0].name
        connection.updated_by = actor
        connection.save(
            update_fields=[
                "google_business_account_name",
                "updated_by",
                "updated_at",
            ]
        )
        auto_selected = True
    elif (
        len(accounts) == 1
        and connection.google_business_account_name
        and connection.google_business_account_name != accounts[0].name
        and not connection.google_location_id
    ):
        connection.google_business_account_name = accounts[0].name
        connection.updated_by = actor
        connection.save(
            update_fields=[
                "google_business_account_name",
                "updated_by",
                "updated_at",
            ]
        )
        auto_selected = True

    return {
        "accounts": [_serialize_account(item) for item in accounts],
        "count": len(accounts),
        "selected_account_name": connection.google_business_account_name or None,
        "account_selection_required": len(accounts) > 1
        and not connection.google_business_account_name,
        "auto_selected": auto_selected,
        "connection": serialize_google_connection(connection),
    }


@transaction.atomic
def select_google_business_account(
    *,
    organization,
    business_id,
    location_id,
    actor,
    account_name: str,
) -> dict:
    cleaned = (account_name or "").strip()
    if not cleaned:
        raise ValidationError(
            {
                "google_account_name": "Google Business account is required.",
                "error_code": "ACCOUNT_SELECTION_REQUIRED",
            }
        )

    connection = _connection_for_google_ops(
        organization=organization,
        business_id=business_id,
        location_id=location_id,
        actor=actor,
        for_update=True,
    )
    _require_oauth_ready(connection)

    access_token = None
    if connection.access_token_encrypted or connection.refresh_token_encrypted:
        access_token = ensure_valid_access_token(connection)
    elif connection.provider == "mock":
        access_token = "mock-access-select-account"

    provider = get_google_business_provider()
    try:
        accounts = provider.list_accounts(access_token=access_token or "")
    except GoogleBusinessProviderError as exc:
        if exc.code == "REAUTH_REQUIRED":
            _mark_reauth(connection, actor=actor, message=str(exc))
        raise ValidationError({"status": str(exc), "error_code": exc.code}) from None

    match = next((item for item in accounts if item.name == cleaned), None)
    if match is None:
        raise ValidationError(
            {
                "google_account_name": "Google Business account not found.",
                "error_code": "NOT_FOUND",
            }
        )

    if connection.google_business_account_name != cleaned:
        # Changing account clears prior location mapping (must re-select).
        connection.google_location_id = ""
        connection.google_location_display_name = ""
        connection.last_sync_status = GoogleSyncStatus.NEVER
        connection.last_synced_booking_url = ""
        connection.last_synced_at = None

    connection.google_business_account_name = cleaned
    connection.status = GoogleConnectionStatus.LOCATION_SELECTION_REQUIRED
    connection.last_error_code = ""
    connection.last_error_message = ""
    connection.updated_by = actor
    connection.save(
        update_fields=[
            "google_business_account_name",
            "google_location_id",
            "google_location_display_name",
            "status",
            "last_sync_status",
            "last_synced_booking_url",
            "last_synced_at",
            "last_error_code",
            "last_error_message",
            "updated_by",
            "updated_at",
        ]
    )
    return {
        "selected_account": _serialize_account(match),
        "connection": serialize_google_connection(connection),
    }


def list_google_business_locations(
    *,
    organization,
    business_id,
    location_id,
    actor,
    account_name: str | None = None,
) -> dict:
    connection = _connection_for_google_ops(
        organization=organization,
        business_id=business_id,
        location_id=location_id,
        actor=actor,
        for_update=False,
    )
    _require_oauth_ready(connection)

    access_token = None
    if connection.access_token_encrypted or connection.refresh_token_encrypted:
        access_token = ensure_valid_access_token(connection)
    elif connection.provider == "mock":
        access_token = "mock-access-list-locations"

    provider = get_google_business_provider()
    cleaned_account = (account_name or connection.google_business_account_name or "").strip()
    if not cleaned_account:
        try:
            accounts = provider.list_accounts(access_token=access_token or "")
        except GoogleBusinessProviderError as exc:
            if exc.code == "REAUTH_REQUIRED":
                _mark_reauth(connection, actor=actor, message=str(exc))
            raise ValidationError({"status": str(exc), "error_code": exc.code}) from None
        if len(accounts) == 1:
            cleaned_account = accounts[0].name
            connection.google_business_account_name = cleaned_account
            connection.updated_by = actor
            connection.save(
                update_fields=[
                    "google_business_account_name",
                    "updated_by",
                    "updated_at",
                ]
            )
        elif len(accounts) == 0:
            raise ValidationError(
                {
                    "status": "No Google Business accounts available.",
                    "error_code": "NOT_FOUND",
                }
            )
        else:
            raise ValidationError(
                {
                    "status": "Select a Google Business account first.",
                    "error_code": "ACCOUNT_SELECTION_REQUIRED",
                    "accounts": [_serialize_account(item) for item in accounts],
                }
            )

    try:
        locations = provider.list_locations(
            access_token=access_token or "",
            account_name=cleaned_account,
        )
    except GoogleBusinessProviderError as exc:
        if exc.code == "REAUTH_REQUIRED":
            _mark_reauth(connection, actor=actor, message=str(exc))
        raise ValidationError({"status": str(exc), "error_code": exc.code}) from None

    return {
        "account_name": cleaned_account,
        "locations": [_serialize_location(item) for item in locations],
        "count": len(locations),
        "selected_location_id": connection.google_location_id or None,
        "location_selection_required": not bool(connection.google_location_id),
        "connection": serialize_google_connection(connection),
    }


@transaction.atomic
def select_google_business_location(
    *,
    organization,
    business_id,
    location_id,
    actor,
    google_location_id: str,
    google_account_name: str | None = None,
) -> dict:
    cleaned_location = (google_location_id or "").strip()
    if not cleaned_location:
        raise ValidationError(
            {
                "google_location_id": "Google Business location is required.",
                "error_code": "GOOGLE_LOCATION_SELECTION_REQUIRED",
            }
        )

    connection = _connection_for_google_ops(
        organization=organization,
        business_id=business_id,
        location_id=location_id,
        actor=actor,
        for_update=True,
    )
    _require_oauth_ready(connection)

    access_token = None
    if connection.access_token_encrypted or connection.refresh_token_encrypted:
        access_token = ensure_valid_access_token(connection)
    elif connection.provider == "mock":
        access_token = "mock-access-select-location"

    provider = get_google_business_provider()
    cleaned_account = (google_account_name or connection.google_business_account_name or "").strip()
    if not cleaned_account:
        raise ValidationError(
            {
                "status": "Select a Google Business account first.",
                "error_code": "ACCOUNT_SELECTION_REQUIRED",
            }
        )

    try:
        available = provider.list_locations(
            access_token=access_token or "",
            account_name=cleaned_account,
        )
    except GoogleBusinessProviderError as exc:
        if exc.code == "REAUTH_REQUIRED":
            _mark_reauth(connection, actor=actor, message=str(exc))
        raise ValidationError({"status": str(exc), "error_code": exc.code}) from None

    match = next((item for item in available if item.name == cleaned_location), None)
    if match is None:
        # Accept normalized locations/{id} forms for real Google names.
        from businesses.google_provider import _normalize_location_resource_name

        normalized = _normalize_location_resource_name(cleaned_location)
        match = next(
            (
                item
                for item in available
                if _normalize_location_resource_name(item.name) == normalized
            ),
            None,
        )
    if match is None:
        raise ValidationError(
            {
                "google_location_id": "Google Business location not found for this account.",
                "error_code": "NOT_FOUND",
            }
        )

    if (
        connection.google_location_id
        and connection.google_location_id != match.name
        and connection.last_sync_status == GoogleSyncStatus.SUCCESS
    ):
        connection.last_sync_status = GoogleSyncStatus.NEVER
        connection.last_synced_booking_url = ""
        connection.last_synced_at = None

    connection.google_business_account_name = cleaned_account
    connection.google_location_id = match.name
    connection.google_location_display_name = (match.title or "")[:255]
    connection.status = GoogleConnectionStatus.CONNECTED
    connection.last_error_code = ""
    connection.last_error_message = ""
    connection.updated_by = actor
    connection.save(
        update_fields=[
            "google_business_account_name",
            "google_location_id",
            "google_location_display_name",
            "status",
            "last_sync_status",
            "last_synced_booking_url",
            "last_synced_at",
            "last_error_code",
            "last_error_message",
            "updated_by",
            "updated_at",
        ]
    )
    logger.info(
        "google.location_mapped business_id=%s location_id=%s google_location_id=%s",
        business_id,
        location_id,
        match.name,
    )
    return {
        "selected_location": _serialize_location(match),
        "connection": serialize_google_connection(connection),
    }


@transaction.atomic
def connect_google_location(
    *,
    organization,
    business_id,
    location_id,
    actor,
) -> dict:
    """
    Start Google connection.

    - mock: immediate connect (foundation tests)
    - google: return OAuth authorization URL
    """
    business = get_business_for_organization(
        organization=organization,
        business_id=business_id,
    )
    location = get_location_for_business(
        organization=organization,
        business=business,
        location_id=location_id,
    )
    connection = get_or_create_google_connection(
        organization=organization,
        business_id=business_id,
        location_id=location_id,
        actor=actor,
    )
    connection = (
        GoogleBusinessConnection.objects.select_for_update()
        .select_related("business", "location", "organization")
        .get(pk=connection.pk)
    )
    provider = get_google_business_provider()
    connection.provider = provider.name
    connection.updated_by = actor

    if provider.name == "mock" and not provider.supports_oauth_connect():
        pass

    # Mock foundation path: direct connect without browser OAuth.
    if provider.name == "mock" and getattr(settings, "GOOGLE_MOCK_DIRECT_CONNECT", True):
        if connection.status == GoogleConnectionStatus.CONNECTED and connection.google_location_id:
            return serialize_google_connection(connection)
        try:
            snapshot = provider.connect(
                location_id=str(connection.location_id),
                business_id=str(connection.business_id),
            )
        except GoogleBusinessProviderError as exc:
            connection.status = GoogleConnectionStatus.ERROR
            connection.last_error_code = exc.code
            connection.last_error_message = str(exc)
            connection.save(
                update_fields=[
                    "provider",
                    "status",
                    "last_error_code",
                    "last_error_message",
                    "updated_by",
                    "updated_at",
                ]
            )
            raise ValidationError({"status": str(exc), "error_code": exc.code}) from None
        connection.status = GoogleConnectionStatus.CONNECTED
        connection.google_location_id = snapshot.google_location_id
        connection.google_account_id = snapshot.google_account_id
        connection.google_email = snapshot.google_email or "owner@example.com"
        connection.google_business_account_name = (
            connection.google_business_account_name or f"accounts/{snapshot.google_account_id}"
        )
        connection.google_location_display_name = (
            connection.google_location_display_name or snapshot.google_location_id
        )
        connection.connected_at = timezone.now()
        connection.last_error_code = ""
        connection.last_error_message = ""
        connection.save(
            update_fields=[
                "provider",
                "status",
                "google_location_id",
                "google_account_id",
                "google_email",
                "google_business_account_name",
                "google_location_display_name",
                "connected_at",
                "last_error_code",
                "last_error_message",
                "updated_by",
                "updated_at",
            ]
        )
        return serialize_google_connection(connection)

    if not provider.supports_oauth_connect():
        raise ValidationError(
            {
                "status": "Google OAuth is not available.",
                "error_code": "OAUTH_UNAVAILABLE",
            }
        )

    if provider.name == "google":
        require_encryption_configured()

    raw_state = create_oauth_state(
        user=actor,
        organization=organization,
        business=business,
        location=location,
    )
    try:
        authorization_url = provider.get_authorization_url(state=raw_state)
    except GoogleBusinessProviderError as exc:
        raise ValidationError({"status": str(exc), "error_code": exc.code}) from None

    connection.save(update_fields=["provider", "updated_by", "updated_at"])
    payload = serialize_google_connection(connection)
    payload["authorization_url"] = authorization_url
    payload["oauth_started"] = True
    return payload


@transaction.atomic
def complete_google_oauth_callback(
    *,
    code: str | None,
    state: str | None,
    error: str | None = None,
    actor=None,
) -> dict:
    """Exchange OAuth code and persist encrypted credentials."""
    if error:
        logger.info("google.oauth_denied error=%s", error)
        raise ValidationError(
            {
                "status": "Google authorization was denied.",
                "error_code": "ACCESS_DENIED",
            }
        )

    oauth_state = consume_oauth_state(raw_state=state or "", user=actor)
    if actor is not None and oauth_state.user_id != actor.id:
        raise ValidationError({"state": "OAuth state does not match this user."})

    connection = get_or_create_google_connection(
        organization=oauth_state.organization,
        business_id=oauth_state.business_id,
        location_id=oauth_state.location_id,
        actor=oauth_state.user,
    )
    connection = (
        GoogleBusinessConnection.objects.select_for_update()
        .select_related("business", "location", "organization")
        .get(pk=connection.pk)
    )

    provider = get_google_business_provider()
    try:
        bundle = provider.exchange_code(code=(code or "").strip())
    except GoogleBusinessProviderError as exc:
        connection.status = GoogleConnectionStatus.ERROR
        connection.last_error_code = exc.code
        connection.last_error_message = str(exc)
        connection.updated_by = oauth_state.user
        connection.save(
            update_fields=[
                "status",
                "last_error_code",
                "last_error_message",
                "updated_by",
                "updated_at",
            ]
        )
        raise ValidationError(
            {"status": "Google authorization failed.", "error_code": exc.code}
        ) from None

    _store_encrypted_tokens(
        connection,
        access_token=bundle.access_token,
        refresh_token=bundle.refresh_token,
        preserve_existing_refresh=True,
    )
    connection.provider = provider.name
    connection.status = GoogleConnectionStatus.LOCATION_SELECTION_REQUIRED
    connection.google_account_id = bundle.google_account_id or connection.google_account_id
    connection.google_email = bundle.google_email or connection.google_email
    connection.token_expires_at = bundle.expires_at
    connection.scopes = (bundle.scopes or "")[:500]
    connection.connected_at = timezone.now()
    connection.last_error_code = ""
    connection.last_error_message = ""
    connection.updated_by = oauth_state.user
    # OAuth does not auto-map a Google Business location.
    connection.save(
        update_fields=[
            "provider",
            "status",
            "google_account_id",
            "google_email",
            "access_token_encrypted",
            "refresh_token_encrypted",
            "token_expires_at",
            "scopes",
            "connected_at",
            "last_error_code",
            "last_error_message",
            "updated_by",
            "updated_at",
        ]
    )
    logger.info(
        "google.oauth_connected business_id=%s location_id=%s",
        connection.business_id,
        connection.location_id,
    )
    return {
        "connection": serialize_google_connection(connection),
        "redirect_path": (
            f"/owner/onboarding?google=connected"
            f"&business_id={connection.business_id}"
            f"&location_id={connection.location_id}"
        ),
    }


@transaction.atomic
def disconnect_google_location(
    *,
    organization,
    business_id,
    location_id,
    actor,
) -> dict:
    connection = get_or_create_google_connection(
        organization=organization,
        business_id=business_id,
        location_id=location_id,
        actor=actor,
    )
    connection = (
        GoogleBusinessConnection.objects.select_for_update()
        .select_related("business", "location", "organization")
        .get(pk=connection.pk)
    )
    provider = get_google_business_provider()

    # Best-effort revoke; never fail disconnect solely on provider revoke.
    for field in ("access_token_encrypted", "refresh_token_encrypted"):
        try:
            token = decrypt_token(getattr(connection, field))
        except GoogleCryptoError:
            token = ""
        if token:
            try:
                provider.revoke_credentials(token=token)
            except GoogleBusinessProviderError:
                logger.info(
                    "google.revoke_failed business_id=%s location_id=%s",
                    business_id,
                    location_id,
                )

    if connection.google_location_id:
        try:
            provider.disconnect(google_location_id=connection.google_location_id)
        except GoogleBusinessProviderError as exc:
            logger.info(
                "google.disconnect_provider_error business_id=%s location_id=%s code=%s",
                business_id,
                location_id,
                exc.code,
            )

    connection.status = GoogleConnectionStatus.DISCONNECTED
    connection.google_location_id = ""
    connection.google_business_account_name = ""
    connection.google_location_display_name = ""
    # Keep google_account_id/email as safe audit metadata? Spec says clear sensitive
    # tokens; retain safe metadata. Clear account ids for privacy simplicity.
    connection.google_account_id = ""
    connection.google_email = ""
    _clear_encrypted_tokens(connection)
    connection.last_error_code = ""
    connection.last_error_message = ""
    connection.updated_by = actor
    connection.save(
        update_fields=[
            "status",
            "google_location_id",
            "google_business_account_name",
            "google_location_display_name",
            "google_account_id",
            "google_email",
            "access_token_encrypted",
            "refresh_token_encrypted",
            "token_expires_at",
            "scopes",
            "last_error_code",
            "last_error_message",
            "updated_by",
            "updated_at",
        ]
    )
    return serialize_google_connection(connection)


@transaction.atomic
def sync_location_booking_url(
    *,
    organization,
    business_id,
    location_id,
    actor,
) -> dict:
    """Push canonical booking URL to the Google provider when eligible."""
    business = get_business_for_organization(
        organization=organization,
        business_id=business_id,
    )
    location = get_location_for_business(
        organization=organization,
        business=business,
        location_id=location_id,
    )
    connection = get_or_create_google_connection(
        organization=organization,
        business_id=business_id,
        location_id=location_id,
        actor=actor,
    )
    connection = (
        GoogleBusinessConnection.objects.select_for_update()
        .select_related("business", "location", "organization")
        .get(pk=connection.pk)
    )

    urls = resolve_canonical_google_urls(
        organization=organization,
        business=business,
        location=location,
    )
    booking_url = urls.get("booking_url")

    def _fail(*, code: str, message: str, status_value: str | None = None) -> dict:
        connection.last_sync_status = GoogleSyncStatus.FAILED
        if code in {
            "WEBSITE_NOT_PUBLISHED",
            "LOCATION_INACTIVE",
            "BUSINESS_INACTIVE",
            "GOOGLE_LOCATION_SELECTION_REQUIRED",
        }:
            connection.last_sync_status = GoogleSyncStatus.SKIPPED
        connection.last_error_code = code
        connection.last_error_message = message
        update_fields = [
            "last_sync_status",
            "last_error_code",
            "last_error_message",
            "updated_by",
            "updated_at",
        ]
        if status_value:
            connection.status = status_value
            update_fields.insert(0, "status")
        connection.updated_by = actor
        connection.save(update_fields=update_fields)
        return {
            "success": False,
            "status": connection.status,
            "url": booking_url,
            "website_url": urls.get("website_url"),
            "provider_reference": None,
            "error_code": code,
            "message": message,
            "connection": serialize_google_connection(connection, urls=urls),
        }

    if not urls.get("syncable"):
        reason = urls.get("reason") or "NOT_SYNCABLE"
        return _fail(
            code=reason,
            message="Website must be published with a public URL before Google sync.",
        )

    if connection.status == GoogleConnectionStatus.REAUTH_REQUIRED:
        return _fail(
            code="REAUTH_REQUIRED",
            message="Reconnect Google Business Profile before syncing.",
        )

    if connection.status not in {
        GoogleConnectionStatus.CONNECTED,
        GoogleConnectionStatus.LOCATION_SELECTION_REQUIRED,
        GoogleConnectionStatus.ERROR,
        GoogleConnectionStatus.SYNCING,
    }:
        return _fail(
            code="NOT_CONNECTED",
            message="Connect Google Business Profile before syncing the booking URL.",
        )

    if not connection.google_location_id:
        return _fail(
            code="GOOGLE_LOCATION_SELECTION_REQUIRED",
            message="Select a Google Business Profile location before syncing.",
            status_value=GoogleConnectionStatus.LOCATION_SELECTION_REQUIRED,
        )

    if (
        connection.last_sync_status == GoogleSyncStatus.SUCCESS
        and connection.last_synced_booking_url == booking_url
        and connection.status == GoogleConnectionStatus.CONNECTED
    ):
        return {
            "success": True,
            "status": connection.status,
            "url": booking_url,
            "website_url": urls.get("website_url"),
            "provider_reference": None,
            "error_code": None,
            "message": "Booking URL already synced.",
            "connection": serialize_google_connection(connection, urls=urls),
        }

    connection.status = GoogleConnectionStatus.SYNCING
    connection.updated_by = actor
    connection.save(update_fields=["status", "updated_by", "updated_at"])

    access_token = None
    if connection.access_token_encrypted or connection.refresh_token_encrypted:
        try:
            access_token = ensure_valid_access_token(connection)
        except ValidationError as exc:
            detail = getattr(exc, "detail", {}) or {}
            code = "REAUTH_REQUIRED"
            if isinstance(detail, dict) and detail.get("error_code"):
                code = str(detail.get("error_code"))
            return _fail(
                code=code,
                message="Google authorization expired. Reconnect required.",
                status_value=GoogleConnectionStatus.REAUTH_REQUIRED,
            )

    provider = get_google_business_provider()
    try:
        result = provider.update_booking_url(
            google_location_id=connection.google_location_id,
            booking_url=booking_url,
            access_token=access_token,
        )
    except GoogleBusinessProviderError as exc:
        logger.info(
            "google.sync_failed business_id=%s location_id=%s code=%s",
            business_id,
            location_id,
            exc.code,
        )
        status_value = GoogleConnectionStatus.ERROR
        if exc.code == "GOOGLE_LOCATION_SELECTION_REQUIRED":
            status_value = GoogleConnectionStatus.LOCATION_SELECTION_REQUIRED
        elif exc.code == "REAUTH_REQUIRED":
            status_value = GoogleConnectionStatus.REAUTH_REQUIRED
        connection.status = status_value
        connection.last_sync_status = (
            GoogleSyncStatus.SKIPPED
            if exc.code == "GOOGLE_LOCATION_SELECTION_REQUIRED"
            else GoogleSyncStatus.FAILED
        )
        connection.last_error_code = exc.code
        connection.last_error_message = str(exc)
        connection.updated_by = actor
        connection.save(
            update_fields=[
                "status",
                "last_sync_status",
                "last_error_code",
                "last_error_message",
                "updated_by",
                "updated_at",
            ]
        )
        return {
            "success": False,
            "status": connection.status,
            "url": booking_url,
            "website_url": urls.get("website_url"),
            "provider_reference": None,
            "error_code": exc.code,
            "message": str(exc),
            "connection": serialize_google_connection(connection, urls=urls),
        }

    if not result.success:
        return _fail(
            code="PROVIDER_ERROR",
            message=result.message or "Google sync failed.",
            status_value=GoogleConnectionStatus.ERROR,
        )

    connection.status = GoogleConnectionStatus.CONNECTED
    connection.last_synced_booking_url = result.booking_url
    connection.last_sync_status = GoogleSyncStatus.SUCCESS
    connection.last_synced_at = timezone.now()
    connection.last_error_code = ""
    connection.last_error_message = ""
    connection.updated_by = actor
    connection.save(
        update_fields=[
            "status",
            "last_synced_booking_url",
            "last_sync_status",
            "last_synced_at",
            "last_error_code",
            "last_error_message",
            "updated_by",
            "updated_at",
        ]
    )
    return {
        "success": True,
        "status": connection.status,
        "url": result.booking_url,
        "website_url": urls.get("website_url"),
        "provider_reference": result.provider_reference,
        "error_code": None,
        "message": result.message or "Booking URL synced.",
        "connection": serialize_google_connection(connection, urls=urls),
    }
