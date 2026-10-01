"""Website provisioning + publish/unpublish tests."""

from __future__ import annotations

from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from booking.tests.test_booking_api import BookingAPITestCase
from businesses.models import (
    Business,
    BusinessLaunchProfile,
    DomainStatus,
    LaunchStatus,
    WebsiteStatus,
    WebsiteTemplateKey,
)
from locations.models import Location
from organizations.models import OrganizationMember, Role
from sites.provisioning_services import (
    allocate_unique_subdomain,
    normalize_subdomain_label,
    provision_website,
    provisioned_public_url,
)


class WebsiteProvisioningTests(BookingAPITestCase):
    def setUp(self):
        super().setUp()
        register = self._register("prov-owner@example.com", "Prov Org")
        self.access = register.data["access"]
        self._auth(self.access)

    def _seed_ready(self, *, qc_slug="prov-salon", **kwargs):
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
        return ctx

    def test_normalize_and_collision(self):
        self.assertEqual(normalize_subdomain_label("KSN Salon & Spa"), "ksn-salon-and-spa")
        business = self._create_business("Collision Salon")
        location = self._create_location(business["id"], name="Main")
        biz = Business.objects.get(pk=business["id"])
        loc = Location.objects.get(pk=location["id"])
        first = allocate_unique_subdomain(location=loc, business=biz, preferred="ksn-salon")
        BusinessLaunchProfile.objects.create(
            organization=biz.organization,
            business=biz,
            location=loc,
            subdomain=first,
            domain_status=DomainStatus.SUBDOMAIN_ACTIVE,
        )
        loc2 = Location.objects.get(pk=self._create_location(business["id"], name="Second")["id"])
        second = allocate_unique_subdomain(location=loc2, business=biz, preferred="ksn-salon")
        self.assertEqual(second, "ksn-salon-2")

    @override_settings(BOOKANYTHING_SITE_DOMAIN="bookanything.in")
    def test_publish_provisions_and_public_url(self):
        ctx = self._seed_ready(
            owner_email="pub-prov@example.com",
            org_name="Pub Prov",
            qc_slug="pub-prov",
        )
        published = self.client.post(
            reverse("business-website-publish", kwargs={"business_id": ctx["business"]["id"]})
            + f"?location_id={ctx['location']['id']}",
        )
        self.assertEqual(published.status_code, status.HTTP_200_OK)
        self.assertEqual(published.data["website_status"], WebsiteStatus.PUBLISHED)
        self.assertEqual(published.data["domain_status"], DomainStatus.SUBDOMAIN_ACTIVE)
        self.assertEqual(published.data["launch_status"], LaunchStatus.LIVE)
        self.assertTrue(published.data["subdomain"])
        self.assertTrue(published.data["public_url"].startswith("https://"))
        self.assertIn(".bookanything.in", published.data["public_url"])

        again = provision_website(
            organization=User.objects.get(email="pub-prov@example.com").active_organization,
            business_id=ctx["business"]["id"],
            location_id=ctx["location"]["id"],
        )
        self.assertEqual(again.subdomain, published.data["subdomain"])

        public = self.client.get(
            reverse("public-site-detail", kwargs={"slug": published.data["subdomain"]})
        )
        self.assertEqual(public.status_code, status.HTTP_200_OK)
        self.assertEqual(public.data["site"]["url"], published.data["public_url"])

    def test_unpublish_hides_and_republish_reuses_subdomain(self):
        ctx = self._seed_ready(
            owner_email="unpub-prov@example.com",
            org_name="Unpub Prov",
            qc_slug="unpub-prov",
        )
        published = self.client.post(
            reverse("business-website-publish", kwargs={"business_id": ctx["business"]["id"]})
            + f"?location_id={ctx['location']['id']}",
        )
        sub = published.data["subdomain"]
        hidden = self.client.post(
            reverse("business-website-unpublish", kwargs={"business_id": ctx["business"]["id"]})
            + f"?location_id={ctx['location']['id']}",
        )
        self.assertEqual(hidden.status_code, status.HTTP_200_OK)
        self.assertEqual(hidden.data["website_status"], WebsiteStatus.UNPUBLISHED)
        self.assertEqual(hidden.data["subdomain"], sub)
        missing = self.client.get(reverse("public-site-detail", kwargs={"slug": sub}))
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)

        again = self.client.post(
            reverse("business-website-publish", kwargs={"business_id": ctx["business"]["id"]})
            + f"?location_id={ctx['location']['id']}",
        )
        self.assertEqual(again.data["subdomain"], sub)
        live = self.client.get(reverse("public-site-detail", kwargs={"slug": sub}))
        self.assertEqual(live.status_code, status.HTTP_200_OK)

    def test_template_switch_keeps_url(self):
        ctx = self._seed_ready(
            owner_email="switch-prov@example.com",
            org_name="Switch Prov",
            qc_slug="switch-prov",
        )
        published = self.client.post(
            reverse("business-website-publish", kwargs={"business_id": ctx["business"]["id"]})
            + f"?location_id={ctx['location']['id']}",
        )
        sub = published.data["subdomain"]
        switched = self.client.patch(
            reverse("business-launch-profile", kwargs={"business_id": ctx["business"]["id"]})
            + f"?location_id={ctx['location']['id']}",
            {"template_key": WebsiteTemplateKey.SALON_CLASSIC},
            format="json",
        )
        self.assertEqual(switched.status_code, status.HTTP_200_OK)
        status_view = self.client.get(
            reverse("business-website-status", kwargs={"business_id": ctx["business"]["id"]})
            + f"?location_id={ctx['location']['id']}",
        )
        self.assertEqual(status_view.data["subdomain"], sub)
        self.assertEqual(status_view.data["template_key"], WebsiteTemplateKey.SALON_CLASSIC)
        public = self.client.get(reverse("public-site-detail", kwargs={"slug": sub}))
        self.assertEqual(public.data["template"], WebsiteTemplateKey.SALON_CLASSIC)

    def test_multi_location_isolation(self):
        ctx = self._seed_ready(
            owner_email="multi-prov@example.com",
            org_name="Multi Prov",
            qc_slug="multi-prov-a",
        )
        loc_b = self._create_location(ctx["business"]["id"], name="Branch B")
        pub_a = self.client.post(
            reverse("business-website-publish", kwargs={"business_id": ctx["business"]["id"]})
            + f"?location_id={ctx['location']['id']}",
        )
        self.assertEqual(pub_a.status_code, status.HTTP_200_OK)
        pub_b = self.client.post(
            reverse("business-website-publish", kwargs={"business_id": ctx["business"]["id"]})
            + f"?location_id={loc_b['id']}",
        )
        self.assertEqual(pub_b.status_code, status.HTTP_400_BAD_REQUEST)

    def test_staff_forbidden(self):
        ctx = self._seed_ready(
            owner_email="staff-prov@example.com",
            org_name="Staff Prov",
            qc_slug="staff-prov",
        )
        owner = User.objects.get(email="staff-prov@example.com")
        staff_user = User.objects.create_user(
            email="prov-staff@example.com",
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
            {"email": "prov-staff@example.com", "password": "StrongPass123"},
            format="json",
        )
        staff_client = APIClient()
        staff_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        denied = staff_client.post(
            reverse("business-website-publish", kwargs={"business_id": ctx["business"]["id"]})
        )
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

    @override_settings(BOOKANYTHING_SITE_DOMAIN="bookanything.in")
    def test_public_url_helper(self):
        self.assertEqual(
            provisioned_public_url("ksnsalon"),
            "https://ksnsalon.bookanything.in",
        )

    def test_inactive_location_not_public(self):
        ctx = self._seed_ready(
            owner_email="inactive-prov@example.com",
            org_name="Inactive Prov",
            qc_slug="inactive-prov",
        )
        published = self.client.post(
            reverse("business-website-publish", kwargs={"business_id": ctx["business"]["id"]})
            + f"?location_id={ctx['location']['id']}",
        )
        sub = published.data["subdomain"]
        Location.objects.filter(pk=ctx["location"]["id"]).update(is_active=False)
        missing = self.client.get(reverse("public-site-detail", kwargs={"slug": sub}))
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_website_status(self):
        ctx = self._seed_ready(
            owner_email="status-prov@example.com",
            org_name="Status Prov",
            qc_slug="status-prov",
        )
        self.client.post(
            reverse("business-website-publish", kwargs={"business_id": ctx["business"]["id"]})
            + f"?location_id={ctx['location']['id']}",
        )
        status_view = self.client.get(
            reverse("business-website-status", kwargs={"business_id": ctx["business"]["id"]})
            + f"?location_id={ctx['location']['id']}",
        )
        self.assertEqual(status_view.status_code, status.HTTP_200_OK)
        self.assertEqual(status_view.data["website_status"], WebsiteStatus.PUBLISHED)
        self.assertTrue(status_view.data["public_url"])
