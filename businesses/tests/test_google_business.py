"""Google Business Profile integration foundation tests."""

from __future__ import annotations

from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from booking.tests.test_booking_api import BookingAPITestCase
from businesses.google_provider import (
    GoogleBusinessProviderError,
    GoogleProfileSnapshot,
    MockGoogleBusinessProvider,
    reset_mock_google_business_provider,
)
from businesses.google_services import resolve_canonical_google_urls, sync_location_booking_url
from businesses.models import (
    Business,
    GoogleBusinessConnection,
    GoogleConnectionStatus,
    GoogleSyncStatus,
    WebsiteTemplateKey,
)
from locations.models import Location
from organizations.models import OrganizationMember, Role
from sites.services import booking_url_for_location


@override_settings(
    GOOGLE_BUSINESS_PROVIDER="mock",
    BOOKANYTHING_SITE_DOMAIN="bookanything.in",
    PUBLIC_APP_URL="https://bookanything.in",
)
class GoogleBusinessFoundationTests(BookingAPITestCase):
    def setUp(self):
        super().setUp()
        reset_mock_google_business_provider()
        register = self._register("gbp-owner@example.com", "GBP Org")
        self.access = register.data["access"]
        self._auth(self.access)

    def _seed_published(self, *, qc_slug="gbp-salon", **kwargs):
        ctx = self._seed_bookable_monday(**kwargs)
        self._auth(ctx["token"])
        created = self.client.post(
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
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
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
        ctx["website"] = published.data
        return ctx

    def test_resolve_urls_published(self):
        ctx = self._seed_published(
            owner_email="gbp-url@example.com",
            org_name="GBP URL",
            qc_slug="gbp-url",
        )
        biz = Business.objects.get(pk=ctx["business"]["id"])
        loc = Location.objects.get(pk=ctx["location"]["id"])
        urls = resolve_canonical_google_urls(
            organization=biz.organization,
            business=biz,
            location=loc,
        )
        self.assertTrue(urls["syncable"])
        self.assertEqual(urls["booking_url"], booking_url_for_location(loc))
        self.assertTrue(urls["website_url"].startswith("https://"))
        self.assertIn(".bookanything.in", urls["website_url"])

    def test_resolve_urls_unpublished(self):
        ctx = self._seed_bookable_monday(
            owner_email="gbp-unpub@example.com",
            org_name="GBP Unpub",
        )
        self._auth(ctx["token"])
        biz = Business.objects.get(pk=ctx["business"]["id"])
        loc = Location.objects.get(pk=ctx["location"]["id"])
        urls = resolve_canonical_google_urls(
            organization=biz.organization,
            business=biz,
            location=loc,
        )
        self.assertFalse(urls["syncable"])
        self.assertEqual(urls["reason"], "WEBSITE_NOT_PUBLISHED")

    def test_resolve_urls_inactive_location(self):
        ctx = self._seed_published(
            owner_email="gbp-inactive@example.com",
            org_name="GBP Inactive",
            qc_slug="gbp-inactive",
        )
        biz = Business.objects.get(pk=ctx["business"]["id"])
        loc = Location.objects.get(pk=ctx["location"]["id"])
        loc.is_active = False
        loc.save(update_fields=["is_active", "updated_at"])
        urls = resolve_canonical_google_urls(
            organization=biz.organization,
            business=biz,
            location=loc,
        )
        self.assertFalse(urls["syncable"])
        self.assertEqual(urls["reason"], "LOCATION_INACTIVE")

    def test_get_status_manager_allowed_staff_denied(self):
        ctx = self._seed_published(
            owner_email="gbp-perm@example.com",
            org_name="GBP Perm",
            qc_slug="gbp-perm",
        )
        owner = User.objects.get(email="gbp-perm@example.com")
        manager = User.objects.create_user(
            email="gbp-manager@example.com",
            password="StrongPass123",
            active_organization=owner.active_organization,
        )
        OrganizationMember.objects.create(
            organization=owner.active_organization,
            user=manager,
            role=Role.MANAGER,
        )
        staff = User.objects.create_user(
            email="gbp-staff@example.com",
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
            {"email": "gbp-manager@example.com", "password": "StrongPass123"},
            format="json",
        )
        mgr = APIClient()
        mgr.credentials(HTTP_AUTHORIZATION=f"Bearer {mgr_login.data['access']}")
        status_ok = mgr.get(
            reverse(
                "business-location-google",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            )
        )
        self.assertEqual(status_ok.status_code, status.HTTP_200_OK)
        self.assertEqual(status_ok.data["status"], GoogleConnectionStatus.NOT_CONNECTED)
        self.assertTrue(status_ok.data["oauth_available"])

        staff_login = self.client.post(
            reverse("auth-login"),
            {"email": "gbp-staff@example.com", "password": "StrongPass123"},
            format="json",
        )
        staff_client = APIClient()
        staff_client.credentials(HTTP_AUTHORIZATION=f"Bearer {staff_login.data['access']}")
        denied = staff_client.get(
            reverse(
                "business-location-google",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            )
        )
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_tenant_404(self):
        ctx_a = self._seed_published(
            owner_email="gbp-a@example.com",
            org_name="GBP A",
            qc_slug="gbp-a",
        )
        register_b = self._register("gbp-b2@example.com", "GBP B2")
        other = APIClient()
        other.credentials(HTTP_AUTHORIZATION=f"Bearer {register_b.data['access']}")
        missing = other.get(
            reverse(
                "business-location-google",
                kwargs={
                    "business_id": ctx_a["business"]["id"],
                    "location_id": ctx_a["location"]["id"],
                },
            )
        )
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)

    def test_sync_mock_provider_and_idempotent(self):
        ctx = self._seed_published(
            owner_email="gbp-sync@example.com",
            org_name="GBP Sync",
            qc_slug="gbp-sync",
        )
        unsynced = self.client.post(
            reverse(
                "business-location-google-sync-url",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            )
        )
        self.assertEqual(unsynced.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(unsynced.data["error_code"], "NOT_CONNECTED")

        connected = self.client.post(
            reverse(
                "business-location-google",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            )
        )
        self.assertEqual(connected.status_code, status.HTTP_200_OK)
        self.assertEqual(connected.data["status"], GoogleConnectionStatus.CONNECTED)

        provider = reset_mock_google_business_provider()
        conn = GoogleBusinessConnection.objects.get(location_id=ctx["location"]["id"])
        provider._profiles[conn.google_location_id] = GoogleProfileSnapshot(
            google_location_id=conn.google_location_id,
            google_account_id=conn.google_account_id or "mock-acct",
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
        expected_url = booking_url_for_location(Location.objects.get(pk=ctx["location"]["id"]))
        self.assertEqual(synced.data["url"], expected_url)
        self.assertTrue(synced.data["provider_reference"])
        self.assertEqual(provider.updated_urls[-1][1], expected_url)

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
        self.assertTrue(again.data["success"])
        self.assertIn("already synced", again.data["message"].lower())
        self.assertEqual(len(provider.updated_urls), 1)

    def test_unpublish_blocks_sync(self):
        ctx = self._seed_published(
            owner_email="gbp-block@example.com",
            org_name="GBP Block",
            qc_slug="gbp-block",
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

    def test_provider_error_recorded(self):
        ctx = self._seed_published(
            owner_email="gbp-err@example.com",
            org_name="GBP Err",
            qc_slug="gbp-err",
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

        class BoomProvider(MockGoogleBusinessProvider):
            def update_booking_url(self, *, google_location_id, booking_url, access_token=None):
                raise GoogleBusinessProviderError("boom", code="PROVIDER_DOWN")

        boom = BoomProvider()
        conn = GoogleBusinessConnection.objects.get(location_id=ctx["location"]["id"])
        boom._profiles[conn.google_location_id] = GoogleProfileSnapshot(
            google_location_id=conn.google_location_id,
            google_account_id=conn.google_account_id or "mock-acct",
        )

        with patch(
            "businesses.google_services.get_google_business_provider",
            return_value=boom,
        ):
            result = sync_location_booking_url(
                organization=conn.organization,
                business_id=conn.business_id,
                location_id=conn.location_id,
                actor=User.objects.get(email="gbp-err@example.com"),
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "PROVIDER_DOWN")
        conn.refresh_from_db()
        self.assertEqual(conn.status, GoogleConnectionStatus.ERROR)
        self.assertEqual(conn.last_sync_status, GoogleSyncStatus.FAILED)

    def test_manager_cannot_sync(self):
        ctx = self._seed_published(
            owner_email="gbp-mgr-sync@example.com",
            org_name="GBP Mgr Sync",
            qc_slug="gbp-mgr-sync",
        )
        owner = User.objects.get(email="gbp-mgr-sync@example.com")
        manager = User.objects.create_user(
            email="gbp-mgr2@example.com",
            password="StrongPass123",
            active_organization=owner.active_organization,
        )
        OrganizationMember.objects.create(
            organization=owner.active_organization,
            user=manager,
            role=Role.MANAGER,
        )
        login = self.client.post(
            reverse("auth-login"),
            {"email": "gbp-mgr2@example.com", "password": "StrongPass123"},
            format="json",
        )
        mgr = APIClient()
        mgr.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        denied = mgr.post(
            reverse(
                "business-location-google-sync-url",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            )
        )
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

    @override_settings(GOOGLE_BUSINESS_PROVIDER="deferred")
    def test_deferred_provider_rejects_connect(self):
        ctx = self._seed_published(
            owner_email="gbp-def@example.com",
            org_name="GBP Def",
            qc_slug="gbp-def",
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
