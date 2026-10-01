from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from organizations.models import Organization, OrganizationMember, Role
from organizations.services import (
    get_active_membership,
    list_organization_members,
    resolve_current_membership,
    user_can_access_organization,
)


class TenantIsolationTests(APITestCase):
    def _register(self, email: str, organization_name: str, password: str = "StrongPass123"):
        response = self.client.post(
            reverse("auth-register"),
            {
                "email": email,
                "password": password,
                "organization_name": organization_name,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response

    def test_defined_roles(self):
        self.assertEqual(
            set(Role.values),
            {Role.OWNER, Role.MANAGER, Role.STAFF},
        )
        self.assertNotIn("SUPER_ADMIN", Role.values)

    def test_organization_a_cannot_read_organization_b_members(self):
        org_a = self._register("owner-a@example.com", "Organization A")
        org_b = self._register("owner-b@example.com", "Organization B")

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {org_a.data['access']}")
        response = self.client.get(
            reverse("organization-members"),
            {
                "tenant_id": org_b.data["organization"]["id"],
                "organization_id": org_b.data["organization"]["id"],
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = {member["user"]["email"] for member in response.data}
        self.assertEqual(emails, {"owner-a@example.com"})
        self.assertNotIn("owner-b@example.com", emails)

    def test_organization_b_cannot_read_organization_a_current_organization(self):
        org_a = self._register("owner-a@example.com", "Organization A")
        org_b = self._register("owner-b@example.com", "Organization B")

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {org_b.data['access']}")
        response = self.client.get(
            reverse("organization-current"),
            {"organization_id": org_a.data["organization"]["id"]},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], org_b.data["organization"]["id"])
        self.assertNotEqual(response.data["id"], org_a.data["organization"]["id"])
        self.assertEqual(response.data["name"], "Organization B")

    def test_protected_example_ignores_foreign_tenant_id(self):
        org_a = self._register("owner-a@example.com", "Organization A")
        org_b = self._register("owner-b@example.com", "Organization B")

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {org_a.data['access']}")
        response = self.client.get(
            reverse("protected-example"),
            {"tenant_id": org_b.data["organization"]["id"]},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["organization_id"], org_a.data["organization"]["id"])
        self.assertEqual(response.data["organization_name"], "Organization A")
        self.assertNotEqual(response.data["organization_id"], org_b.data["organization"]["id"])

    def test_service_layer_denies_cross_tenant_membership(self):
        self._register("owner-a@example.com", "Organization A")
        self._register("owner-b@example.com", "Organization B")

        user_a = User.objects.get(email="owner-a@example.com")
        org_a = Organization.objects.get(name="Organization A")
        org_b = Organization.objects.get(name="Organization B")

        self.assertIsNotNone(get_active_membership(user=user_a, organization=org_a))
        self.assertIsNone(get_active_membership(user=user_a, organization=org_b))
        self.assertTrue(user_can_access_organization(user_a, org_a))
        self.assertFalse(user_can_access_organization(user_a, org_b))

        member_emails = {member.user.email for member in list_organization_members(org_a)}
        self.assertEqual(member_emails, {"owner-a@example.com"})

        current = resolve_current_membership(user_a)
        self.assertIsNotNone(current)
        self.assertEqual(current.organization_id, org_a.id)

    def test_manager_in_org_a_cannot_access_org_b(self):
        org_a = self._register("owner-a@example.com", "Organization A")
        org_b = self._register("owner-b@example.com", "Organization B")

        owner_a = User.objects.get(email="owner-a@example.com")
        manager = User.objects.create_user(
            email="manager-a@example.com",
            password="StrongPass123",
            active_organization=owner_a.active_organization,
        )
        OrganizationMember.objects.create(
            organization=owner_a.active_organization,
            user=manager,
            role=Role.MANAGER,
        )

        login = self.client.post(
            reverse("auth-login"),
            {"email": "manager-a@example.com", "password": "StrongPass123"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        members = self.client.get(
            reverse("organization-members"),
            {"organization_id": org_b.data["organization"]["id"]},
        )
        emails = {member["user"]["email"] for member in members.data}
        self.assertEqual(members.status_code, status.HTTP_200_OK)
        self.assertIn("owner-a@example.com", emails)
        self.assertIn("manager-a@example.com", emails)
        self.assertNotIn("owner-b@example.com", emails)

        example = self.client.get(reverse("protected-example"))
        self.assertEqual(example.data["organization_id"], org_a.data["organization"]["id"])
        self.assertEqual(example.data["role"], Role.MANAGER)

    def test_user_without_membership_cannot_use_protected_tenant_endpoints(self):
        user = User.objects.create_user(email="nomember@example.com", password="StrongPass123")
        login = self.client.post(
            reverse("auth-login"),
            {"email": user.email, "password": "StrongPass123"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        self.assertEqual(
            self.client.get(reverse("protected-example")).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.get(reverse("organization-members")).status_code,
            status.HTTP_403_FORBIDDEN,
        )
