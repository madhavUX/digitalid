from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from businesses.models import Business, BusinessVertical
from locations.models import Location


class LocationAPITests(APITestCase):
    def _register(self, email: str, organization_name: str):
        response = self.client.post(
            reverse("auth-register"),
            {
                "email": email,
                "password": "StrongPass123",
                "organization_name": organization_name,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response

    def _auth(self, token: str):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def _create_business(self, name: str = "Ada Salon"):
        response = self.client.post(
            reverse("business-list"),
            {"name": name, "vertical": BusinessVertical.SALON},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def test_owner_can_create_and_read_location(self):
        register = self._register("owner@example.com", "Org A")
        self._auth(register.data["access"])
        business = self._create_business()

        create = self.client.post(
            reverse("location-list", kwargs={"business_id": business["id"]}),
            {
                "name": "Downtown",
                "timezone": "Asia/Kolkata",
                "city": "Mumbai",
                "country": "IN",
                "phone": "+919876543210",
                "organization_id": "ignored",
                "tenant_id": "ignored",
            },
            format="json",
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create.data["name"], "Downtown")
        self.assertTrue(create.data["is_primary"])
        self.assertEqual(create.data["timezone"], "Asia/Kolkata")

        location = Location.objects.get(pk=create.data["id"])
        self.assertEqual(str(location.organization_id), register.data["organization"]["id"])
        self.assertEqual(str(location.business_id), business["id"])

        listing = self.client.get(reverse("location-list", kwargs={"business_id": business["id"]}))
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual(listing.data["count"], 1)

    def test_location_must_belong_to_business_in_current_organization(self):
        org_a = self._register("owner-a@example.com", "Organization A")
        org_b = self._register("owner-b@example.com", "Organization B")

        self._auth(org_b.data["access"])
        business_b = self._create_business("Biz B")

        self._auth(org_a.data["access"])
        business_a = self._create_business("Biz A")

        # Cannot create a location under Org B's business while authenticated as Org A.
        response = self.client.post(
            reverse("location-list", kwargs={"business_id": business_b["id"]}),
            {"name": "Hijack", "timezone": "UTC"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Cannot attach Org A location using Org B business via body fields.
        created = self.client.post(
            reverse("location-list", kwargs={"business_id": business_a["id"]}),
            {
                "name": "Valid",
                "timezone": "UTC",
                "business_id": business_b["id"],
                "organization_id": org_b.data["organization"]["id"],
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        location = Location.objects.get(pk=created.data["id"])
        self.assertEqual(str(location.business_id), business_a["id"])
        self.assertEqual(str(location.organization_id), org_a.data["organization"]["id"])

    def test_organization_a_cannot_access_organization_b_location(self):
        org_a = self._register("owner-a@example.com", "Organization A")
        org_b = self._register("owner-b@example.com", "Organization B")

        self._auth(org_b.data["access"])
        business_b = self._create_business("Biz B")
        location_b = self.client.post(
            reverse("location-list", kwargs={"business_id": business_b["id"]}),
            {"name": "Branch B", "timezone": "UTC"},
            format="json",
        ).data

        self._auth(org_a.data["access"])
        listing = self.client.get(
            reverse("location-list", kwargs={"business_id": business_b["id"]})
        )
        self.assertEqual(listing.status_code, status.HTTP_404_NOT_FOUND)

        detail = self.client.get(
            reverse(
                "location-detail",
                kwargs={"business_id": business_b["id"], "location_id": location_b["id"]},
            )
        )
        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)

        patched = self.client.patch(
            reverse(
                "location-detail",
                kwargs={"business_id": business_b["id"], "location_id": location_b["id"]},
            ),
            {"name": "Hacked"},
            format="json",
        )
        self.assertEqual(patched.status_code, status.HTTP_404_NOT_FOUND)

        deleted = self.client.delete(
            reverse(
                "location-detail",
                kwargs={"business_id": business_b["id"], "location_id": location_b["id"]},
            )
        )
        self.assertEqual(deleted.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(Location.objects.filter(pk=location_b["id"]).exists())

    def test_soft_deleted_location_excluded_from_queries(self):
        register = self._register("owner@example.com", "Org A")
        self._auth(register.data["access"])
        business = self._create_business()
        created = self.client.post(
            reverse("location-list", kwargs={"business_id": business["id"]}),
            {"name": "Downtown", "timezone": "UTC"},
            format="json",
        )
        location_id = created.data["id"]

        deleted = self.client.delete(
            reverse(
                "location-detail",
                kwargs={"business_id": business["id"], "location_id": location_id},
            )
        )
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Location.objects.filter(pk=location_id).exists())
        self.assertIsNotNone(Location.all_objects.get(pk=location_id).deleted_at)

        listing = self.client.get(reverse("location-list", kwargs={"business_id": business["id"]}))
        self.assertEqual(listing.data["count"], 0)

    def test_invalid_timezone_rejected(self):
        register = self._register("owner@example.com", "Org A")
        self._auth(register.data["access"])
        business = self._create_business()
        response = self.client.post(
            reverse("location-list", kwargs={"business_id": business["id"]}),
            {"name": "Bad TZ", "timezone": "Not/AZone"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cross_tenant_business_id_with_own_location_path_fails(self):
        """Location under Org A business cannot be fetched via Org B business path."""
        org_a = self._register("owner-a@example.com", "Organization A")
        org_b = self._register("owner-b@example.com", "Organization B")

        self._auth(org_a.data["access"])
        business_a = self._create_business("Biz A")
        location_a = self.client.post(
            reverse("location-list", kwargs={"business_id": business_a["id"]}),
            {"name": "Branch A", "timezone": "UTC"},
            format="json",
        ).data

        self._auth(org_b.data["access"])
        business_b = self._create_business("Biz B")

        response = self.client.get(
            reverse(
                "location-detail",
                kwargs={
                    "business_id": business_b["id"],
                    "location_id": location_a["id"],
                },
            )
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(Business.objects.filter(pk=business_a["id"]).exists())
