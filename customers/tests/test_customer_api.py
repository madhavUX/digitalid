from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from businesses.models import BusinessVertical
from customers.models import Customer, CustomerTag, CustomerTagAssignment
from organizations.models import OrganizationMember, Role


class CustomerAPITestCase(APITestCase):
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


class CustomerCRUDTests(CustomerAPITestCase):
    def test_owner_crud_search_pagination_soft_delete(self):
        register = self._register("owner@example.com", "Org A")
        self._auth(register.data["access"])
        business = self._create_business()

        created = self.client.post(
            reverse("customer-list", kwargs={"business_id": business["id"]}),
            {
                "first_name": "Ananya",
                "last_name": "Sharma",
                "phone": "+919876543210",
                "email": "Ananya@Example.com",
                "notes": "Prefers morning slots",
                "organization_id": "ignored",
                "tenant_id": "ignored",
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(created.data["first_name"], "Ananya")
        self.assertEqual(created.data["full_name"], "Ananya Sharma")
        self.assertEqual(created.data["email"], "ananya@example.com")
        self.assertEqual(created.data["total_visits"], 0)
        customer_id = created.data["id"]

        customer = Customer.objects.get(pk=customer_id)
        self.assertEqual(str(customer.organization_id), register.data["organization"]["id"])
        self.assertEqual(str(customer.business_id), business["id"])

        # Duplicate phone rejected
        dup = self.client.post(
            reverse("customer-list", kwargs={"business_id": business["id"]}),
            {
                "first_name": "Other",
                "phone": "+919876543210",
            },
            format="json",
        )
        self.assertEqual(dup.status_code, status.HTTP_400_BAD_REQUEST)

        # Invalid phone
        bad_phone = self.client.post(
            reverse("customer-list", kwargs={"business_id": business["id"]}),
            {"first_name": "Bad", "phone": "9876543210"},
            format="json",
        )
        self.assertEqual(bad_phone.status_code, status.HTTP_400_BAD_REQUEST)

        # Second customer for search/pagination
        self.client.post(
            reverse("customer-list", kwargs={"business_id": business["id"]}),
            {
                "first_name": "Ravi",
                "last_name": "Kumar",
                "phone": "+919811122233",
                "email": "ravi@example.com",
            },
            format="json",
        )

        listing = self.client.get(reverse("customer-list", kwargs={"business_id": business["id"]}))
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual(listing.data["count"], 2)
        self.assertIn("results", listing.data)

        search = self.client.get(
            reverse("customer-list", kwargs={"business_id": business["id"]}),
            {"search": "987654"},
        )
        self.assertEqual(search.status_code, status.HTTP_200_OK)
        self.assertEqual(search.data["count"], 1)
        self.assertEqual(search.data["results"][0]["first_name"], "Ananya")

        page = self.client.get(
            reverse("customer-list", kwargs={"business_id": business["id"]}),
            {"limit": 1, "offset": 0},
        )
        self.assertEqual(page.status_code, status.HTTP_200_OK)
        self.assertEqual(len(page.data["results"]), 1)
        self.assertEqual(page.data["count"], 2)

        detail = self.client.get(
            reverse(
                "customer-detail",
                kwargs={"business_id": business["id"], "customer_id": customer_id},
            )
        )
        self.assertEqual(detail.status_code, status.HTTP_200_OK)

        patched = self.client.patch(
            reverse(
                "customer-detail",
                kwargs={"business_id": business["id"], "customer_id": customer_id},
            ),
            {"notes": "VIP", "marketing_opt_in": True},
            format="json",
        )
        self.assertEqual(patched.status_code, status.HTTP_200_OK)
        self.assertEqual(patched.data["notes"], "VIP")
        self.assertTrue(patched.data["marketing_opt_in"])

        deleted = self.client.delete(
            reverse(
                "customer-detail",
                kwargs={"business_id": business["id"], "customer_id": customer_id},
            )
        )
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Customer.objects.filter(pk=customer_id).exists())
        soft = Customer.all_objects.get(pk=customer_id)
        self.assertIsNotNone(soft.deleted_at)

        # Phone reusable after soft delete
        recreate = self.client.post(
            reverse("customer-list", kwargs={"business_id": business["id"]}),
            {"first_name": "Ananya", "phone": "+919876543210"},
            format="json",
        )
        self.assertEqual(recreate.status_code, status.HTTP_201_CREATED)

    def test_customer_tenant_isolation(self):
        a = self._register("owner-a@example.com", "Org A")
        self._auth(a.data["access"])
        business_a = self._create_business("Salon A")
        created = self.client.post(
            reverse("customer-list", kwargs={"business_id": business_a["id"]}),
            {"first_name": "Priya", "phone": "+919900011122"},
            format="json",
        )
        customer_id = created.data["id"]

        b = self._register("owner-b@example.com", "Org B")
        self._auth(b.data["access"])
        business_b = self._create_business("Salon B")

        listing = self.client.get(
            reverse("customer-list", kwargs={"business_id": business_a["id"]})
        )
        self.assertEqual(listing.status_code, status.HTTP_404_NOT_FOUND)

        detail = self.client.get(
            reverse(
                "customer-detail",
                kwargs={"business_id": business_a["id"], "customer_id": customer_id},
            )
        )
        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)

        create_under_a = self.client.post(
            reverse("customer-list", kwargs={"business_id": business_a["id"]}),
            {"first_name": "Hack", "phone": "+919900099988"},
            format="json",
        )
        self.assertEqual(create_under_a.status_code, status.HTTP_404_NOT_FOUND)

        patch = self.client.patch(
            reverse(
                "customer-detail",
                kwargs={"business_id": business_a["id"], "customer_id": customer_id},
            ),
            {"notes": "nope"},
            format="json",
        )
        self.assertEqual(patch.status_code, status.HTTP_404_NOT_FOUND)

        delete = self.client.delete(
            reverse(
                "customer-detail",
                kwargs={"business_id": business_a["id"], "customer_id": customer_id},
            )
        )
        self.assertEqual(delete.status_code, status.HTTP_404_NOT_FOUND)

        # Cannot create with A customer phone under B using A's business id
        self.assertEqual(
            self.client.get(
                reverse("customer-list", kwargs={"business_id": business_b["id"]})
            ).data["count"],
            0,
        )


class CustomerTagTests(CustomerAPITestCase):
    def test_tag_crud_and_assignment(self):
        register = self._register("owner@example.com", "Org A")
        self._auth(register.data["access"])
        business = self._create_business()

        tag = self.client.post(
            reverse("customer-tag-list", kwargs={"business_id": business["id"]}),
            {"name": "VIP", "organization_id": "ignored"},
            format="json",
        )
        self.assertEqual(tag.status_code, status.HTTP_201_CREATED)
        tag_id = tag.data["id"]

        listing = self.client.get(
            reverse("customer-tag-list", kwargs={"business_id": business["id"]})
        )
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual(listing.data["count"], 1)

        patched = self.client.patch(
            reverse(
                "customer-tag-detail",
                kwargs={"business_id": business["id"], "tag_id": tag_id},
            ),
            {"name": "High Value"},
            format="json",
        )
        self.assertEqual(patched.status_code, status.HTTP_200_OK)
        self.assertEqual(patched.data["name"], "High Value")

        customer = self.client.post(
            reverse("customer-list", kwargs={"business_id": business["id"]}),
            {"first_name": "Neha", "phone": "+919700011122"},
            format="json",
        )
        customer_id = customer.data["id"]

        assigned = self.client.post(
            reverse(
                "customer-tag-assignment-list",
                kwargs={"business_id": business["id"], "customer_id": customer_id},
            ),
            {"tag_id": tag_id},
            format="json",
        )
        self.assertEqual(assigned.status_code, status.HTTP_201_CREATED)
        assignment_id = assigned.data["id"]
        self.assertEqual(assigned.data["tag"]["name"], "High Value")

        # Duplicate assignment
        dup = self.client.post(
            reverse(
                "customer-tag-assignment-list",
                kwargs={"business_id": business["id"], "customer_id": customer_id},
            ),
            {"tag_id": tag_id},
            format="json",
        )
        self.assertEqual(dup.status_code, status.HTTP_400_BAD_REQUEST)

        detail = self.client.get(
            reverse(
                "customer-detail",
                kwargs={"business_id": business["id"], "customer_id": customer_id},
            )
        )
        self.assertEqual(len(detail.data["tags"]), 1)

        filtered = self.client.get(
            reverse("customer-list", kwargs={"business_id": business["id"]}),
            {"tag_id": tag_id},
        )
        self.assertEqual(filtered.data["count"], 1)

        removed = self.client.delete(
            reverse(
                "customer-tag-assignment-detail",
                kwargs={
                    "business_id": business["id"],
                    "customer_id": customer_id,
                    "assignment_id": assignment_id,
                },
            )
        )
        self.assertEqual(removed.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(CustomerTagAssignment.objects.filter(pk=assignment_id).exists())

        deleted_tag = self.client.delete(
            reverse(
                "customer-tag-detail",
                kwargs={"business_id": business["id"], "tag_id": tag_id},
            )
        )
        self.assertEqual(deleted_tag.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(CustomerTag.objects.filter(pk=tag_id).exists())

    def test_tag_tenant_isolation_and_cross_business_assignment(self):
        a = self._register("owner-a@example.com", "Org A")
        self._auth(a.data["access"])
        business_a = self._create_business("Salon A")
        customer_a = self.client.post(
            reverse("customer-list", kwargs={"business_id": business_a["id"]}),
            {"first_name": "Asha", "phone": "+919711100001"},
            format="json",
        ).data
        tag_a = self.client.post(
            reverse("customer-tag-list", kwargs={"business_id": business_a["id"]}),
            {"name": "VIP"},
            format="json",
        ).data

        b = self._register("owner-b@example.com", "Org B")
        self._auth(b.data["access"])
        business_b = self._create_business("Salon B")
        customer_b = self.client.post(
            reverse("customer-list", kwargs={"business_id": business_b["id"]}),
            {"first_name": "Bina", "phone": "+919722200002"},
            format="json",
        ).data
        tag_b = self.client.post(
            reverse("customer-tag-list", kwargs={"business_id": business_b["id"]}),
            {"name": "VIP"},
            format="json",
        ).data

        # Cannot read A's tags
        tags = self.client.get(
            reverse("customer-tag-list", kwargs={"business_id": business_a["id"]})
        )
        self.assertEqual(tags.status_code, status.HTTP_404_NOT_FOUND)

        # Cannot assign B tag to A customer (customer path 404)
        assign_b_to_a = self.client.post(
            reverse(
                "customer-tag-assignment-list",
                kwargs={
                    "business_id": business_a["id"],
                    "customer_id": customer_a["id"],
                },
            ),
            {"tag_id": tag_b["id"]},
            format="json",
        )
        self.assertEqual(assign_b_to_a.status_code, status.HTTP_404_NOT_FOUND)

        # Cannot assign A tag to B customer
        assign_a_to_b = self.client.post(
            reverse(
                "customer-tag-assignment-list",
                kwargs={
                    "business_id": business_b["id"],
                    "customer_id": customer_b["id"],
                },
            ),
            {"tag_id": tag_a["id"]},
            format="json",
        )
        self.assertEqual(assign_a_to_b.status_code, status.HTTP_404_NOT_FOUND)

    def test_same_org_different_business_tag_assignment_rejected(self):
        register = self._register("owner@example.com", "Org A")
        self._auth(register.data["access"])
        business_1 = self._create_business("Salon 1")
        business_2 = self._create_business("Salon 2")

        customer = self.client.post(
            reverse("customer-list", kwargs={"business_id": business_1["id"]}),
            {"first_name": "Cara", "phone": "+919733300003"},
            format="json",
        ).data
        tag = self.client.post(
            reverse("customer-tag-list", kwargs={"business_id": business_2["id"]}),
            {"name": "Bridal"},
            format="json",
        ).data

        assign = self.client.post(
            reverse(
                "customer-tag-assignment-list",
                kwargs={
                    "business_id": business_1["id"],
                    "customer_id": customer["id"],
                },
            ),
            {"tag_id": tag["id"]},
            format="json",
        )
        self.assertEqual(assign.status_code, status.HTTP_404_NOT_FOUND)


class CustomerPermissionTests(CustomerAPITestCase):
    def test_manager_can_write_staff_cannot(self):
        self._register("owner@example.com", "Org A")
        self._auth(
            self.client.post(
                reverse("auth-login"),
                {"email": "owner@example.com", "password": "StrongPass123"},
                format="json",
            ).data["access"]
        )
        business = self._create_business()

        self._login_as_role("owner@example.com", Role.MANAGER, "manager@example.com")
        created = self.client.post(
            reverse("customer-list", kwargs={"business_id": business["id"]}),
            {"first_name": "Maya", "phone": "+919744400004"},
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        customer_id = created.data["id"]

        tag = self.client.post(
            reverse("customer-tag-list", kwargs={"business_id": business["id"]}),
            {"name": "Regular"},
            format="json",
        )
        self.assertEqual(tag.status_code, status.HTTP_201_CREATED)

        self._login_as_role("owner@example.com", Role.STAFF, "staff@example.com")
        listing = self.client.get(reverse("customer-list", kwargs={"business_id": business["id"]}))
        self.assertEqual(listing.status_code, status.HTTP_200_OK)

        write = self.client.post(
            reverse("customer-list", kwargs={"business_id": business["id"]}),
            {"first_name": "Nope", "phone": "+919755500005"},
            format="json",
        )
        self.assertEqual(write.status_code, status.HTTP_403_FORBIDDEN)

        patch = self.client.patch(
            reverse(
                "customer-detail",
                kwargs={"business_id": business["id"], "customer_id": customer_id},
            ),
            {"notes": "x"},
            format="json",
        )
        self.assertEqual(patch.status_code, status.HTTP_403_FORBIDDEN)

        tag_write = self.client.post(
            reverse("customer-tag-list", kwargs={"business_id": business["id"]}),
            {"name": "Blocked"},
            format="json",
        )
        self.assertEqual(tag_write.status_code, status.HTTP_403_FORBIDDEN)
