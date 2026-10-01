"""Public salon website API tests."""

from __future__ import annotations

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from booking.tests.test_booking_api import BookingAPITestCase
from businesses.models import LaunchStatus, WebsiteStatus, WebsiteTemplateKey
from organizations.models import OrganizationMember, Role


class PublicWebsiteApiTests(BookingAPITestCase):
    def setUp(self):
        super().setUp()
        register = self._register("site-owner@example.com", "Site Org")
        self.access = register.data["access"]
        self._auth(self.access)

    def _launch_url(self, business_id, location_id=None):
        url = reverse("business-launch-profile", kwargs={"business_id": business_id})
        if location_id:
            return f"{url}?location_id={location_id}"
        return url

    def _public_url(self, slug):
        return reverse("public-site-detail", kwargs={"slug": slug})

    def _preview_url(self, business_id, location_id=None):
        url = reverse("business-website-preview", kwargs={"business_id": business_id})
        if location_id:
            return f"{url}?location_id={location_id}"
        return url

    def _seed_ready_site(self, *, qc_slug="site-salon", **kwargs):
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
            {
                "slug": qc_slug,
                "headline": "Style starts here",
                "description": "Premium cuts and care.",
                "phone": "+919999000111",
                "whatsapp": "+919999000111",
                "instagram_url": "https://instagram.com/ksn",
            },
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
        patched = self.client.patch(
            self._launch_url(ctx["business"]["id"], ctx["location"]["id"]),
            {"template_key": WebsiteTemplateKey.SALON_MODERN},
            format="json",
        )
        self.assertEqual(patched.status_code, status.HTTP_200_OK)
        self.assertTrue(patched.data["launch"]["ready"])
        return ctx

    def test_unpublished_site_404(self):
        ctx = self._seed_ready_site(
            owner_email="unpub@example.com",
            org_name="Unpub Org",
            qc_slug="unpub-salon",
        )
        response = self.client.get(self._public_url(ctx["location"]["slug"]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("available", str(response.data).lower())

    def test_publish_then_public_200(self):
        ctx = self._seed_ready_site(
            owner_email="pub@example.com",
            org_name="Pub Org",
            qc_slug="pub-salon",
        )
        published = self.client.patch(
            self._launch_url(ctx["business"]["id"], ctx["location"]["id"]),
            {"website_status": WebsiteStatus.PUBLISHED},
            format="json",
        )
        self.assertEqual(published.status_code, status.HTTP_200_OK)
        self.assertEqual(published.data["profile"]["launch_status"], LaunchStatus.LIVE)

        public = self.client.get(self._public_url(ctx["location"]["slug"]))
        self.assertEqual(public.status_code, status.HTTP_200_OK)
        self.assertEqual(public.data["template"], WebsiteTemplateKey.SALON_MODERN)
        self.assertEqual(public.data["business"]["name"], ctx["business"]["name"])
        self.assertEqual(public.data["location"]["slug"], ctx["location"]["slug"])
        self.assertTrue(len(public.data["services"]) >= 1)
        self.assertTrue(len(public.data["staff"]) >= 1)
        self.assertEqual(public.data["booking"]["path"], f"/book/{ctx['location']['slug']}")
        self.assertNotIn("manage_token", str(public.data))
        self.assertNotIn("access_token", str(public.data).lower())
        self.assertNotIn("customer", str(public.data["services"]))

    def test_invalid_slug_404(self):
        response = self.client.get(self._public_url("does-not-exist-xyz"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_subdomain_resolution(self):
        ctx = self._seed_ready_site(
            owner_email="sub@example.com",
            org_name="Sub Org",
            qc_slug="sub-salon",
        )
        self.client.patch(
            self._launch_url(ctx["business"]["id"], ctx["location"]["id"]),
            {
                "subdomain": "ksnsalon",
                "website_status": WebsiteStatus.PUBLISHED,
            },
            format="json",
        )
        public = self.client.get(self._public_url("ksnsalon"))
        self.assertEqual(public.status_code, status.HTTP_200_OK)
        self.assertEqual(public.data["location"]["slug"], ctx["location"]["slug"])

    def test_preview_allowed_before_publish(self):
        ctx = self._seed_ready_site(
            owner_email="preview@example.com",
            org_name="Preview Org",
            qc_slug="preview-salon",
        )
        preview = self.client.get(self._preview_url(ctx["business"]["id"], ctx["location"]["id"]))
        self.assertEqual(preview.status_code, status.HTTP_200_OK)
        self.assertTrue(preview.data["preview"])
        self.assertFalse(preview.data["published"])

    def test_staff_forbidden_preview(self):
        ctx = self._seed_ready_site(
            owner_email="staff-site@example.com",
            org_name="Staff Site Org",
            qc_slug="staff-site",
        )
        owner = User.objects.get(email="staff-site@example.com")
        staff_user = User.objects.create_user(
            email="site-staff@example.com",
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
            {"email": "site-staff@example.com", "password": "StrongPass123"},
            format="json",
        )
        staff_client = APIClient()
        staff_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        response = staff_client.get(self._preview_url(ctx["business"]["id"], ctx["location"]["id"]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_multi_location_isolation(self):
        ctx = self._seed_ready_site(
            owner_email="multi-site@example.com",
            org_name="Multi Site",
            qc_slug="multi-site-a",
        )
        loc_b = self._create_location(ctx["business"]["id"], name="Second Branch")
        self.client.patch(
            self._launch_url(ctx["business"]["id"], ctx["location"]["id"]),
            {
                "template_key": WebsiteTemplateKey.SALON_LUXURY,
                "website_status": WebsiteStatus.PUBLISHED,
            },
            format="json",
        )
        # Location B not published / incomplete
        public_a = self.client.get(self._public_url(ctx["location"]["slug"]))
        public_b = self.client.get(self._public_url(loc_b["slug"]))
        self.assertEqual(public_a.status_code, status.HTTP_200_OK)
        self.assertEqual(public_a.data["template"], WebsiteTemplateKey.SALON_LUXURY)
        self.assertEqual(public_b.status_code, status.HTTP_404_NOT_FOUND)
