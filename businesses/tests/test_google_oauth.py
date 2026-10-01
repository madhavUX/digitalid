"""Google OAuth, encryption, and provider boundary tests."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from accounts.models import User
from booking.tests.test_booking_api import BookingAPITestCase
from businesses.google_crypto import (
    GoogleCryptoError,
    decrypt_token,
    encrypt_token,
)
from businesses.google_provider import (
    OAuthTokenBundle,
    reset_mock_google_business_provider,
)
from businesses.google_services import (
    complete_google_oauth_callback,
    consume_oauth_state,
    create_oauth_state,
)
from businesses.models import (
    GoogleBusinessConnection,
    GoogleConnectionStatus,
    WebsiteTemplateKey,
)
from businesses.services import get_business_for_organization
from locations.services import get_location_for_business


@override_settings(GOOGLE_TOKEN_ENCRYPTION_KEY="test-google-token-key-32b!!!!!!!!")
class GoogleCryptoTests(SimpleTestCase):
    def test_round_trip_and_unique_ciphertext(self):
        a = encrypt_token("secret-token-value")
        b = encrypt_token("secret-token-value")
        self.assertTrue(a.startswith("v1:"))
        self.assertNotEqual(a, b)
        self.assertEqual(decrypt_token(a), "secret-token-value")
        self.assertEqual(decrypt_token(b), "secret-token-value")

    def test_empty_and_invalid(self):
        self.assertEqual(encrypt_token(""), "")
        self.assertEqual(decrypt_token(""), "")
        with self.assertRaises(GoogleCryptoError):
            decrypt_token("not-valid")
        with self.assertRaises(GoogleCryptoError):
            decrypt_token("v1:@@@@")

    @override_settings(GOOGLE_TOKEN_ENCRYPTION_KEY="other-key-entirely")
    def test_wrong_key_rejected(self):
        with override_settings(GOOGLE_TOKEN_ENCRYPTION_KEY="test-google-token-key-32b!!!!!!!!"):
            cipher = encrypt_token("hello")
        with self.assertRaises(GoogleCryptoError):
            decrypt_token(cipher)


@override_settings(
    GOOGLE_BUSINESS_PROVIDER="mock",
    GOOGLE_MOCK_DIRECT_CONNECT=True,
    GOOGLE_TOKEN_ENCRYPTION_KEY="test-google-token-key-32b!!!!!!!!",
    BOOKANYTHING_SITE_DOMAIN="bookanything.in",
    PUBLIC_APP_URL="https://bookanything.in",
)
class GoogleOAuthFoundationTests(BookingAPITestCase):
    def setUp(self):
        super().setUp()
        reset_mock_google_business_provider()
        register = self._register("oauth-owner@example.com", "OAuth Org")
        self.access = register.data["access"]
        self._auth(self.access)
        self.user = User.objects.get(email="oauth-owner@example.com")

    def _seed_published(self, *, qc_slug="oauth-qc", **kwargs):
        ctx = self._seed_bookable_monday(**kwargs)
        self._auth(ctx["token"])
        self.client.post(
            reverse(
                "quickcard-detail",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            ),
            {"slug": qc_slug, "headline": "Hello"},
            format="json",
        )
        self.client.post(
            reverse(
                "quickcard-publish",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            )
        )
        self.client.patch(
            reverse("business-launch-profile", kwargs={"business_id": ctx["business"]["id"]})
            + f"?location_id={ctx['location']['id']}",
            {"template_key": WebsiteTemplateKey.SALON_MODERN},
            format="json",
        )
        published = self.client.post(
            reverse("business-website-publish", kwargs={"business_id": ctx["business"]["id"]})
            + f"?location_id={ctx['location']['id']}",
        )
        self.assertEqual(published.status_code, status.HTTP_200_OK)
        return ctx

    def test_oauth_state_lifecycle(self):
        ctx = self._seed_published(
            owner_email="state-owner@example.com",
            org_name="State Org",
            qc_slug="state-qc",
        )
        user = User.objects.get(email="state-owner@example.com")
        org = user.active_organization
        business = get_business_for_organization(
            organization=org, business_id=ctx["business"]["id"]
        )
        location = get_location_for_business(
            organization=org, business=business, location_id=ctx["location"]["id"]
        )
        raw = create_oauth_state(user=user, organization=org, business=business, location=location)
        row = consume_oauth_state(raw_state=raw, user=user)
        self.assertIsNotNone(row.used_at)
        with self.assertRaises(ValidationError):
            consume_oauth_state(raw_state=raw, user=user)
        with self.assertRaises(ValidationError):
            consume_oauth_state(raw_state="invalid", user=user)

        raw2 = create_oauth_state(user=user, organization=org, business=business, location=location)
        from businesses.google_services import _hash_state
        from businesses.models import GoogleOAuthState

        GoogleOAuthState.objects.filter(state_hash=_hash_state(raw2)).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        with self.assertRaises(ValidationError):
            consume_oauth_state(raw_state=raw2, user=user)

    @override_settings(GOOGLE_MOCK_DIRECT_CONNECT=False)
    def test_connect_returns_authorization_url(self):
        ctx = self._seed_published(
            owner_email="authurl@example.com",
            org_name="Auth URL Org",
            qc_slug="authurl-qc",
        )
        started = self.client.post(
            reverse(
                "business-location-google",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            )
        )
        self.assertEqual(started.status_code, status.HTTP_200_OK)
        self.assertTrue(started.data.get("authorization_url"))
        self.assertIn("state=", started.data["authorization_url"])

    def test_oauth_callback_encrypts_tokens(self):
        ctx = self._seed_published(
            owner_email="cb@example.com",
            org_name="CB Org",
            qc_slug="cb-qc",
        )
        user = User.objects.get(email="cb@example.com")
        org = user.active_organization
        business = get_business_for_organization(
            organization=org, business_id=ctx["business"]["id"]
        )
        location = get_location_for_business(
            organization=org, business=business, location_id=ctx["location"]["id"]
        )
        raw = create_oauth_state(user=user, organization=org, business=business, location=location)
        result = complete_google_oauth_callback(code="good-code", state=raw, actor=None)
        conn = GoogleBusinessConnection.objects.get(location_id=ctx["location"]["id"])
        self.assertEqual(conn.status, GoogleConnectionStatus.LOCATION_SELECTION_REQUIRED)
        self.assertTrue(conn.access_token_encrypted.startswith("v1:"))
        self.assertTrue(conn.refresh_token_encrypted.startswith("v1:"))
        self.assertNotIn("mock-access", str(conn))
        self.assertEqual(decrypt_token(conn.access_token_encrypted), "mock-access-good-code")
        payload = result["connection"]
        self.assertNotIn("access_token", payload)
        self.assertNotIn("refresh_token", payload)
        self.assertEqual(payload["google_account"]["email"], "owner@example.com")

        # Preserve refresh when Google omits it on reconnect
        old_refresh = conn.refresh_token_encrypted
        raw2 = create_oauth_state(user=user, organization=org, business=business, location=location)
        provider = reset_mock_google_business_provider()

        def exchange_without_refresh(*, code: str):
            return OAuthTokenBundle(
                access_token="mock-access-2",
                refresh_token=None,
                expires_at=timezone.now() + timedelta(hours=1),
                scopes="https://www.googleapis.com/auth/business.manage",
                google_account_id="acct",
                google_email="owner@example.com",
            )

        with patch.object(provider, "exchange_code", side_effect=exchange_without_refresh):
            with patch(
                "businesses.google_services.get_google_business_provider",
                return_value=provider,
            ):
                complete_google_oauth_callback(code="again", state=raw2, actor=None)
        conn.refresh_from_db()
        self.assertEqual(conn.refresh_token_encrypted, old_refresh)

    def test_callback_http_redirect(self):
        ctx = self._seed_published(
            owner_email="redir@example.com",
            org_name="Redir Org",
            qc_slug="redir-qc",
        )
        user = User.objects.get(email="redir@example.com")
        org = user.active_organization
        business = get_business_for_organization(
            organization=org, business_id=ctx["business"]["id"]
        )
        location = get_location_for_business(
            organization=org, business=business, location_id=ctx["location"]["id"]
        )
        raw = create_oauth_state(user=user, organization=org, business=business, location=location)
        anon = APIClient()
        response = anon.get(
            reverse("business-google-oauth-callback"),
            {"code": "ok", "state": raw},
        )
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn("google=connected", response["Location"])

    def test_status_never_exposes_tokens(self):
        ctx = self._seed_published(
            owner_email="safe@example.com",
            org_name="Safe Org",
            qc_slug="safe-qc",
        )
        self.client.post(
            reverse(
                "business-location-google",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            )
        )
        status_view = self.client.get(
            reverse(
                "business-location-google",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            )
        )
        self.assertEqual(status_view.status_code, status.HTTP_200_OK)
        blob = str(status_view.data)
        self.assertNotIn("access_token", blob)
        self.assertNotIn("refresh_token", blob)
        self.assertNotIn("encrypted", blob)

    @override_settings(
        GOOGLE_BUSINESS_PROVIDER="google",
        GOOGLE_BUSINESS_ENABLED=True,
        GOOGLE_OAUTH_CLIENT_ID="",
        GOOGLE_OAUTH_CLIENT_SECRET="",
        GOOGLE_TOKEN_ENCRYPTION_KEY="test-google-token-key-32b!!!!!!!!",
    )
    def test_google_mode_missing_config(self):
        ctx = self._seed_published(
            owner_email="cfg@example.com",
            org_name="Cfg Org",
            qc_slug="cfg-qc",
        )
        rejected = self.client.post(
            reverse(
                "business-location-google",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            )
        )
        self.assertEqual(rejected.status_code, status.HTTP_400_BAD_REQUEST)
