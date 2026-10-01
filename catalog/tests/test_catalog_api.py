from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from businesses.models import BusinessVertical
from catalog.models import Service, ServiceCategory, ServiceLocation
from organizations.models import OrganizationMember, Role


class CatalogAPITestCase(APITestCase):
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

    def _create_location(self, business_id, name: str = "Downtown"):
        response = self.client.post(
            reverse("location-list", kwargs={"business_id": business_id}),
            {"name": name, "timezone": "Asia/Kolkata"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def _login_as_role(self, owner_email: str, role: str, member_email: str):
        owner = User.objects.get(email=owner_email)
        member = User.objects.create_user(
            email=member_email,
            password="StrongPass123",
            active_organization=owner.active_organization,
        )
        OrganizationMember.objects.create(
            organization=owner.active_organization,
            user=member,
            role=role,
        )
        login = self.client.post(
            reverse("auth-login"),
            {"email": member_email, "password": "StrongPass123"},
            format="json",
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self._auth(login.data["access"])
        return member


class ServiceCategoryAPITests(CatalogAPITestCase):
    def test_owner_crud_and_soft_delete(self):
        register = self._register("owner@example.com", "Org A")
        self._auth(register.data["access"])
        business = self._create_business()

        created = self.client.post(
            reverse("service-category-list", kwargs={"business_id": business["id"]}),
            {
                "name": "Hair",
                "display_order": 1,
                "organization_id": "ignored",
                "tenant_id": "ignored",
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(created.data["slug"], "hair")
        category_id = created.data["id"]

        listing = self.client.get(
            reverse("service-category-list", kwargs={"business_id": business["id"]})
        )
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual(listing.data["count"], 1)

        detail = self.client.get(
            reverse(
                "service-category-detail",
                kwargs={"business_id": business["id"], "category_id": category_id},
            )
        )
        self.assertEqual(detail.status_code, status.HTTP_200_OK)

        patched = self.client.patch(
            reverse(
                "service-category-detail",
                kwargs={"business_id": business["id"], "category_id": category_id},
            ),
            {"name": "Hair Care"},
            format="json",
        )
        self.assertEqual(patched.status_code, status.HTTP_200_OK)
        self.assertEqual(patched.data["name"], "Hair Care")

        deleted = self.client.delete(
            reverse(
                "service-category-detail",
                kwargs={"business_id": business["id"], "category_id": category_id},
            )
        )
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ServiceCategory.objects.filter(pk=category_id).exists())
        self.assertIsNotNone(ServiceCategory.all_objects.get(pk=category_id).deleted_at)

        listing = self.client.get(
            reverse("service-category-list", kwargs={"business_id": business["id"]})
        )
        self.assertEqual(listing.data["count"], 0)

    def test_category_tenant_isolation(self):
        org_a = self._register("owner-a@example.com", "Organization A")
        org_b = self._register("owner-b@example.com", "Organization B")

        self._auth(org_b.data["access"])
        business_b = self._create_business("Biz B")
        category_b = self.client.post(
            reverse("service-category-list", kwargs={"business_id": business_b["id"]}),
            {"name": "Color"},
            format="json",
        ).data

        self._auth(org_a.data["access"])
        listing = self.client.get(
            reverse("service-category-list", kwargs={"business_id": business_b["id"]})
        )
        self.assertEqual(listing.status_code, status.HTTP_404_NOT_FOUND)

        detail = self.client.get(
            reverse(
                "service-category-detail",
                kwargs={
                    "business_id": business_b["id"],
                    "category_id": category_b["id"],
                },
            )
        )
        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)

        patched = self.client.patch(
            reverse(
                "service-category-detail",
                kwargs={
                    "business_id": business_b["id"],
                    "category_id": category_b["id"],
                },
            ),
            {"name": "Hacked"},
            format="json",
        )
        self.assertEqual(patched.status_code, status.HTTP_404_NOT_FOUND)

        deleted = self.client.delete(
            reverse(
                "service-category-detail",
                kwargs={
                    "business_id": business_b["id"],
                    "category_id": category_b["id"],
                },
            )
        )
        self.assertEqual(deleted.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(ServiceCategory.objects.filter(pk=category_b["id"]).exists())


class ServiceAPITests(CatalogAPITestCase):
    def test_owner_crud_and_soft_delete(self):
        register = self._register("owner@example.com", "Org A")
        self._auth(register.data["access"])
        business = self._create_business()
        category = self.client.post(
            reverse("service-category-list", kwargs={"business_id": business["id"]}),
            {"name": "Hair"},
            format="json",
        ).data

        created = self.client.post(
            reverse("service-list", kwargs={"business_id": business["id"]}),
            {
                "name": "Haircut",
                "duration_minutes": 45,
                "price": "499.00",
                "currency": "INR",
                "category_id": category["id"],
                "organization_id": "ignored",
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(created.data["slug"], "haircut")
        self.assertEqual(created.data["duration_minutes"], 45)
        self.assertEqual(Decimal(created.data["price"]), Decimal("499.00"))
        service_id = created.data["id"]

        service = Service.objects.get(pk=service_id)
        self.assertEqual(str(service.organization_id), register.data["organization"]["id"])
        self.assertEqual(str(service.category_id), category["id"])

        listing = self.client.get(reverse("service-list", kwargs={"business_id": business["id"]}))
        self.assertEqual(listing.data["count"], 1)

        patched = self.client.patch(
            reverse(
                "service-detail",
                kwargs={"business_id": business["id"], "service_id": service_id},
            ),
            {"price": "549.50", "duration_minutes": 50},
            format="json",
        )
        self.assertEqual(patched.status_code, status.HTTP_200_OK)
        self.assertEqual(Decimal(patched.data["price"]), Decimal("549.50"))

        deleted = self.client.delete(
            reverse(
                "service-detail",
                kwargs={"business_id": business["id"], "service_id": service_id},
            )
        )
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Service.objects.filter(pk=service_id).exists())
        self.assertIsNotNone(Service.all_objects.get(pk=service_id).deleted_at)

    def test_category_must_belong_to_same_business(self):
        org_a = self._register("owner-a@example.com", "Organization A")
        org_b = self._register("owner-b@example.com", "Organization B")

        self._auth(org_b.data["access"])
        business_b = self._create_business("Biz B")
        category_b = self.client.post(
            reverse("service-category-list", kwargs={"business_id": business_b["id"]}),
            {"name": "Spa"},
            format="json",
        ).data

        self._auth(org_a.data["access"])
        business_a = self._create_business("Biz A")
        response = self.client.post(
            reverse("service-list", kwargs={"business_id": business_a["id"]}),
            {
                "name": "Massage",
                "duration_minutes": 60,
                "price": "999.00",
                "category_id": category_b["id"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_service_tenant_isolation(self):
        org_a = self._register("owner-a@example.com", "Organization A")
        org_b = self._register("owner-b@example.com", "Organization B")

        self._auth(org_b.data["access"])
        business_b = self._create_business("Biz B")
        service_b = self.client.post(
            reverse("service-list", kwargs={"business_id": business_b["id"]}),
            {"name": "Cut", "duration_minutes": 30, "price": "300.00"},
            format="json",
        ).data

        self._auth(org_a.data["access"])
        self.assertEqual(
            self.client.get(
                reverse("service-list", kwargs={"business_id": business_b["id"]})
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.get(
                reverse(
                    "service-detail",
                    kwargs={
                        "business_id": business_b["id"],
                        "service_id": service_b["id"],
                    },
                )
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.patch(
                reverse(
                    "service-detail",
                    kwargs={
                        "business_id": business_b["id"],
                        "service_id": service_b["id"],
                    },
                ),
                {"name": "Hacked"},
                format="json",
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.delete(
                reverse(
                    "service-detail",
                    kwargs={
                        "business_id": business_b["id"],
                        "service_id": service_b["id"],
                    },
                )
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertTrue(Service.objects.filter(pk=service_b["id"]).exists())

    def test_rejects_invalid_duration_and_price(self):
        register = self._register("owner@example.com", "Org A")
        self._auth(register.data["access"])
        business = self._create_business()

        bad_duration = self.client.post(
            reverse("service-list", kwargs={"business_id": business["id"]}),
            {"name": "Bad", "duration_minutes": 0, "price": "10.00"},
            format="json",
        )
        self.assertEqual(bad_duration.status_code, status.HTTP_400_BAD_REQUEST)

        bad_price = self.client.post(
            reverse("service-list", kwargs={"business_id": business["id"]}),
            {"name": "Bad", "duration_minutes": 30, "price": "-1.00"},
            format="json",
        )
        self.assertEqual(bad_price.status_code, status.HTTP_400_BAD_REQUEST)


class ServiceLocationAPITests(CatalogAPITestCase):
    def test_assign_list_update_and_remove(self):
        register = self._register("owner@example.com", "Org A")
        self._auth(register.data["access"])
        business = self._create_business()
        location = self._create_location(business["id"])
        service = self.client.post(
            reverse("service-list", kwargs={"business_id": business["id"]}),
            {"name": "Haircut", "duration_minutes": 45, "price": "499.00"},
            format="json",
        ).data

        assigned = self.client.post(
            reverse(
                "service-location-list",
                kwargs={"business_id": business["id"], "service_id": service["id"]},
            ),
            {
                "location_id": location["id"],
                "price": "450.00",
                "duration_minutes": 40,
                "organization_id": "ignored",
            },
            format="json",
        )
        self.assertEqual(assigned.status_code, status.HTTP_201_CREATED)
        self.assertEqual(str(assigned.data["location"]), location["id"])
        assignment_id = assigned.data["id"]

        listing = self.client.get(
            reverse(
                "service-location-list",
                kwargs={"business_id": business["id"], "service_id": service["id"]},
            )
        )
        self.assertEqual(listing.data["count"], 1)

        patched = self.client.patch(
            reverse(
                "service-location-detail",
                kwargs={
                    "business_id": business["id"],
                    "service_id": service["id"],
                    "service_location_id": assignment_id,
                },
            ),
            {"price": "475.00"},
            format="json",
        )
        self.assertEqual(patched.status_code, status.HTTP_200_OK)
        self.assertEqual(Decimal(patched.data["price"]), Decimal("475.00"))

        removed = self.client.delete(
            reverse(
                "service-location-detail",
                kwargs={
                    "business_id": business["id"],
                    "service_id": service["id"],
                    "service_location_id": assignment_id,
                },
            )
        )
        self.assertEqual(removed.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ServiceLocation.objects.filter(pk=assignment_id).exists())

    def test_duplicate_assignment_prevented(self):
        register = self._register("owner@example.com", "Org A")
        self._auth(register.data["access"])
        business = self._create_business()
        location = self._create_location(business["id"])
        service = self.client.post(
            reverse("service-list", kwargs={"business_id": business["id"]}),
            {"name": "Haircut", "duration_minutes": 45, "price": "499.00"},
            format="json",
        ).data

        first = self.client.post(
            reverse(
                "service-location-list",
                kwargs={"business_id": business["id"], "service_id": service["id"]},
            ),
            {"location_id": location["id"]},
            format="json",
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        duplicate = self.client.post(
            reverse(
                "service-location-list",
                kwargs={"business_id": business["id"], "service_id": service["id"]},
            ),
            {"location_id": location["id"]},
            format="json",
        )
        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_assign_cross_tenant_location(self):
        org_a = self._register("owner-a@example.com", "Organization A")
        org_b = self._register("owner-b@example.com", "Organization B")

        self._auth(org_b.data["access"])
        business_b = self._create_business("Biz B")
        location_b = self._create_location(business_b["id"], "Branch B")

        self._auth(org_a.data["access"])
        business_a = self._create_business("Biz A")
        service_a = self.client.post(
            reverse("service-list", kwargs={"business_id": business_a["id"]}),
            {"name": "Cut", "duration_minutes": 30, "price": "200.00"},
            format="json",
        ).data

        response = self.client.post(
            reverse(
                "service-location-list",
                kwargs={"business_id": business_a["id"], "service_id": service_a["id"]},
            ),
            {"location_id": location_b["id"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(ServiceLocation.objects.count(), 0)

    def test_cross_tenant_service_location_access_rejected(self):
        org_a = self._register("owner-a@example.com", "Organization A")
        org_b = self._register("owner-b@example.com", "Organization B")

        self._auth(org_b.data["access"])
        business_b = self._create_business("Biz B")
        location_b = self._create_location(business_b["id"])
        service_b = self.client.post(
            reverse("service-list", kwargs={"business_id": business_b["id"]}),
            {"name": "Cut", "duration_minutes": 30, "price": "200.00"},
            format="json",
        ).data
        assignment = self.client.post(
            reverse(
                "service-location-list",
                kwargs={"business_id": business_b["id"], "service_id": service_b["id"]},
            ),
            {"location_id": location_b["id"]},
            format="json",
        ).data

        self._auth(org_a.data["access"])
        self.assertEqual(
            self.client.get(
                reverse(
                    "service-location-list",
                    kwargs={
                        "business_id": business_b["id"],
                        "service_id": service_b["id"],
                    },
                )
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.patch(
                reverse(
                    "service-location-detail",
                    kwargs={
                        "business_id": business_b["id"],
                        "service_id": service_b["id"],
                        "service_location_id": assignment["id"],
                    },
                ),
                {"price": "1.00"},
                format="json",
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.delete(
                reverse(
                    "service-location-detail",
                    kwargs={
                        "business_id": business_b["id"],
                        "service_id": service_b["id"],
                        "service_location_id": assignment["id"],
                    },
                )
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertTrue(ServiceLocation.objects.filter(pk=assignment["id"]).exists())


class CatalogPermissionTests(CatalogAPITestCase):
    def test_manager_and_staff_can_read_but_not_write(self):
        self._register("owner@example.com", "Org A")
        # Use owner's token to seed data
        owner_login = self.client.post(
            reverse("auth-login"),
            {"email": "owner@example.com", "password": "StrongPass123"},
            format="json",
        )
        self._auth(owner_login.data["access"])
        business = self._create_business()
        category = self.client.post(
            reverse("service-category-list", kwargs={"business_id": business["id"]}),
            {"name": "Hair"},
            format="json",
        ).data
        service = self.client.post(
            reverse("service-list", kwargs={"business_id": business["id"]}),
            {"name": "Cut", "duration_minutes": 30, "price": "200.00"},
            format="json",
        ).data

        for role, email in (
            (Role.MANAGER, "manager@example.com"),
            (Role.STAFF, "staff@example.com"),
        ):
            self._login_as_role("owner@example.com", role, email)

            listing = self.client.get(
                reverse("service-list", kwargs={"business_id": business["id"]})
            )
            self.assertEqual(listing.status_code, status.HTTP_200_OK)
            self.assertEqual(listing.data["count"], 1)

            create_blocked = self.client.post(
                reverse("service-list", kwargs={"business_id": business["id"]}),
                {"name": "New", "duration_minutes": 20, "price": "100.00"},
                format="json",
            )
            self.assertEqual(create_blocked.status_code, status.HTTP_403_FORBIDDEN)

            patch_blocked = self.client.patch(
                reverse(
                    "service-detail",
                    kwargs={"business_id": business["id"], "service_id": service["id"]},
                ),
                {"name": "Nope"},
                format="json",
            )
            self.assertEqual(patch_blocked.status_code, status.HTTP_403_FORBIDDEN)

            category_create = self.client.post(
                reverse(
                    "service-category-list",
                    kwargs={"business_id": business["id"]},
                ),
                {"name": "Blocked"},
                format="json",
            )
            self.assertEqual(category_create.status_code, status.HTTP_403_FORBIDDEN)

            # Ensure seed category still readable
            self.assertEqual(
                self.client.get(
                    reverse(
                        "service-category-detail",
                        kwargs={
                            "business_id": business["id"],
                            "category_id": category["id"],
                        },
                    )
                ).status_code,
                status.HTTP_200_OK,
            )
