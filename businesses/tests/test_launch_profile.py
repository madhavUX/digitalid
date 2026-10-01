"""Business launch profile API + readiness tests."""

from __future__ import annotations

from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from booking.tests.test_booking_api import BookingAPITestCase
from businesses.models import (
    BusinessLaunchProfile,
    DomainStatus,
    GoogleBusinessStatus,
    LaunchStatus,
    WebsiteTemplateKey,
    WhatsAppSetupStatus,
)
from organizations.models import OrganizationMember, Role


class BusinessLaunchProfileTests(BookingAPITestCase):
    def setUp(self):
        super().setUp()
        register = self._register("launch-owner@example.com", "Launch Org")
        self.access = register.data["access"]
        self._auth(self.access)

    def _url(self, business_id, location_id=None):
        url = reverse("business-launch-profile", kwargs={"business_id": business_id})
        if location_id:
            return f"{url}?location_id={location_id}"
        return url

    def _seed_with_quickcard(self, **kwargs):
        qc_slug = kwargs.pop("qc_slug", "launch-salon")
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
        return ctx

    def test_create_and_retrieve_launch_profile(self):
        business = self._create_business("Launch Salon")
        location = self._create_location(business["id"], name="Main")
        created = self.client.post(
            self._url(business["id"]),
            {"location_id": location["id"], "template_key": WebsiteTemplateKey.SALON_MODERN},
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(created.data["profile"]["template_key"], WebsiteTemplateKey.SALON_MODERN)
        self.assertEqual(created.data["profile"]["domain_status"], DomainStatus.SUBDOMAIN_ACTIVE)
        self.assertTrue(created.data["profile"]["subdomain"])
        self.assertIn("bookanything.in", created.data["profile"]["subdomain_hostname"])

        fetched = self.client.get(self._url(business["id"], location["id"]))
        self.assertEqual(fetched.status_code, status.HTTP_200_OK)
        self.assertEqual(fetched.data["template"]["key"], WebsiteTemplateKey.SALON_MODERN)
        self.assertFalse(fetched.data["ready"])
        self.assertIn("booking", str(fetched.data["blocking_reasons"]).lower())

    def test_update_domain_google_and_statuses(self):
        business = self._create_business("Domain Salon")
        location = self._create_location(business["id"], name="Main")
        self.client.post(self._url(business["id"]), {"location_id": location["id"]}, format="json")
        patched = self.client.patch(
            self._url(business["id"], location["id"]),
            {
                "subdomain": "ksnsalon",
                "custom_domain": "www.ksnsalon.com",
                "google_business_url": "https://maps.google.com/?cid=123",
                "google_business_status": GoogleBusinessStatus.READY,
                "website_status": "DRAFT",
            },
            format="json",
        )
        self.assertEqual(patched.status_code, status.HTTP_200_OK)
        self.assertEqual(patched.data["profile"]["subdomain"], "ksnsalon")
        self.assertEqual(patched.data["profile"]["custom_domain"], "www.ksnsalon.com")
        self.assertEqual(
            patched.data["profile"]["domain_status"],
            DomainStatus.CUSTOM_DOMAIN_PENDING,
        )
        self.assertEqual(
            patched.data["launch"]["google_business"]["status"],
            GoogleBusinessStatus.READY,
        )
        self.assertNotIn("token", str(patched.data).lower())
        self.assertNotIn("META_WHATSAPP", str(patched.data))

    def test_ready_requires_template_and_booking_setup(self):
        ctx = self._seed_with_quickcard(
            owner_email="ready-launch@example.com",
            org_name="Ready Launch Org",
            qc_slug="ready-launch",
        )
        before = self.client.get(self._url(ctx["business"]["id"], ctx["location"]["id"]))
        self.assertEqual(before.status_code, status.HTTP_200_OK)
        self.assertTrue(before.data["booking"]["ready"])
        self.assertFalse(before.data["ready"])
        self.assertFalse(before.data["template"]["selected"])
        self.assertIn("template", before.data["blocking_reasons"][0].lower())

        patched = self.client.patch(
            self._url(ctx["business"]["id"], ctx["location"]["id"]),
            {"template_key": WebsiteTemplateKey.SALON_CLASSIC},
            format="json",
        )
        self.assertEqual(patched.status_code, status.HTTP_200_OK)
        self.assertTrue(patched.data["launch"]["ready"])
        self.assertEqual(patched.data["launch"]["launch_status"], LaunchStatus.READY)
        self.assertEqual(patched.data["launch"]["progress"], 100)
        self.assertTrue(patched.data["launch"]["checklist"]["template"])

    def test_missing_quickcard_blocks_launch(self):
        ctx = self._seed_bookable_monday(
            owner_email="no-qc@example.com",
            org_name="No QC Org",
        )
        self._auth(ctx["token"])
        response = self.client.get(self._url(ctx["business"]["id"], ctx["location"]["id"]))
        self.assertFalse(response.data["ready"])
        self.assertFalse(response.data["quickcard"]["published"])
        self.assertTrue(any("QuickCard" in reason for reason in response.data["blocking_reasons"]))

    def test_cannot_go_live_when_incomplete(self):
        business = self._create_business("Draft Live")
        location = self._create_location(business["id"], name="Main")
        response = self.client.patch(
            self._url(business["id"], location["id"]),
            {"launch_status": LaunchStatus.LIVE},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_staff_forbidden_manager_allowed(self):
        business = self._create_business()
        owner = User.objects.get(email="launch-owner@example.com")
        staff_user = User.objects.create_user(
            email="launch-staff@example.com",
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
            {"email": "launch-staff@example.com", "password": "StrongPass123"},
            format="json",
        )
        staff_client = APIClient()
        staff_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        forbidden = staff_client.get(self._url(business["id"]))
        self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)

        manager = User.objects.create_user(
            email="launch-manager@example.com",
            password="StrongPass123",
            active_organization=owner.active_organization,
        )
        OrganizationMember.objects.create(
            organization=owner.active_organization,
            user=manager,
            role=Role.MANAGER,
        )
        mgr_login = self.client.post(
            reverse("auth-login"),
            {"email": "launch-manager@example.com", "password": "StrongPass123"},
            format="json",
        )
        mgr = APIClient()
        mgr.credentials(HTTP_AUTHORIZATION=f"Bearer {mgr_login.data['access']}")
        location = self._create_location(business["id"], name="Mgr Loc")
        ok = mgr.get(self._url(business["id"], location["id"]))
        self.assertEqual(ok.status_code, status.HTTP_200_OK)

    def test_cross_business_404(self):
        other = self._register("other-launch@example.com", "Other Launch")
        other_client = APIClient()
        other_client.credentials(HTTP_AUTHORIZATION=f"Bearer {other.data['access']}")
        other_biz = other_client.post(
            reverse("business-list"),
            {"name": "Other Biz", "vertical": "SALON"},
            format="json",
        )
        response = self.client.get(self._url(other_biz.data["id"]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_multi_location_isolation(self):
        ctx = self._seed_with_quickcard(
            owner_email="multi-launch@example.com",
            org_name="Multi Launch",
            qc_slug="multi-a",
        )
        loc_b = self._create_location(ctx["business"]["id"], name="Second")
        self.client.patch(
            self._url(ctx["business"]["id"], ctx["location"]["id"]),
            {"template_key": WebsiteTemplateKey.SALON_LUXURY},
            format="json",
        )
        a = self.client.get(self._url(ctx["business"]["id"], ctx["location"]["id"]))
        b = self.client.get(self._url(ctx["business"]["id"], loc_b["id"]))
        self.assertEqual(a.data["template"]["key"], WebsiteTemplateKey.SALON_LUXURY)
        self.assertIsNone(b.data["template"]["key"])
        self.assertNotEqual(
            a.data["profile"]["id"],
            b.data["profile"]["id"],
        )
        self.assertTrue(
            BusinessLaunchProfile.objects.filter(
                business_id=ctx["business"]["id"],
                location_id=ctx["location"]["id"],
            ).exists()
        )

    @override_settings(WHATSAPP_ENABLED=True, WHATSAPP_PROVIDER="mock")
    def test_whatsapp_platform_status_active_without_secrets(self):
        business = self._create_business("WA Salon")
        location = self._create_location(business["id"], name="Main")
        response = self.client.get(self._url(business["id"], location["id"]))
        self.assertEqual(response.data["whatsapp"]["status"], WhatsAppSetupStatus.ACTIVE)
        self.assertTrue(response.data["whatsapp"]["configured"])
        blob = str(response.data)
        self.assertNotIn("ACCESS_TOKEN", blob)
        self.assertNotIn("access_token", blob)

    def test_dashboard_includes_launch_summary(self):
        ctx = self._seed_with_quickcard(
            owner_email="dash-launch@example.com",
            org_name="Dash Launch",
            qc_slug="dash-launch",
        )
        self.client.patch(
            self._url(ctx["business"]["id"], ctx["location"]["id"]),
            {"template_key": WebsiteTemplateKey.SALON_MODERN},
            format="json",
        )
        dash = self.client.get(
            reverse("business-dashboard", kwargs={"business_id": ctx["business"]["id"]})
            + f"?location_id={ctx['location']['id']}"
        )
        self.assertEqual(dash.status_code, status.HTTP_200_OK)
        self.assertTrue(dash.data["launch"]["ready"])
        self.assertEqual(dash.data["launch"]["launch_status"], LaunchStatus.READY)
        self.assertNotIn("manage_token", str(dash.data))
