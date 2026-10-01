from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from organizations.models import Organization, OrganizationMember, Role


class AuthenticationAPITests(APITestCase):
    def test_register_creates_user_organization_and_owner_membership(self):
        response = self.client.post(
            reverse("auth-register"),
            {
                "email": "Owner@Example.com",
                "password": "StrongPass123",
                "first_name": "Ada",
                "last_name": "Lovelace",
                "organization_name": "Ada Salon",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertEqual(response.data["user"]["email"], "owner@example.com")
        self.assertEqual(response.data["organization"]["name"], "Ada Salon")
        self.assertEqual(response.data["membership"]["role"], Role.OWNER)

        user = User.objects.get(email="owner@example.com")
        self.assertTrue(user.check_password("StrongPass123"))
        self.assertEqual(Organization.objects.count(), 1)
        membership = OrganizationMember.objects.get(user=user)
        self.assertEqual(membership.role, Role.OWNER)
        self.assertEqual(user.active_organization_id, membership.organization_id)

    def test_register_rejects_duplicate_email(self):
        payload = {
            "email": "same@example.com",
            "password": "StrongPass123",
            "organization_name": "First Org",
        }
        self.client.post(reverse("auth-register"), payload, format="json")
        response = self.client.post(
            reverse("auth-register"),
            {**payload, "organization_name": "Second Org"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(User.objects.filter(email="same@example.com").count(), 1)
        self.assertEqual(Organization.objects.count(), 1)

    def test_register_rejects_weak_password(self):
        response = self.client.post(
            reverse("auth-register"),
            {
                "email": "weak@example.com",
                "password": "123",
                "organization_name": "Weak Org",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(User.objects.filter(email="weak@example.com").exists())

    def test_register_requires_organization_name(self):
        response = self.client.post(
            reverse("auth-register"),
            {
                "email": "noorg@example.com",
                "password": "StrongPass123",
                "organization_name": "   ",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_returns_tokens_and_tenant_context(self):
        self.client.post(
            reverse("auth-register"),
            {
                "email": "login@example.com",
                "password": "StrongPass123",
                "organization_name": "Login Org",
            },
            format="json",
        )

        response = self.client.post(
            reverse("auth-login"),
            {"email": "Login@Example.com", "password": "StrongPass123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertEqual(response.data["organization"]["name"], "Login Org")
        self.assertEqual(response.data["membership"]["role"], Role.OWNER)

    def test_login_rejects_invalid_credentials(self):
        response = self.client.post(
            reverse("auth-login"),
            {"email": "missing@example.com", "password": "wrong-password"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_requires_authentication(self):
        response = self.client.get(reverse("auth-me"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_returns_authenticated_user_and_organization(self):
        register = self.client.post(
            reverse("auth-register"),
            {
                "email": "me@example.com",
                "password": "StrongPass123",
                "organization_name": "Me Org",
            },
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {register.data['access']}")

        response = self.client.get(reverse("auth-me"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"]["email"], "me@example.com")
        self.assertEqual(response.data["organization"]["name"], "Me Org")
        self.assertEqual(response.data["membership"]["role"], Role.OWNER)

    def test_token_refresh(self):
        register = self.client.post(
            reverse("auth-register"),
            {
                "email": "refresh@example.com",
                "password": "StrongPass123",
                "organization_name": "Refresh Org",
            },
            format="json",
        )

        response = self.client.post(
            reverse("auth-refresh"),
            {"refresh": register.data["refresh"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)

    def test_protected_example_requires_authentication(self):
        response = self.client.get(reverse("protected-example"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_protected_example_returns_server_side_tenant_context(self):
        register = self.client.post(
            reverse("auth-register"),
            {
                "email": "protected@example.com",
                "password": "StrongPass123",
                "organization_name": "Protected Org",
            },
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {register.data['access']}")

        response = self.client.get(
            reverse("protected-example"),
            {"tenant_id": "should-be-ignored", "organization_id": "should-be-ignored"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["organization_id"], register.data["organization"]["id"])
        self.assertEqual(response.data["organization_name"], "Protected Org")
        self.assertEqual(response.data["role"], Role.OWNER)
