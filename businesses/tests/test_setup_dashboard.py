"""Business setup status + dashboard API tests."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from booking.tests.test_booking_api import KOLKATA, BookingAPITestCase
from organizations.models import OrganizationMember, Role


class BusinessSetupDashboardTests(BookingAPITestCase):
    def setUp(self):
        super().setUp()
        register = self._register("dash-owner@example.com", "Dash Org")
        self.access = register.data["access"]
        self._auth(self.access)

    def _setup_url(self, business_id, location_id=None):
        url = reverse("business-setup", kwargs={"business_id": business_id})
        if location_id:
            return f"{url}?location_id={location_id}"
        return url

    def _dashboard_url(self, business_id, location_id=None):
        url = reverse("business-dashboard", kwargs={"business_id": business_id})
        if location_id:
            return f"{url}?location_id={location_id}"
        return url

    def test_incomplete_setup_progress(self):
        business = self._create_business("Bare Salon")
        response = self.client.get(self._setup_url(business["id"]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["ready"])
        self.assertTrue(response.data["steps"]["business"])
        self.assertFalse(response.data["steps"]["location"])
        self.assertIn("Add at least one location.", response.data["blocking_reasons"])

    def test_ready_after_full_seed_and_quickcard_publish(self):
        ctx = self._seed_bookable_monday(
            owner_email="ready-owner@example.com",
            org_name="Ready Org",
        )
        # Re-auth as seeded owner
        self._auth(ctx["token"])
        setup = self.client.get(self._setup_url(ctx["business"]["id"], ctx["location"]["id"]))
        self.assertEqual(setup.status_code, status.HTTP_200_OK)
        self.assertTrue(setup.data["steps"]["services"])
        self.assertTrue(setup.data["steps"]["staff"])
        self.assertTrue(setup.data["steps"]["availability"])
        self.assertFalse(setup.data["steps"]["quickcard"])

        created = self.client.post(
            reverse(
                "quickcard-detail",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            ),
            {"slug": "ready-salon", "headline": "Hello"},
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        published = self.client.post(
            reverse(
                "quickcard-publish",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            )
        )
        self.assertEqual(published.status_code, status.HTTP_200_OK)
        ready = self.client.get(self._setup_url(ctx["business"]["id"], ctx["location"]["id"]))
        self.assertTrue(ready.data["ready"])
        self.assertEqual(ready.data["progress"], 100)
        self.assertEqual(ready.data["quickcard"]["slug"], "ready-salon")

    def test_staff_forbidden(self):
        business = self._create_business()
        owner = User.objects.get(email="dash-owner@example.com")
        staff_user = User.objects.create_user(
            email="dash-staff@example.com",
            password="StrongPass123",
            active_organization=owner.active_organization,
        )
        OrganizationMember.objects.create(
            organization=owner.active_organization,
            user=staff_user,
            role=Role.STAFF,
        )
        login = self.client.post(
            reverse("auth-login"),
            {"email": "dash-staff@example.com", "password": "StrongPass123"},
            format="json",
        )
        staff_client = APIClient()
        staff_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        response = staff_client.get(self._setup_url(business["id"]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        dash = staff_client.get(self._dashboard_url(business["id"]))
        self.assertEqual(dash.status_code, status.HTTP_403_FORBIDDEN)

    def test_manager_allowed(self):
        business = self._create_business()
        owner = User.objects.get(email="dash-owner@example.com")
        manager = User.objects.create_user(
            email="dash-manager@example.com",
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
            {"email": "dash-manager@example.com", "password": "StrongPass123"},
            format="json",
        )
        mgr = APIClient()
        mgr.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        response = mgr.get(self._setup_url(business["id"]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_cross_business_404(self):
        self._create_business("Biz A")
        other = self._register("other-owner@example.com", "Other Org")
        self._auth(other.data["access"])
        other_biz = self._create_business("Biz B")
        self._auth(self.access)
        response = self.client.get(self._setup_url(other_biz["id"]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_dashboard_counts_and_no_manage_token(self):
        ctx = self._seed_bookable_monday(
            owner_email="dash2@example.com",
            org_name="Dash2 Org",
        )
        self._auth(ctx["token"])
        monday = ctx["monday"]
        start = datetime.combine(monday, time(10, 0), tzinfo=KOLKATA)
        # Create appointment for "today" relative to monday if monday is upcoming;
        # force by using starts_at on monday and pass now into service via URL not available —
        # create appointment and check list shape instead when monday == today locally.
        create = self.client.post(
            reverse("appointment-list", kwargs={"business_id": ctx["business"]["id"]}),
            {
                "location_id": ctx["location"]["id"],
                "customer_id": ctx["customer"]["id"],
                "service_id": ctx["service"]["id"],
                "staff_id": ctx["staff"]["id"],
                "starts_at": start.isoformat(),
            },
            format="json",
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED)

        # Publish quickcard so setup ready fields exist
        self.client.post(
            reverse(
                "quickcard-detail",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            ),
            {"slug": "dash-salon"},
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

        from businesses.setup_services import get_business_dashboard

        payload = get_business_dashboard(
            organization=User.objects.get(email="dash2@example.com").active_organization,
            business_id=ctx["business"]["id"],
            location_id=ctx["location"]["id"],
            now=start + timedelta(minutes=1),
        )
        self.assertGreaterEqual(payload["today"]["bookings"], 1)
        self.assertTrue(payload["appointments"])
        blob = str(payload)
        self.assertNotIn("manage_token", blob)
        self.assertNotIn("token_hash", blob)
        self.assertIn("customer_name", payload["appointments"][0])
        self.assertNotIn("phone", blob.lower())

    def test_multi_location_scoping(self):
        ctx = self._seed_bookable_monday(
            owner_email="multi@example.com",
            org_name="Multi Org",
        )
        self._auth(ctx["token"])
        loc_b = self._create_location(ctx["business"]["id"], name="Uptown")
        setup_a = self.client.get(self._setup_url(ctx["business"]["id"], ctx["location"]["id"]))
        setup_b = self.client.get(self._setup_url(ctx["business"]["id"], loc_b["id"]))
        self.assertTrue(setup_a.data["steps"]["services"])
        self.assertFalse(setup_b.data["steps"]["services"])
