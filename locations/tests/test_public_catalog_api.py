from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from businesses.models import BusinessVertical
from catalog.models import Service, ServiceCategory
from locations.models import Location


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
        },
    }
)
class PublicCatalogAPITestCase(APITestCase):
    def setUp(self):
        super().setUp()
        self.public = APIClient()

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

    def _create_location(self, business_id, name: str = "Downtown", **extra):
        payload = {"name": name, "timezone": "Asia/Kolkata", **extra}
        response = self.client.post(
            reverse("location-list", kwargs={"business_id": business_id}),
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def _create_category(self, business_id, name: str = "Hair", display_order: int = 1):
        response = self.client.post(
            reverse("service-category-list", kwargs={"business_id": business_id}),
            {"name": name, "display_order": display_order},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def _create_service(
        self,
        business_id,
        *,
        name: str = "Haircut",
        duration_minutes: int = 45,
        price: str = "499.00",
        category_id=None,
        is_bookable_online: bool = True,
        currency: str = "INR",
        description: str = "Classic cut",
    ):
        payload = {
            "name": name,
            "duration_minutes": duration_minutes,
            "price": price,
            "currency": currency,
            "description": description,
            "is_bookable_online": is_bookable_online,
        }
        if category_id is not None:
            payload["category_id"] = category_id
        response = self.client.post(
            reverse("service-list", kwargs={"business_id": business_id}),
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def _assign_service_location(
        self,
        business_id,
        service_id,
        location_id,
        *,
        duration_minutes=None,
        price=None,
        currency="",
    ):
        payload = {"location_id": location_id}
        if duration_minutes is not None:
            payload["duration_minutes"] = duration_minutes
        if price is not None:
            payload["price"] = price
        if currency:
            payload["currency"] = currency
        response = self.client.post(
            reverse(
                "service-location-list",
                kwargs={"business_id": business_id, "service_id": service_id},
            ),
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def _seed_public_catalog(self, *, owner_email="owner@example.com", org_name="Org A"):
        register = self._register(owner_email, org_name)
        self._auth(register.data["access"])
        business = self._create_business()
        location = self._create_location(
            business["id"],
            name="Downtown",
            address_line1="12 MG Road",
            city="Bengaluru",
            phone="+918012345678",
        )
        category = self._create_category(business["id"], name="Hair", display_order=1)
        empty_category = self._create_category(business["id"], name="Unused", display_order=9)
        service = self._create_service(
            business["id"],
            category_id=category["id"],
            duration_minutes=45,
            price="499.00",
        )
        self._assign_service_location(
            business["id"],
            service["id"],
            location["id"],
            duration_minutes=30,
            price="450.00",
            currency="INR",
        )
        return {
            "token": register.data["access"],
            "business": business,
            "location": location,
            "category": category,
            "empty_category": empty_category,
            "service": service,
        }


class PublicLocationDetailTests(PublicCatalogAPITestCase):
    def test_active_public_location_returned(self):
        ctx = self._seed_public_catalog()
        response = self.public.get(
            reverse("public-location-detail", kwargs={"slug": ctx["location"]["slug"]})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["slug"], ctx["location"]["slug"])
        self.assertEqual(response.data["name"], "Downtown")
        self.assertEqual(response.data["timezone"], "Asia/Kolkata")
        self.assertEqual(response.data["phone"], "+918012345678")
        self.assertEqual(response.data["address"]["city"], "Bengaluru")
        self.assertEqual(response.data["business"]["name"], "Ada Salon")
        self.assertEqual(response.data["id"], ctx["location"]["id"])
        self.assertNotIn("organization", response.data)
        self.assertNotIn("organization_id", response.data)
        self.assertNotIn("created_by", response.data)
        self.assertNotIn("deleted_at", response.data)
        cache_control = response.get("Cache-Control", "")
        self.assertIn("max-age=60", cache_control)
        self.assertIn("public", cache_control)

    def test_inactive_and_deleted_location_rejected(self):
        ctx = self._seed_public_catalog()
        slug = ctx["location"]["slug"]
        Location.objects.filter(pk=ctx["location"]["id"]).update(is_active=False)
        inactive = self.public.get(reverse("public-location-detail", kwargs={"slug": slug}))
        self.assertEqual(inactive.status_code, status.HTTP_404_NOT_FOUND)

        Location.objects.filter(pk=ctx["location"]["id"]).update(is_active=True)
        location = Location.objects.get(pk=ctx["location"]["id"])
        location.soft_delete()
        deleted = self.public.get(reverse("public-location-detail", kwargs={"slug": slug}))
        self.assertEqual(deleted.status_code, status.HTTP_404_NOT_FOUND)

    def test_invalid_slug_returns_404(self):
        response = self.public.get(
            reverse("public-location-detail", kwargs={"slug": "does-not-exist"})
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_ambiguous_slug_returns_404(self):
        ctx_a = self._seed_public_catalog(owner_email="a@example.com", org_name="Org A")
        register_b = self._register("b@example.com", "Org B")
        self._auth(register_b.data["access"])
        business_b = self._create_business("Other Salon")
        location_b = self._create_location(business_b["id"], name="Downtown")
        self.assertEqual(location_b["slug"], ctx_a["location"]["slug"])

        response = self.public.get(
            reverse("public-location-detail", kwargs={"slug": ctx_a["location"]["slug"]})
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_organization_id_query_ignored(self):
        ctx = self._seed_public_catalog()
        response = self.public.get(
            reverse("public-location-detail", kwargs={"slug": ctx["location"]["slug"]}),
            {"organization_id": "00000000-0000-0000-0000-000000000099", "tenant_id": "x"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], ctx["location"]["id"])


class PublicServicesTests(PublicCatalogAPITestCase):
    def test_services_list_and_effective_overrides(self):
        ctx = self._seed_public_catalog()
        response = self.public.get(
            reverse("public-location-services", kwargs={"slug": ctx["location"]["slug"]})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        service = response.data["results"][0]
        self.assertEqual(service["slug"], ctx["service"]["slug"])
        self.assertEqual(service["duration_minutes"], 30)
        self.assertEqual(service["price"], "450.00")
        self.assertEqual(service["currency"], "INR")
        self.assertEqual(service["category"]["name"], "Hair")
        self.assertEqual(service["id"], ctx["service"]["id"])
        self.assertNotIn("buffer_before_minutes", service)
        self.assertNotIn("organization_id", service)
        self.assertNotIn("created_by", service)

    def test_excludes_inactive_deleted_unassigned_and_offline(self):
        ctx = self._seed_public_catalog()
        business_id = ctx["business"]["id"]
        location_id = ctx["location"]["id"]

        inactive = self._create_service(business_id, name="Inactive")
        self._assign_service_location(business_id, inactive["id"], location_id)
        Service.objects.filter(pk=inactive["id"]).update(is_active=False)

        offline = self._create_service(business_id, name="Offline", is_bookable_online=False)
        self._assign_service_location(business_id, offline["id"], location_id)

        deleted = self._create_service(business_id, name="Deleted")
        self._assign_service_location(business_id, deleted["id"], location_id)
        Service.objects.get(pk=deleted["id"]).soft_delete()

        other_location = self._create_location(business_id, name="Uptown")
        elsewhere = self._create_service(business_id, name="Elsewhere")
        self._assign_service_location(business_id, elsewhere["id"], other_location["id"])

        response = self.public.get(
            reverse("public-location-services", kwargs={"slug": ctx["location"]["slug"]})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        slugs = {row["slug"] for row in response.data["results"]}
        self.assertEqual(slugs, {ctx["service"]["slug"]})

    def test_service_detail_by_slug_and_id(self):
        ctx = self._seed_public_catalog()
        by_slug = self.public.get(
            reverse(
                "public-location-service-detail",
                kwargs={
                    "slug": ctx["location"]["slug"],
                    "service_identifier": ctx["service"]["slug"],
                },
            )
        )
        self.assertEqual(by_slug.status_code, status.HTTP_200_OK)
        self.assertEqual(by_slug.data["name"], "Haircut")
        self.assertEqual(by_slug.data["duration_minutes"], 30)

        by_id = self.public.get(
            reverse(
                "public-location-service-detail",
                kwargs={
                    "slug": ctx["location"]["slug"],
                    "service_identifier": ctx["service"]["id"],
                },
            )
        )
        self.assertEqual(by_id.status_code, status.HTTP_200_OK)
        self.assertEqual(by_id.data["id"], ctx["service"]["id"])

    def test_service_not_at_location_404(self):
        ctx = self._seed_public_catalog()
        other_location = self._create_location(ctx["business"]["id"], name="Uptown")
        elsewhere = self._create_service(ctx["business"]["id"], name="Elsewhere")
        self._assign_service_location(ctx["business"]["id"], elsewhere["id"], other_location["id"])
        response = self.public.get(
            reverse(
                "public-location-service-detail",
                kwargs={
                    "slug": ctx["location"]["slug"],
                    "service_identifier": elsewhere["slug"],
                },
            )
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_service_list_avoids_n_plus_one(self):
        ctx = self._seed_public_catalog()
        business_id = ctx["business"]["id"]
        location_id = ctx["location"]["id"]
        for index in range(8):
            service = self._create_service(business_id, name=f"Extra {index}")
            self._assign_service_location(business_id, service["id"], location_id)

        url = reverse("public-location-services", kwargs={"slug": ctx["location"]["slug"]})
        with CaptureQueriesContext(connection) as ctx_queries:
            response = self.public.get(url, {"limit": 50})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data["count"], 9)
        self.assertLessEqual(len(ctx_queries), 8)


class PublicCategoriesTests(PublicCatalogAPITestCase):
    def test_categories_with_public_services_only(self):
        ctx = self._seed_public_catalog()
        response = self.public.get(
            reverse("public-location-categories", kwargs={"slug": ctx["location"]["slug"]})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [row["name"] for row in response.data["results"]]
        self.assertEqual(names, ["Hair"])
        self.assertNotIn("Unused", names)
        self.assertNotIn("id", response.data["results"][0])
        self.assertNotIn("organization_id", response.data["results"][0])

    def test_deleted_category_excluded(self):
        ctx = self._seed_public_catalog()
        ServiceCategory.objects.get(pk=ctx["category"]["id"]).soft_delete()
        response = self.public.get(
            reverse("public-location-categories", kwargs={"slug": ctx["location"]["slug"]})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)


class PublicCatalogPrivacyTests(PublicCatalogAPITestCase):
    def test_no_enumeration_endpoint(self):
        response = self.public.get("/api/v1/public/locations/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cross_tenant_service_slug_isolated(self):
        ctx_a = self._seed_public_catalog(owner_email="a@example.com", org_name="Org A")
        register_b = self._register("b@example.com", "Org B")
        self._auth(register_b.data["access"])
        business_b = self._create_business("Salon B")
        location_b = self._create_location(business_b["id"], name="Branch")
        service_b = self._create_service(business_b["id"], name="Haircut")
        self._assign_service_location(business_b["id"], service_b["id"], location_b["id"])

        # Same service slug under B must not resolve via A's location.
        response = self.public.get(
            reverse(
                "public-location-service-detail",
                kwargs={
                    "slug": ctx_a["location"]["slug"],
                    "service_identifier": service_b["slug"],
                },
            )
        )
        # A's location has its own haircut; slug may match A's service.
        # Use B's unique name instead.
        unique = self._create_service(business_b["id"], name="Unique B Only")
        self._assign_service_location(business_b["id"], unique["id"], location_b["id"])
        missing = self.public.get(
            reverse(
                "public-location-service-detail",
                kwargs={
                    "slug": ctx_a["location"]["slug"],
                    "service_identifier": unique["slug"],
                },
            )
        )
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], ctx_a["service"]["id"])
