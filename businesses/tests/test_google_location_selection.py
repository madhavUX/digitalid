"""Google Business Profile location selection + URL sync tests."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from booking.tests.test_booking_api import BookingAPITestCase
from businesses.google_crypto import encrypt_token
from businesses.google_provider import (
    GoogleAccountSummary,
    GoogleLocationSummary,
    reset_mock_google_business_provider,
)
from businesses.google_services import (
    complete_google_oauth_callback,
    create_oauth_state,
    select_google_business_location,
)
from businesses.models import (
    GoogleBusinessConnection,
    GoogleConnectionStatus,
    GoogleSyncStatus,
    WebsiteTemplateKey,
)
from businesses.services import get_business_for_organization
from locations.models import Location
from locations.services import get_location_for_business
from organizations.models import OrganizationMember, Role
from sites.services import booking_url_for_location


@override_settings(
    GOOGLE_BUSINESS_PROVIDER="mock",
    GOOGLE_MOCK_DIRECT_CONNECT=False,
    GOOGLE_TOKEN_ENCRYPTION_KEY="test-google-token-key-32b!!!!!!!!",
    BOOKANYTHING_SITE_DOMAIN="bookanything.in",
    PUBLIC_APP_URL="https://bookanything.in",
)
class GoogleLocationSelectionTests(BookingAPITestCase):
    def setUp(self):
        super().setUp()
        reset_mock_google_business_provider()
        register = self._register("map-owner@example.com", "Map Org")
        self.access = register.data["access"]
        self._auth(self.access)
        self.user = User.objects.get(email="map-owner@example.com")

    def _seed_published(self, *, qc_slug="map-qc", **kwargs):
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

    def _oauth_connect(self, ctx, *, owner_email: str | None = None, code="map-code"):
        email = owner_email or self.user.email
        user = User.objects.get(email=email)
        org = user.active_organization
        business = get_business_for_organization(
            organization=org, business_id=ctx["business"]["id"]
        )
        location = get_location_for_business(
            organization=org, business=business, location_id=ctx["location"]["id"]
        )
        raw = create_oauth_state(user=user, organization=org, business=business, location=location)
        complete_google_oauth_callback(code=code, state=raw, actor=None)
        self._auth(ctx["token"])
        return GoogleBusinessConnection.objects.get(location_id=ctx["location"]["id"])

    def test_list_accounts_and_auto_select_single(self):
        ctx = self._seed_published(
            owner_email="single-acct@example.com",
            org_name="Single Acct",
            qc_slug="single-acct",
        )
        provider = reset_mock_google_business_provider()
        provider._accounts = [
            GoogleAccountSummary(
                name="accounts/only",
                display_name="Only Account",
                account_type="PERSONAL",
            )
        ]
        provider._locations_by_account = {
            "accounts/only": [
                GoogleLocationSummary(
                    name="accounts/only/locations/one",
                    title="Only Salon",
                    address="1 Main",
                )
            ]
        }
        provider._rebuild_location_catalog()
        self._oauth_connect(ctx, owner_email="single-acct@example.com", code="single")

        listed = self.client.get(
            reverse(
                "business-location-google-accounts",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            )
        )
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual(listed.data["count"], 1)
        self.assertTrue(listed.data["auto_selected"])
        self.assertEqual(listed.data["selected_account_name"], "accounts/only")
        self.assertNotIn("access_token", listed.data)
        self.assertNotIn("refresh_token", str(listed.data))

    def test_multiple_accounts_require_explicit_selection(self):
        ctx = self._seed_published(
            owner_email="multi-acct@example.com",
            org_name="Multi Acct",
            qc_slug="multi-acct",
        )
        self._oauth_connect(ctx, owner_email="multi-acct@example.com", code="multi")
        listed = self.client.get(
            reverse(
                "business-location-google-accounts",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            )
        )
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(listed.data["count"], 2)
        self.assertTrue(listed.data["account_selection_required"])

        selected = self.client.post(
            reverse(
                "business-location-google-accounts",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            ),
            {"google_account_name": "accounts/mock-primary"},
            format="json",
        )
        self.assertEqual(selected.status_code, status.HTTP_200_OK)
        self.assertEqual(
            selected.data["connection"]["google_business_account"]["name"],
            "accounts/mock-primary",
        )

    def test_location_selection_and_sync(self):
        ctx = self._seed_published(
            owner_email="map-sync@example.com",
            org_name="Map Sync",
            qc_slug="map-sync",
        )
        self._oauth_connect(ctx, owner_email="map-sync@example.com", code="syncmap")
        self.client.post(
            reverse(
                "business-location-google-accounts",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            ),
            {"google_account_name": "accounts/mock-primary"},
            format="json",
        )
        locations = self.client.get(
            reverse(
                "business-location-google-locations",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            )
            + "?account_name=accounts/mock-primary"
        )
        self.assertEqual(locations.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(locations.data["count"], 1)
        google_loc = locations.data["locations"][0]["id"]

        mapped = self.client.post(
            reverse(
                "business-location-google-select-location",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            ),
            {
                "google_location_id": google_loc,
                "google_account_name": "accounts/mock-primary",
            },
            format="json",
        )
        self.assertEqual(mapped.status_code, status.HTTP_200_OK)
        self.assertTrue(mapped.data["connection"]["location_selected"])
        self.assertEqual(mapped.data["connection"]["status"], GoogleConnectionStatus.CONNECTED)
        self.assertNotIn("access_token", mapped.data["connection"])

        provider = reset_mock_google_business_provider()
        # Keep mapped location known to the mock after reset.
        conn = GoogleBusinessConnection.objects.get(location_id=ctx["location"]["id"])
        provider._location_catalog[conn.google_location_id] = GoogleLocationSummary(
            name=conn.google_location_id,
            title=conn.google_location_display_name or "Mapped",
        )

        with patch(
            "businesses.google_services.get_google_business_provider",
            return_value=provider,
        ):
            synced = self.client.post(
                reverse(
                    "business-location-google-sync-url",
                    kwargs={
                        "business_id": ctx["business"]["id"],
                        "location_id": ctx["location"]["id"],
                    },
                )
            )
        self.assertEqual(synced.status_code, status.HTTP_200_OK)
        self.assertTrue(synced.data["success"])
        expected = booking_url_for_location(Location.objects.get(pk=ctx["location"]["id"]))
        self.assertEqual(synced.data["url"], expected)
        self.assertEqual(provider.updated_urls[-1][1], expected)
        conn.refresh_from_db()
        self.assertEqual(conn.last_sync_status, GoogleSyncStatus.SUCCESS)

        with patch(
            "businesses.google_services.get_google_business_provider",
            return_value=provider,
        ):
            again = self.client.post(
                reverse(
                    "business-location-google-sync-url",
                    kwargs={
                        "business_id": ctx["business"]["id"],
                        "location_id": ctx["location"]["id"],
                    },
                )
            )
        self.assertEqual(again.status_code, status.HTTP_200_OK)
        self.assertIn("already synced", again.data["message"].lower())
        self.assertEqual(len(provider.updated_urls), 1)

    def test_invalid_location_rejected(self):
        ctx = self._seed_published(
            owner_email="bad-loc@example.com",
            org_name="Bad Loc",
            qc_slug="bad-loc",
        )
        self._oauth_connect(ctx, owner_email="bad-loc@example.com", code="badloc")
        self.client.post(
            reverse(
                "business-location-google-accounts",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            ),
            {"google_account_name": "accounts/mock-primary"},
            format="json",
        )
        rejected = self.client.post(
            reverse(
                "business-location-google-select-location",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            ),
            {"google_location_id": "accounts/mock-primary/locations/does-not-exist"},
            format="json",
        )
        self.assertEqual(rejected.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cross_tenant_select_404(self):
        ctx_a = self._seed_published(
            owner_email="tenant-a@example.com",
            org_name="Tenant A Map",
            qc_slug="tenant-a-map",
        )
        self._oauth_connect(ctx_a, owner_email="tenant-a@example.com", code="tenanta")
        register_b = self._register("tenant-b@example.com", "Tenant B Map")
        other = APIClient()
        other.credentials(HTTP_AUTHORIZATION=f"Bearer {register_b.data['access']}")
        missing = other.post(
            reverse(
                "business-location-google-select-location",
                kwargs={
                    "business_id": ctx_a["business"]["id"],
                    "location_id": ctx_a["location"]["id"],
                },
            ),
            {"google_location_id": "accounts/mock-primary/locations/loc-main"},
            format="json",
        )
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)

    def test_manager_can_list_staff_cannot_select(self):
        ctx = self._seed_published(
            owner_email="perm-map@example.com",
            org_name="Perm Map",
            qc_slug="perm-map",
        )
        owner = User.objects.get(email="perm-map@example.com")
        self._oauth_connect(ctx, owner_email="perm-map@example.com", code="perm")
        manager = User.objects.create_user(
            email="map-manager@example.com",
            password="StrongPass123",
            active_organization=owner.active_organization,
        )
        OrganizationMember.objects.create(
            organization=owner.active_organization,
            user=manager,
            role=Role.MANAGER,
        )
        staff = User.objects.create_user(
            email="map-staff@example.com",
            password="StrongPass123",
            active_organization=owner.active_organization,
        )
        OrganizationMember.objects.create(
            organization=owner.active_organization,
            user=staff,
            role=Role.STAFF,
        )

        mgr_login = self.client.post(
            reverse("auth-login"),
            {"email": "map-manager@example.com", "password": "StrongPass123"},
            format="json",
        )
        mgr = APIClient()
        mgr.credentials(HTTP_AUTHORIZATION=f"Bearer {mgr_login.data['access']}")
        listed = mgr.get(
            reverse(
                "business-location-google-accounts",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            )
        )
        self.assertEqual(listed.status_code, status.HTTP_200_OK)

        staff_login = self.client.post(
            reverse("auth-login"),
            {"email": "map-staff@example.com", "password": "StrongPass123"},
            format="json",
        )
        staff_client = APIClient()
        staff_client.credentials(HTTP_AUTHORIZATION=f"Bearer {staff_login.data['access']}")
        denied = staff_client.post(
            reverse(
                "business-location-google-select-location",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            ),
            {"google_location_id": "accounts/mock-primary/locations/loc-main"},
            format="json",
        )
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

    def test_unpublished_blocks_sync_after_mapping(self):
        ctx = self._seed_published(
            owner_email="unpub-map@example.com",
            org_name="Unpub Map",
            qc_slug="unpub-map",
        )
        conn = self._oauth_connect(ctx, owner_email="unpub-map@example.com", code="unpub")
        org = conn.organization
        business = conn.business
        select_google_business_location(
            organization=org,
            business_id=business.id,
            location_id=conn.location_id,
            actor=User.objects.get(email="unpub-map@example.com"),
            google_location_id="accounts/mock-primary/locations/loc-main",
            google_account_name="accounts/mock-primary",
        )
        self.client.post(
            reverse("business-website-unpublish", kwargs={"business_id": ctx["business"]["id"]})
            + f"?location_id={ctx['location']['id']}",
        )
        blocked = self.client.post(
            reverse(
                "business-location-google-sync-url",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            )
        )
        self.assertEqual(blocked.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(blocked.data["error_code"], "WEBSITE_NOT_PUBLISHED")

    def test_reauth_required_on_revoked_token(self):
        ctx = self._seed_published(
            owner_email="reauth-map@example.com",
            org_name="Reauth Map",
            qc_slug="reauth-map",
        )
        conn = self._oauth_connect(ctx, owner_email="reauth-map@example.com", code="reauth")
        conn.access_token_encrypted = encrypt_token("expired-access")
        conn.refresh_token_encrypted = encrypt_token("revoked-refresh")
        conn.token_expires_at = timezone.now() - timedelta(minutes=5)
        conn.save(
            update_fields=[
                "access_token_encrypted",
                "refresh_token_encrypted",
                "token_expires_at",
                "updated_at",
            ]
        )
        listed = self.client.get(
            reverse(
                "business-location-google-accounts",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            )
        )
        self.assertEqual(listed.status_code, status.HTTP_400_BAD_REQUEST)
        conn.refresh_from_db()
        self.assertEqual(conn.status, GoogleConnectionStatus.REAUTH_REQUIRED)
        self.assertNotIn("revoked-refresh", str(listed.data))
