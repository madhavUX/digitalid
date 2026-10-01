"""QuickCard MVP tests — model, public API, permissions, QR."""

from __future__ import annotations

from datetime import timedelta

from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from businesses.models import Business, BusinessLaunchProfile, BusinessVertical
from catalog.models import Service
from locations.models import Location
from organizations.models import OrganizationMember, Role
from sites.models import QuickCard, QuickCardEvent
from sites.services import generate_quickcard_qr_png, public_quickcard_url
from staff.models import Weekday


@override_settings(
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": (
            "rest_framework_simplejwt.authentication.JWTAuthentication",
        ),
        "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
        "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
        "DEFAULT_PAGINATION_CLASS": "core.pagination.StandardLimitOffsetPagination",
        "PAGE_SIZE": 25,
        "EXCEPTION_HANDLER": "core.exceptions.api_exception_handler",
        "DEFAULT_THROTTLE_RATES": {
            "public_booking_availability": "10000/min",
            "public_booking_write": "10000/min",
            "public_catalog": "10000/min",
            "public_quickcard_events": "10000/min",
        },
    },
    PUBLIC_APP_URL="https://book.example.com",
)
class QuickCardAPITests(APITestCase):
    def setUp(self):
        super().setUp()
        self.public = APIClient()
        register = self.client.post(
            reverse("auth-register"),
            {
                "email": "qc-owner@example.com",
                "password": "StrongPass123",
                "organization_name": "QC Org",
            },
            format="json",
        )
        self.assertEqual(register.status_code, status.HTTP_201_CREATED)
        self.access = register.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access}")
        business = self.client.post(
            reverse("business-list"),
            {"name": "KSN Salon", "vertical": BusinessVertical.SALON},
            format="json",
        )
        self.assertEqual(business.status_code, status.HTTP_201_CREATED)
        self.business_id = business.data["id"]
        location = self.client.post(
            reverse("location-list", kwargs={"business_id": self.business_id}),
            {"name": "Downtown", "timezone": "Asia/Kolkata", "phone": "+918012345678"},
            format="json",
        )
        self.assertEqual(location.status_code, status.HTTP_201_CREATED)
        self.location_id = location.data["id"]
        self.location_slug = location.data["slug"]

        service = self.client.post(
            reverse("service-list", kwargs={"business_id": self.business_id}),
            {
                "name": "Haircut",
                "duration_minutes": 30,
                "price": "400.00",
                "is_bookable_online": True,
            },
            format="json",
        )
        self.assertEqual(service.status_code, status.HTTP_201_CREATED)
        self.client.post(
            reverse(
                "service-location-list",
                kwargs={"business_id": self.business_id, "service_id": service.data["id"]},
            ),
            {"location_id": self.location_id},
            format="json",
        )
        staff = self.client.post(
            reverse("staff-list", kwargs={"business_id": self.business_id}),
            {"display_name": "Priya", "location_id": self.location_id},
            format="json",
        )
        self.assertEqual(staff.status_code, status.HTTP_201_CREATED)
        self.client.post(
            reverse(
                "staff-service-list",
                kwargs={"business_id": self.business_id, "staff_id": staff.data["id"]},
            ),
            {"service_id": service.data["id"]},
            format="json",
        )
        self.client.post(
            reverse(
                "staff-availability-list",
                kwargs={"business_id": self.business_id, "staff_id": staff.data["id"]},
            ),
            {
                "location_id": self.location_id,
                "weekday": Weekday.MONDAY,
                "starts_at": "09:00:00",
                "ends_at": "17:00:00",
            },
            format="json",
        )

    def _quickcard_url(self, suffix=""):
        return (
            reverse(
                "quickcard-detail",
                kwargs={"business_id": self.business_id, "location_id": self.location_id},
            )
            + suffix
        )

    def _create_card(self, **extra):
        payload = {
            "slug": "ksn-salon",
            "headline": "Look your best",
            "description": "Premium salon downtown.",
            "whatsapp": "+918012345678",
            "instagram_url": "https://instagram.com/ksn",
            **extra,
        }
        return self.client.post(self._quickcard_url(), payload, format="json")

    def test_create_one_per_location_and_slug_unique(self):
        created = self._create_card()
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(created.data["slug"], "ksn-salon")
        self.assertFalse(created.data["is_published"])
        self.assertEqual(QuickCard.objects.count(), 1)

        duplicate = self._create_card(slug="other-slug")
        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)

        # Second location can create; slug collision rejected
        location2 = self.client.post(
            reverse("location-list", kwargs={"business_id": self.business_id}),
            {"name": "Uptown", "timezone": "Asia/Kolkata"},
            format="json",
        )
        collide = self.client.post(
            reverse(
                "quickcard-detail",
                kwargs={
                    "business_id": self.business_id,
                    "location_id": location2.data["id"],
                },
            ),
            {"slug": "ksn-salon"},
            format="json",
        )
        self.assertEqual(collide.status_code, status.HTTP_400_BAD_REQUEST)

    def test_slug_stable_after_create(self):
        self._create_card()
        patched = self.client.patch(
            self._quickcard_url(),
            {"slug": "changed", "headline": "New"},
            format="json",
        )
        self.assertEqual(patched.status_code, status.HTTP_400_BAD_REQUEST)
        card = QuickCard.objects.get()
        self.assertEqual(card.slug, "ksn-salon")
        self.assertEqual(card.headline, "Look your best")

        ok = self.client.patch(
            self._quickcard_url(),
            {"headline": "Updated"},
            format="json",
        )
        self.assertEqual(ok.status_code, status.HTTP_200_OK)
        self.assertEqual(ok.data["headline"], "Updated")

    def test_publish_unpublish_and_public_api(self):
        self._create_card()
        unpublished = self.public.get(
            reverse("public-quickcard-detail", kwargs={"slug": "ksn-salon"})
        )
        self.assertEqual(unpublished.status_code, status.HTTP_404_NOT_FOUND)

        published = self.client.post(
            reverse(
                "quickcard-publish",
                kwargs={"business_id": self.business_id, "location_id": self.location_id},
            )
        )
        self.assertEqual(published.status_code, status.HTTP_200_OK)
        self.assertTrue(published.data["is_published"])

        public = self.public.get(reverse("public-quickcard-detail", kwargs={"slug": "ksn-salon"}))
        self.assertEqual(public.status_code, status.HTTP_200_OK)
        data = public.data
        self.assertEqual(data["slug"], "ksn-salon")
        self.assertEqual(data["business"]["name"], "KSN Salon")
        self.assertEqual(data["booking"]["location_slug"], self.location_slug)
        self.assertEqual(
            data["booking"]["booking_path"].split("?")[0], f"/book/{self.location_slug}"
        )
        self.assertIn("source=quickcard", data["booking"]["booking_path"])
        self.assertTrue(any(s["name"] == "Haircut" for s in data["services"]))
        self.assertTrue(any(s["display_name"] == "Priya" for s in data["staff"]))
        self.assertNotIn("manage_token", str(data))
        self.assertNotIn("customer", str(data).lower())
        self.assertNotIn("appointment", str(data).lower())
        raw = str(data)
        self.assertNotIn(self.access[:12], raw)

        self.client.post(
            reverse(
                "quickcard-unpublish",
                kwargs={"business_id": self.business_id, "location_id": self.location_id},
            )
        )
        again = self.public.get(reverse("public-quickcard-detail", kwargs={"slug": "ksn-salon"}))
        self.assertEqual(again.status_code, status.HTTP_404_NOT_FOUND)

    def test_invalid_slug_404(self):
        response = self.public.get(
            reverse("public-quickcard-detail", kwargs={"slug": "missing-card"})
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_staff_cannot_modify(self):
        self._create_card()
        owner = User.objects.get(email="qc-owner@example.com")
        member = User.objects.create_user(
            email="qc-staff@example.com",
            password="StrongPass123",
            active_organization=owner.active_organization,
        )
        OrganizationMember.objects.create(
            organization=owner.active_organization,
            user=member,
            role=Role.STAFF,
        )
        login = self.client.post(
            reverse("auth-login"),
            {"email": "qc-staff@example.com", "password": "StrongPass123"},
            format="json",
        )
        staff_client = APIClient()
        staff_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        forbidden = staff_client.patch(
            self._quickcard_url(),
            {"headline": "Nope"},
            format="json",
        )
        self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)
        publish = staff_client.post(
            reverse(
                "quickcard-publish",
                kwargs={"business_id": self.business_id, "location_id": self.location_id},
            )
        )
        self.assertEqual(publish.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_cannot_modify(self):
        anon = APIClient()
        response = anon.post(
            self._quickcard_url(),
            {"slug": "hack"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_manager_can_publish(self):
        self._create_card()
        owner = User.objects.get(email="qc-owner@example.com")
        manager = User.objects.create_user(
            email="qc-manager@example.com",
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
            {"email": "qc-manager@example.com", "password": "StrongPass123"},
            format="json",
        )
        mgr = APIClient()
        mgr.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        published = mgr.post(
            reverse(
                "quickcard-publish",
                kwargs={"business_id": self.business_id, "location_id": self.location_id},
            )
        )
        self.assertEqual(published.status_code, status.HTTP_200_OK)
        self.assertTrue(published.data["is_published"])

    def test_qr_encodes_public_url_only(self):
        self._create_card()
        png = generate_quickcard_qr_png(slug="ksn-salon")
        self.assertTrue(png.startswith(b"\x89PNG"))
        expected = public_quickcard_url("ksn-salon")
        self.assertEqual(expected, "https://book.example.com/q/ksn-salon")
        self.assertNotIn("manage", expected)
        self.assertNotIn("token", expected)

        qr_http = self.client.get(
            reverse(
                "quickcard-qr",
                kwargs={"business_id": self.business_id, "location_id": self.location_id},
            )
        )
        self.assertEqual(qr_http.status_code, status.HTTP_200_OK)
        self.assertEqual(qr_http["Content-Type"], "image/png")
        self.assertTrue(qr_http.content.startswith(b"\x89PNG"))

    def _publish(self):
        self._create_card()
        self.client.post(
            reverse(
                "quickcard-publish",
                kwargs={"business_id": self.business_id, "location_id": self.location_id},
            )
        )

    def test_public_profile_actions_visibility_and_cache(self):
        self._publish()
        location = Location.objects.get(pk=self.location_id)
        BusinessLaunchProfile.objects.create(
            organization=location.organization,
            business=location.business,
            location=location,
            google_business_url="https://maps.google.com/?cid=123",
            google_review_url="https://search.google.com/local/writereview?placeid=abc",
        )
        with CaptureQueriesContext(connection) as captured:
            public = self.public.get(
                reverse("public-quickcard-detail", kwargs={"slug": "ksn-salon"})
            )
        self.assertEqual(public.status_code, status.HTTP_200_OK)
        self.assertLessEqual(len(captured), 20)
        self.assertEqual(public["Cache-Control"], "public, max-age=60")
        data = public.data
        self.assertTrue(data["actions"]["booking_url"].startswith(f"/book/{self.location_slug}?"))
        self.assertEqual(data["actions"]["whatsapp_url"], "https://wa.me/918012345678")
        self.assertEqual(data["actions"]["call_url"], "tel:+918012345678")
        self.assertEqual(data["actions"]["directions_url"], "https://maps.google.com/?cid=123")
        self.assertIn("placeid=abc", data["actions"]["review_url"])
        self.assertEqual(data["reviews"], None)
        self.assertEqual(data["services"][0]["price"], "400.00")
        self.assertEqual(data["services"][0]["duration_minutes"], 30)
        raw = str(data)
        self.assertNotIn("access_token", raw)
        self.assertNotIn("created_by", raw)
        self.assertNotIn(str(location.organization_id), raw)
        self.assertNotIn(str(location.business_id), raw)
        alias = self.public.get(reverse("public-quickcard-alias", kwargs={"slug": "ksn-salon"}))
        self.assertEqual(alias.status_code, status.HTTP_200_OK)

        profile = BusinessLaunchProfile.objects.get(location=location)
        profile.google_review_url = "http://example.com/review"
        profile.google_business_url = "javascript:alert(1)"
        profile.save(update_fields=["google_review_url", "google_business_url", "updated_at"])
        QuickCard.objects.filter(slug="ksn-salon").update(google_maps_url="", whatsapp="", phone="")
        Location.objects.filter(pk=location.id).update(phone="")
        hidden = self.public.get(reverse("public-quickcard-detail", kwargs={"slug": "ksn-salon"}))
        self.assertIsNone(hidden.data["actions"]["review_url"])
        self.assertIsNone(hidden.data["actions"]["directions_url"])
        self.assertIsNone(hidden.data["actions"]["whatsapp_url"])
        self.assertIsNone(hidden.data["actions"]["call_url"])

    def test_unpublished_inactive_and_other_location_services_are_hidden(self):
        self._publish()
        haircut = Service.objects.get(business_id=self.business_id, name="Haircut")
        location2 = self.client.post(
            reverse("location-list", kwargs={"business_id": self.business_id}),
            {"name": "Uptown", "timezone": "Asia/Kolkata", "phone": "+919800000222"},
            format="json",
        )
        other = self.client.post(
            reverse("service-list", kwargs={"business_id": self.business_id}),
            {
                "name": "Color",
                "duration_minutes": 60,
                "price": "900.00",
                "is_bookable_online": True,
            },
            format="json",
        )
        self.client.post(
            reverse(
                "service-location-list",
                kwargs={"business_id": self.business_id, "service_id": other.data["id"]},
            ),
            {"location_id": location2.data["id"]},
            format="json",
        )
        self.client.post(
            reverse(
                "quickcard-detail",
                kwargs={"business_id": self.business_id, "location_id": location2.data["id"]},
            ),
            {"slug": "ksn-uptown"},
            format="json",
        )
        self.client.post(
            reverse(
                "quickcard-publish",
                kwargs={"business_id": self.business_id, "location_id": location2.data["id"]},
            )
        )
        downtown = self.public.get(reverse("public-quickcard-detail", kwargs={"slug": "ksn-salon"}))
        self.assertTrue(all(row["name"] != "Color" for row in downtown.data["services"]))
        uptown = self.public.get(reverse("public-quickcard-detail", kwargs={"slug": "ksn-uptown"}))
        self.assertEqual([row["name"] for row in uptown.data["services"]], ["Color"])

        haircut.is_active = False
        haircut.save(update_fields=["is_active", "updated_at"])
        inactive = self.public.get(reverse("public-quickcard-detail", kwargs={"slug": "ksn-salon"}))
        self.assertEqual(inactive.data["services"], [])
        haircut.is_active = True
        haircut.is_bookable_online = False
        haircut.save(update_fields=["is_active", "is_bookable_online", "updated_at"])
        offline = self.public.get(reverse("public-quickcard-detail", kwargs={"slug": "ksn-salon"}))
        self.assertEqual(offline.data["services"], [])
        haircut.is_bookable_online = True
        haircut.save(update_fields=["is_bookable_online", "updated_at"])
        haircut.delete()
        deleted = self.public.get(reverse("public-quickcard-detail", kwargs={"slug": "ksn-salon"}))
        self.assertEqual(deleted.data["services"], [])

        Location.objects.filter(pk=self.location_id).update(is_active=False)
        self.assertEqual(
            self.public.get(
                reverse("public-quickcard-detail", kwargs={"slug": "ksn-salon"})
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        Location.objects.filter(pk=self.location_id).update(is_active=True)
        Business.objects.filter(pk=self.business_id).update(is_active=False)
        self.assertEqual(
            self.public.get(
                reverse("public-quickcard-detail", kwargs={"slug": "ksn-salon"})
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        Business.objects.filter(pk=self.business_id).update(is_active=True)
        Location.objects.get(pk=self.location_id).delete()
        self.assertEqual(
            self.public.get(
                reverse("public-quickcard-detail", kwargs={"slug": "ksn-salon"})
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_records_views_and_every_cta_without_tenant_ids(self):
        self._publish()
        url = reverse("public-quickcard-events", kwargs={"slug": "ksn-salon"})
        recorded = self.public.post(url, {"event_type": "page_view"}, format="json")
        self.assertEqual(recorded.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(recorded.content, b"")
        self.assertEqual(recorded["Cache-Control"], "no-store")
        for cta in ["book", "whatsapp", "CALL", "directions", "review", "share"]:
            clicked = self.public.post(url, {"event_type": "CTA_CLICK", "cta": cta}, format="json")
            self.assertEqual(clicked.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(QuickCardEvent.objects.filter(event_type="PAGE_VIEW").count(), 1)
        stored = set(
            QuickCardEvent.objects.filter(event_type="CTA_CLICK").values_list("cta_type", flat=True)
        )
        self.assertEqual(stored, {"BOOK", "WHATSAPP", "CALL", "DIRECTIONS", "REVIEW", "SHARE"})
        event = QuickCardEvent.objects.get(event_type="PAGE_VIEW")
        location = Location.objects.get(pk=self.location_id)
        self.assertEqual(event.organization_id, location.organization_id)
        self.assertEqual(event.business_id, location.business_id)
        self.assertEqual(event.cta_type, "")

    def test_rejects_unknown_values_and_hidden_cards(self):
        missing = self.public.post(
            reverse("public-quickcard-events", kwargs={"slug": "missing-card"}),
            {"event_type": "PAGE_VIEW"},
            format="json",
        )
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)
        self._create_card()
        hidden = self.public.post(
            reverse("public-quickcard-events", kwargs={"slug": "ksn-salon"}),
            {"event_type": "PAGE_VIEW"},
            format="json",
        )
        self.assertEqual(hidden.status_code, status.HTTP_404_NOT_FOUND)
        self.client.post(
            reverse(
                "quickcard-publish",
                kwargs={"business_id": self.business_id, "location_id": self.location_id},
            )
        )
        url = reverse("public-quickcard-events", kwargs={"slug": "ksn-salon"})
        bad_type = self.public.post(url, {"event_type": "PURCHASE"}, format="json")
        bad_cta = self.public.post(
            url, {"event_type": "CTA_CLICK", "cta": "checkout"}, format="json"
        )
        extra = self.public.post(
            url,
            {"event_type": "PAGE_VIEW", "organization_id": str(self.business_id)},
            format="json",
        )
        self.assertEqual(bad_type.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(bad_cta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(extra.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(QuickCardEvent.objects.count(), 0)
        Location.objects.filter(pk=self.location_id).update(is_active=False)
        inactive = self.public.post(url, {"event_type": "PAGE_VIEW"}, format="json")
        self.assertEqual(inactive.status_code, status.HTTP_404_NOT_FOUND)

    def test_owner_manager_and_date_aggregation(self):
        self._publish()
        url = reverse("public-quickcard-events", kwargs={"slug": "ksn-salon"})
        self.public.post(url, {"event_type": "PAGE_VIEW"}, format="json")
        self.public.post(url, {"event_type": "PAGE_VIEW"}, format="json")
        self.public.post(url, {"event_type": "CTA_CLICK", "cta": "book"}, format="json")
        self.public.post(url, {"event_type": "CTA_CLICK", "cta": "share"}, format="json")
        old = QuickCardEvent.objects.filter(cta_type="SHARE").get()
        old.occurred_at = timezone.now() - timedelta(days=40)
        old.save(update_fields=["occurred_at", "updated_at"])

        summary = self.client.get(
            reverse("quickcard-analytics", kwargs={"business_id": self.business_id})
        )
        self.assertEqual(summary.status_code, status.HTTP_200_OK)
        self.assertEqual(summary["Cache-Control"], "private, no-store")
        self.assertEqual(summary.data["views"], 2)
        self.assertEqual(summary.data["cta_clicks"]["book"], 1)
        self.assertEqual(summary.data["cta_clicks"]["share"], 0)
        self.assertNotIn("organization_id", summary.data)
        wide = self.client.get(
            reverse("quickcard-analytics", kwargs={"business_id": self.business_id}),
            {"date_from": (timezone.now() - timedelta(days=50)).date().isoformat()},
        )
        self.assertEqual(wide.data["cta_clicks"]["share"], 1)

        owner = User.objects.get(email="qc-owner@example.com")
        manager = self._member(owner, "qc-analytics-mgr@example.com", Role.MANAGER)
        staff = self._member(owner, "qc-analytics-staff@example.com", Role.STAFF)
        path = reverse("quickcard-analytics", kwargs={"business_id": self.business_id})
        self.assertEqual(manager.get(path).status_code, status.HTTP_200_OK)
        self.assertEqual(staff.get(path).status_code, status.HTTP_403_FORBIDDEN)
        other = self.client.post(
            reverse("auth-register"),
            {
                "email": "qc-other-analytics@example.com",
                "password": "StrongPass123",
                "organization_name": "Other Analytics",
            },
            format="json",
        )
        outsider = APIClient()
        outsider.credentials(HTTP_AUTHORIZATION=f"Bearer {other.data['access']}")
        self.assertEqual(outsider.get(path).status_code, status.HTTP_404_NOT_FOUND)

    def _member(self, owner, email, role):
        user = User.objects.create_user(
            email=email,
            password="StrongPass123",
            active_organization=owner.active_organization,
        )
        OrganizationMember.objects.create(
            organization=owner.active_organization, user=user, role=role
        )
        login = self.client.post(
            reverse("auth-login"),
            {"email": email, "password": "StrongPass123"},
            format="json",
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        return client
