from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from businesses.models import BusinessVertical
from catalog.models import Service
from locations.models import Location
from staff.models import StaffProfile, Weekday


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
class PublicStaffAPITestCase(APITestCase):
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

    def _create_location(self, business_id, name: str = "Downtown"):
        response = self.client.post(
            reverse("location-list", kwargs={"business_id": business_id}),
            {"name": name, "timezone": "Asia/Kolkata"},
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
        is_bookable_online: bool = True,
    ):
        response = self.client.post(
            reverse("service-list", kwargs={"business_id": business_id}),
            {
                "name": name,
                "duration_minutes": duration_minutes,
                "price": price,
                "is_bookable_online": is_bookable_online,
            },
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
    ):
        payload = {"location_id": location_id}
        if duration_minutes is not None:
            payload["duration_minutes"] = duration_minutes
        if price is not None:
            payload["price"] = price
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

    def _create_staff(
        self,
        business_id,
        location_id,
        display_name: str = "Priya",
        *,
        title: str = "Stylist",
        bio: str = "Cuts and color",
        photo_url: str = "https://cdn.example.com/priya.jpg",
        is_bookable: bool = True,
    ):
        response = self.client.post(
            reverse("staff-list", kwargs={"business_id": business_id}),
            {
                "display_name": display_name,
                "location_id": location_id,
                "title": title,
                "bio": bio,
                "photo_url": photo_url,
                "is_bookable": is_bookable,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def _assign_staff_service(
        self,
        business_id,
        staff_id,
        service_id,
        *,
        duration_minutes=None,
        price=None,
    ):
        payload = {"service_id": service_id}
        if duration_minutes is not None:
            payload["duration_minutes"] = duration_minutes
        if price is not None:
            payload["price"] = price
        response = self.client.post(
            reverse(
                "staff-service-list",
                kwargs={"business_id": business_id, "staff_id": staff_id},
            ),
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def _create_availability(self, business_id, staff_id, location_id):
        response = self.client.post(
            reverse(
                "staff-availability-list",
                kwargs={"business_id": business_id, "staff_id": staff_id},
            ),
            {
                "location_id": location_id,
                "weekday": Weekday.MONDAY,
                "starts_at": "09:00:00",
                "ends_at": "17:00:00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def _seed(self, *, owner_email="owner@example.com", org_name="Org A"):
        register = self._register(owner_email, org_name)
        self._auth(register.data["access"])
        business = self._create_business()
        location = self._create_location(business["id"])
        service = self._create_service(business["id"])
        self._assign_service_location(
            business["id"],
            service["id"],
            location["id"],
            duration_minutes=40,
            price="450.00",
        )
        staff = self._create_staff(business["id"], location["id"])
        self._assign_staff_service(
            business["id"],
            staff["id"],
            service["id"],
            duration_minutes=35,
            price="475.00",
        )
        self._create_availability(business["id"], staff["id"], location["id"])
        return {
            "business": business,
            "location": location,
            "service": service,
            "staff": staff,
        }

    def _list(self, slug, **params):
        return self.public.get(
            reverse("public-location-staff", kwargs={"slug": slug}),
            params,
        )


class PublicStaffListingTests(PublicStaffAPITestCase):
    def test_active_bookable_staff_appears_with_services(self):
        ctx = self._seed()
        response = self._list(ctx["location"]["slug"])
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        row = response.data["results"][0]
        self.assertEqual(row["id"], ctx["staff"]["id"])
        self.assertEqual(row["display_name"], "Priya")
        self.assertEqual(row["title"], "Stylist")
        self.assertEqual(row["bio"], "Cuts and color")
        self.assertEqual(row["photo_url"], "https://cdn.example.com/priya.jpg")
        self.assertEqual(len(row["services"]), 1)
        service = row["services"][0]
        self.assertEqual(service["id"], ctx["service"]["id"])
        self.assertEqual(service["duration_minutes"], 35)
        self.assertEqual(service["price"], "475.00")
        self.assertEqual(service["currency"], "INR")
        self.assertNotIn("user", row)
        self.assertNotIn("user_id", row)
        self.assertNotIn("organization_id", row)
        self.assertNotIn("business_id", row)
        self.assertNotIn("created_by", row)
        self.assertNotIn("is_bookable", row)
        cache_control = response.get("Cache-Control", "")
        self.assertIn("max-age=60", cache_control)

    def test_excludes_inactive_deleted_non_bookable(self):
        ctx = self._seed()
        business_id = ctx["business"]["id"]
        location_id = ctx["location"]["id"]
        service_id = ctx["service"]["id"]

        inactive = self._create_staff(business_id, location_id, "Inactive")
        self._assign_staff_service(business_id, inactive["id"], service_id)
        self._create_availability(business_id, inactive["id"], location_id)
        StaffProfile.objects.filter(pk=inactive["id"]).update(is_active=False)

        non_bookable = self._create_staff(business_id, location_id, "Hidden", is_bookable=False)
        self._assign_staff_service(business_id, non_bookable["id"], service_id)
        self._create_availability(business_id, non_bookable["id"], location_id)

        deleted = self._create_staff(business_id, location_id, "Deleted")
        self._assign_staff_service(business_id, deleted["id"], service_id)
        self._create_availability(business_id, deleted["id"], location_id)
        StaffProfile.objects.get(pk=deleted["id"]).soft_delete()

        response = self._list(ctx["location"]["slug"])
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = {row["display_name"] for row in response.data["results"]}
        self.assertEqual(names, {"Priya"})

    def test_excludes_staff_without_availability_at_location(self):
        ctx = self._seed()
        other = self._create_location(ctx["business"]["id"], name="Uptown")
        staff = self._create_staff(ctx["business"]["id"], other["id"], "Uptown Only")
        self._assign_staff_service(ctx["business"]["id"], staff["id"], ctx["service"]["id"])
        # Availability only at Uptown — not Downtown.
        self._create_availability(ctx["business"]["id"], staff["id"], other["id"])

        response = self._list(ctx["location"]["slug"])
        names = {row["display_name"] for row in response.data["results"]}
        self.assertEqual(names, {"Priya"})

    def test_excludes_staff_with_no_bookable_service_at_location(self):
        ctx = self._seed()
        staff = self._create_staff(ctx["business"]["id"], ctx["location"]["id"], "NoSvc")
        self._create_availability(ctx["business"]["id"], staff["id"], ctx["location"]["id"])
        # Capability on a service not offered at Downtown.
        other_loc = self._create_location(ctx["business"]["id"], name="Other")
        orphan = self._create_service(ctx["business"]["id"], name="Orphan")
        self._assign_service_location(ctx["business"]["id"], orphan["id"], other_loc["id"])
        self._assign_staff_service(ctx["business"]["id"], staff["id"], orphan["id"])

        response = self._list(ctx["location"]["slug"])
        names = {row["display_name"] for row in response.data["results"]}
        self.assertEqual(names, {"Priya"})

    def test_service_filters_on_staff_payload(self):
        ctx = self._seed()
        business_id = ctx["business"]["id"]
        location_id = ctx["location"]["id"]
        staff_id = ctx["staff"]["id"]

        offline = self._create_service(business_id, name="Offline", is_bookable_online=False)
        self._assign_service_location(business_id, offline["id"], location_id)
        self._assign_staff_service(business_id, staff_id, offline["id"])

        inactive = self._create_service(business_id, name="InactiveSvc")
        self._assign_service_location(business_id, inactive["id"], location_id)
        self._assign_staff_service(business_id, staff_id, inactive["id"])
        Service.objects.filter(pk=inactive["id"]).update(is_active=False)

        elsewhere = self._create_service(business_id, name="Elsewhere")
        other = self._create_location(business_id, name="Uptown")
        self._assign_service_location(business_id, elsewhere["id"], other["id"])
        self._assign_staff_service(business_id, staff_id, elsewhere["id"])

        unassigned = self._create_service(business_id, name="Unassigned")
        self._assign_service_location(business_id, unassigned["id"], location_id)

        response = self._list(ctx["location"]["slug"])
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        service_names = {s["name"] for s in response.data["results"][0]["services"]}
        self.assertEqual(service_names, {"Haircut"})

    def test_cross_tenant_isolation_and_org_id_ignored(self):
        ctx_a = self._seed(owner_email="a@example.com", org_name="Org A")
        register_b = self._register("b@example.com", "Org B")
        self._auth(register_b.data["access"])
        business_b = self._create_business("Salon B")
        location_b = self._create_location(business_b["id"], name="Branch")
        service_b = self._create_service(business_b["id"], name="Cut B")
        self._assign_service_location(business_b["id"], service_b["id"], location_b["id"])
        staff_b = self._create_staff(business_b["id"], location_b["id"], "B Only")
        self._assign_staff_service(business_b["id"], staff_b["id"], service_b["id"])
        self._create_availability(business_b["id"], staff_b["id"], location_b["id"])

        response = self._list(
            ctx_a["location"]["slug"],
            organization_id="00000000-0000-0000-0000-000000000099",
            tenant_id="x",
            business_id=business_b["id"],
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.data["results"]}
        self.assertEqual(ids, {ctx_a["staff"]["id"]})
        self.assertNotIn(staff_b["id"], ids)

    def test_invalid_inactive_deleted_location(self):
        ctx = self._seed()
        missing = self._list("no-such-place")
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)

        Location.objects.filter(pk=ctx["location"]["id"]).update(is_active=False)
        inactive = self._list(ctx["location"]["slug"])
        self.assertEqual(inactive.status_code, status.HTTP_404_NOT_FOUND)

        Location.objects.filter(pk=ctx["location"]["id"]).update(is_active=True)
        Location.objects.get(pk=ctx["location"]["id"]).soft_delete()
        deleted = self._list(ctx["location"]["slug"])
        self.assertEqual(deleted.status_code, status.HTTP_404_NOT_FOUND)

    def test_pagination_and_query_bound(self):
        ctx = self._seed()
        business_id = ctx["business"]["id"]
        location_id = ctx["location"]["id"]
        service_id = ctx["service"]["id"]
        for index in range(6):
            staff = self._create_staff(business_id, location_id, f"Stylist {index}")
            self._assign_staff_service(business_id, staff["id"], service_id)
            self._create_availability(business_id, staff["id"], location_id)

        page = self._list(ctx["location"]["slug"], limit=3, offset=0)
        self.assertEqual(page.status_code, status.HTTP_200_OK)
        self.assertEqual(page.data["limit"], 3)
        self.assertEqual(len(page.data["results"]), 3)
        self.assertGreaterEqual(page.data["count"], 7)

        with CaptureQueriesContext(connection) as captured:
            response = self._list(ctx["location"]["slug"], limit=50)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data["count"], 7)
        self.assertLessEqual(len(captured), 10)
