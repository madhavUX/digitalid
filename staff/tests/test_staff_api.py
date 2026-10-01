from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from businesses.models import BusinessVertical
from organizations.models import OrganizationMember, Role
from staff.models import StaffProfile, StaffService


class StaffAPITestCase(APITestCase):
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

    def _create_service(self, business_id, name: str = "Haircut"):
        response = self.client.post(
            reverse("service-list", kwargs={"business_id": business_id}),
            {"name": name, "duration_minutes": 45, "price": "499.00"},
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


class StaffProfileAPITests(StaffAPITestCase):
    def test_owner_crud_and_soft_delete(self):
        register = self._register("owner@example.com", "Org A")
        self._auth(register.data["access"])
        business = self._create_business()
        location = self._create_location(business["id"])

        created = self.client.post(
            reverse("staff-list", kwargs={"business_id": business["id"]}),
            {
                "display_name": "Priya",
                "location_id": location["id"],
                "title": "Senior Stylist",
                "organization_id": "ignored",
                "tenant_id": "ignored",
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(created.data["display_name"], "Priya")
        self.assertTrue(created.data["is_bookable"])
        staff_id = created.data["id"]

        profile = StaffProfile.objects.get(pk=staff_id)
        self.assertEqual(str(profile.organization_id), register.data["organization"]["id"])
        self.assertEqual(str(profile.location_id), location["id"])

        listing = self.client.get(reverse("staff-list", kwargs={"business_id": business["id"]}))
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual(listing.data["count"], 1)

        patched = self.client.patch(
            reverse("staff-detail", kwargs={"business_id": business["id"], "staff_id": staff_id}),
            {"title": "Lead Stylist", "is_bookable": False},
            format="json",
        )
        self.assertEqual(patched.status_code, status.HTTP_200_OK)
        self.assertEqual(patched.data["title"], "Lead Stylist")
        self.assertFalse(patched.data["is_bookable"])

        deleted = self.client.delete(
            reverse("staff-detail", kwargs={"business_id": business["id"], "staff_id": staff_id})
        )
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(StaffProfile.objects.filter(pk=staff_id).exists())
        self.assertIsNotNone(StaffProfile.all_objects.get(pk=staff_id).deleted_at)

    def test_location_must_belong_to_same_business(self):
        org_a = self._register("owner-a@example.com", "Organization A")
        org_b = self._register("owner-b@example.com", "Organization B")

        self._auth(org_b.data["access"])
        business_b = self._create_business("Biz B")
        location_b = self._create_location(business_b["id"], "Branch B")

        self._auth(org_a.data["access"])
        business_a = self._create_business("Biz A")
        response = self.client.post(
            reverse("staff-list", kwargs={"business_id": business_a["id"]}),
            {"display_name": "Priya", "location_id": location_b["id"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_staff_tenant_isolation(self):
        org_a = self._register("owner-a@example.com", "Organization A")
        org_b = self._register("owner-b@example.com", "Organization B")

        self._auth(org_b.data["access"])
        business_b = self._create_business("Biz B")
        location_b = self._create_location(business_b["id"])
        staff_b = self.client.post(
            reverse("staff-list", kwargs={"business_id": business_b["id"]}),
            {"display_name": "Ravi", "location_id": location_b["id"]},
            format="json",
        ).data

        self._auth(org_a.data["access"])
        self.assertEqual(
            self.client.get(
                reverse("staff-list", kwargs={"business_id": business_b["id"]})
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.get(
                reverse(
                    "staff-detail",
                    kwargs={"business_id": business_b["id"], "staff_id": staff_b["id"]},
                )
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.patch(
                reverse(
                    "staff-detail",
                    kwargs={"business_id": business_b["id"], "staff_id": staff_b["id"]},
                ),
                {"display_name": "Hacked"},
                format="json",
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.delete(
                reverse(
                    "staff-detail",
                    kwargs={"business_id": business_b["id"], "staff_id": staff_b["id"]},
                )
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertTrue(StaffProfile.objects.filter(pk=staff_b["id"]).exists())

    def test_optional_user_must_be_org_member_and_unique(self):
        register = self._register("owner@example.com", "Org A")
        self._auth(register.data["access"])
        business = self._create_business()
        location = self._create_location(business["id"])
        owner = User.objects.get(email="owner@example.com")

        created = self.client.post(
            reverse("staff-list", kwargs={"business_id": business["id"]}),
            {
                "display_name": "Owner As Staff",
                "location_id": location["id"],
                "user_id": str(owner.id),
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(str(created.data["user"]), str(owner.id))

        duplicate = self.client.post(
            reverse("staff-list", kwargs={"business_id": business["id"]}),
            {
                "display_name": "Duplicate",
                "location_id": location["id"],
                "user_id": str(owner.id),
            },
            format="json",
        )
        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)

        outsider = User.objects.create_user(email="outsider@example.com", password="StrongPass123")
        bad_user = self.client.post(
            reverse("staff-list", kwargs={"business_id": business["id"]}),
            {
                "display_name": "Outsider",
                "location_id": location["id"],
                "user_id": str(outsider.id),
            },
            format="json",
        )
        self.assertEqual(bad_user.status_code, status.HTTP_400_BAD_REQUEST)


class StaffServiceAPITests(StaffAPITestCase):
    def test_assign_update_remove_and_duplicate(self):
        register = self._register("owner@example.com", "Org A")
        self._auth(register.data["access"])
        business = self._create_business()
        location = self._create_location(business["id"])
        service = self._create_service(business["id"])
        staff = self.client.post(
            reverse("staff-list", kwargs={"business_id": business["id"]}),
            {"display_name": "Priya", "location_id": location["id"]},
            format="json",
        ).data

        assigned = self.client.post(
            reverse(
                "staff-service-list",
                kwargs={"business_id": business["id"], "staff_id": staff["id"]},
            ),
            {
                "service_id": service["id"],
                "duration_minutes": 40,
                "price": "450.00",
                "organization_id": "ignored",
            },
            format="json",
        )
        self.assertEqual(assigned.status_code, status.HTTP_201_CREATED)
        assignment_id = assigned.data["id"]
        self.assertEqual(Decimal(assigned.data["price"]), Decimal("450.00"))

        listing = self.client.get(
            reverse(
                "staff-service-list",
                kwargs={"business_id": business["id"], "staff_id": staff["id"]},
            )
        )
        self.assertEqual(listing.data["count"], 1)

        patched = self.client.patch(
            reverse(
                "staff-service-detail",
                kwargs={
                    "business_id": business["id"],
                    "staff_id": staff["id"],
                    "staff_service_id": assignment_id,
                },
            ),
            {"price": "475.00"},
            format="json",
        )
        self.assertEqual(patched.status_code, status.HTTP_200_OK)
        self.assertEqual(Decimal(patched.data["price"]), Decimal("475.00"))

        duplicate = self.client.post(
            reverse(
                "staff-service-list",
                kwargs={"business_id": business["id"], "staff_id": staff["id"]},
            ),
            {"service_id": service["id"]},
            format="json",
        )
        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)

        removed = self.client.delete(
            reverse(
                "staff-service-detail",
                kwargs={
                    "business_id": business["id"],
                    "staff_id": staff["id"],
                    "staff_service_id": assignment_id,
                },
            )
        )
        self.assertEqual(removed.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(StaffService.objects.filter(pk=assignment_id).exists())

    def test_cannot_assign_cross_tenant_service(self):
        org_a = self._register("owner-a@example.com", "Organization A")
        org_b = self._register("owner-b@example.com", "Organization B")

        self._auth(org_b.data["access"])
        business_b = self._create_business("Biz B")
        service_b = self._create_service(business_b["id"], "Cut B")

        self._auth(org_a.data["access"])
        business_a = self._create_business("Biz A")
        location_a = self._create_location(business_a["id"])
        staff_a = self.client.post(
            reverse("staff-list", kwargs={"business_id": business_a["id"]}),
            {"display_name": "Priya", "location_id": location_a["id"]},
            format="json",
        ).data

        response = self.client.post(
            reverse(
                "staff-service-list",
                kwargs={"business_id": business_a["id"], "staff_id": staff_a["id"]},
            ),
            {"service_id": service_b["id"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(StaffService.objects.count(), 0)

    def test_cross_tenant_staff_service_access_rejected(self):
        org_a = self._register("owner-a@example.com", "Organization A")
        org_b = self._register("owner-b@example.com", "Organization B")

        self._auth(org_b.data["access"])
        business_b = self._create_business("Biz B")
        location_b = self._create_location(business_b["id"])
        service_b = self._create_service(business_b["id"])
        staff_b = self.client.post(
            reverse("staff-list", kwargs={"business_id": business_b["id"]}),
            {"display_name": "Ravi", "location_id": location_b["id"]},
            format="json",
        ).data
        assignment = self.client.post(
            reverse(
                "staff-service-list",
                kwargs={"business_id": business_b["id"], "staff_id": staff_b["id"]},
            ),
            {"service_id": service_b["id"]},
            format="json",
        ).data

        self._auth(org_a.data["access"])
        self.assertEqual(
            self.client.get(
                reverse(
                    "staff-service-list",
                    kwargs={"business_id": business_b["id"], "staff_id": staff_b["id"]},
                )
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.patch(
                reverse(
                    "staff-service-detail",
                    kwargs={
                        "business_id": business_b["id"],
                        "staff_id": staff_b["id"],
                        "staff_service_id": assignment["id"],
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
                    "staff-service-detail",
                    kwargs={
                        "business_id": business_b["id"],
                        "staff_id": staff_b["id"],
                        "staff_service_id": assignment["id"],
                    },
                )
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertTrue(StaffService.objects.filter(pk=assignment["id"]).exists())


class StaffPermissionTests(StaffAPITestCase):
    def test_manager_can_write_staff_cannot(self):
        self._register("owner@example.com", "Org A")
        owner_login = self.client.post(
            reverse("auth-login"),
            {"email": "owner@example.com", "password": "StrongPass123"},
            format="json",
        )
        self._auth(owner_login.data["access"])
        business = self._create_business()
        location = self._create_location(business["id"])
        service = self._create_service(business["id"])
        staff = self.client.post(
            reverse("staff-list", kwargs={"business_id": business["id"]}),
            {"display_name": "Priya", "location_id": location["id"]},
            format="json",
        ).data

        # Manager can read and write
        self._login_as_role("owner@example.com", Role.MANAGER, "manager@example.com")
        listing = self.client.get(reverse("staff-list", kwargs={"business_id": business["id"]}))
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual(listing.data["count"], 1)

        create = self.client.post(
            reverse("staff-list", kwargs={"business_id": business["id"]}),
            {"display_name": "Manager Hire", "location_id": location["id"]},
            format="json",
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED)

        assign = self.client.post(
            reverse(
                "staff-service-list",
                kwargs={"business_id": business["id"], "staff_id": staff["id"]},
            ),
            {"service_id": service["id"]},
            format="json",
        )
        self.assertEqual(assign.status_code, status.HTTP_201_CREATED)

        # Staff can read but not write
        self._login_as_role("owner@example.com", Role.STAFF, "staffuser@example.com")
        self.assertEqual(
            self.client.get(
                reverse("staff-list", kwargs={"business_id": business["id"]})
            ).status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            self.client.post(
                reverse("staff-list", kwargs={"business_id": business["id"]}),
                {"display_name": "Blocked", "location_id": location["id"]},
                format="json",
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.patch(
                reverse(
                    "staff-detail",
                    kwargs={"business_id": business["id"], "staff_id": staff["id"]},
                ),
                {"display_name": "Nope"},
                format="json",
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
