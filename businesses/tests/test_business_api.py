from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from businesses.models import Business, BusinessVertical
from organizations.models import OrganizationMember, Role


class BusinessAPITests(APITestCase):
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

    def test_owner_can_create_and_read_business(self):
        register = self._register("owner@example.com", "Org A")
        self._auth(register.data["access"])

        create = self.client.post(
            reverse("business-list"),
            {
                "name": "Ada Salon",
                "vertical": BusinessVertical.SALON,
                "organization_id": "should-be-ignored",
                "tenant_id": "should-be-ignored",
            },
            format="json",
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create.data["name"], "Ada Salon")
        self.assertEqual(create.data["vertical"], BusinessVertical.SALON)
        self.assertEqual(create.data["slug"], "ada-salon")

        business = Business.objects.get(pk=create.data["id"])
        self.assertEqual(str(business.organization_id), register.data["organization"]["id"])

        detail = self.client.get(reverse("business-detail", kwargs={"business_id": business.id}))
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertEqual(detail.data["id"], create.data["id"])

        listing = self.client.get(reverse("business-list"))
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual(listing.data["count"], 1)
        self.assertEqual(listing.data["results"][0]["id"], create.data["id"])

    def test_owner_can_update_business(self):
        register = self._register("owner@example.com", "Org A")
        self._auth(register.data["access"])
        created = self.client.post(
            reverse("business-list"),
            {"name": "Ada Salon", "vertical": BusinessVertical.SALON},
            format="json",
        )

        response = self.client.patch(
            reverse("business-detail", kwargs={"business_id": created.data["id"]}),
            {"name": "Ada Spa", "vertical": BusinessVertical.SPA},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Ada Spa")
        self.assertEqual(response.data["vertical"], BusinessVertical.SPA)

    def test_owner_can_soft_delete_business(self):
        register = self._register("owner@example.com", "Org A")
        self._auth(register.data["access"])
        created = self.client.post(
            reverse("business-list"),
            {"name": "Ada Salon", "vertical": BusinessVertical.SALON},
            format="json",
        )
        business_id = created.data["id"]

        deleted = self.client.delete(
            reverse("business-detail", kwargs={"business_id": business_id})
        )
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Business.objects.filter(pk=business_id).exists())
        self.assertTrue(Business.all_objects.filter(pk=business_id).exists())
        self.assertIsNotNone(Business.all_objects.get(pk=business_id).deleted_at)

        listing = self.client.get(reverse("business-list"))
        self.assertEqual(listing.data["count"], 0)

        detail = self.client.get(reverse("business-detail", kwargs={"business_id": business_id}))
        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)

    def test_organization_a_cannot_access_organization_b_business(self):
        org_a = self._register("owner-a@example.com", "Organization A")
        org_b = self._register("owner-b@example.com", "Organization B")

        self._auth(org_b.data["access"])
        created = self.client.post(
            reverse("business-list"),
            {"name": "Biz B", "vertical": BusinessVertical.SALON},
            format="json",
        )
        business_b_id = created.data["id"]

        self._auth(org_a.data["access"])
        listing = self.client.get(
            reverse("business-list"),
            {
                "organization_id": org_b.data["organization"]["id"],
                "tenant_id": org_b.data["organization"]["id"],
            },
        )
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual(listing.data["count"], 0)

        detail = self.client.get(reverse("business-detail", kwargs={"business_id": business_b_id}))
        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)

        patched = self.client.patch(
            reverse("business-detail", kwargs={"business_id": business_b_id}),
            {"name": "Hacked"},
            format="json",
        )
        self.assertEqual(patched.status_code, status.HTTP_404_NOT_FOUND)

        deleted = self.client.delete(
            reverse("business-detail", kwargs={"business_id": business_b_id})
        )
        self.assertEqual(deleted.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(Business.objects.filter(pk=business_b_id).exists())

    def test_client_supplied_organization_id_cannot_escape_tenant_scope(self):
        org_a = self._register("owner-a@example.com", "Organization A")
        org_b = self._register("owner-b@example.com", "Organization B")
        self._auth(org_a.data["access"])

        created = self.client.post(
            reverse("business-list"),
            {
                "name": "Should Stay In A",
                "vertical": BusinessVertical.SALON,
                "organization_id": org_b.data["organization"]["id"],
                "organization": org_b.data["organization"]["id"],
                "tenant_id": org_b.data["organization"]["id"],
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        business = Business.objects.get(pk=created.data["id"])
        self.assertEqual(str(business.organization_id), org_a.data["organization"]["id"])
        self.assertNotEqual(str(business.organization_id), org_b.data["organization"]["id"])

    def test_manager_cannot_create_business(self):
        self._register("owner@example.com", "Org A")
        owner = User.objects.get(email="owner@example.com")
        manager = User.objects.create_user(
            email="manager@example.com",
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
            {"email": "manager@example.com", "password": "StrongPass123"},
            format="json",
        )
        self._auth(login.data["access"])

        response = self.client.post(
            reverse("business-list"),
            {"name": "Manager Biz", "vertical": BusinessVertical.SALON},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
