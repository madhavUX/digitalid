from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import connection
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from booking.models import Appointment, AppointmentStatus
from businesses.models import BusinessVertical
from organizations.models import OrganizationMember, Role
from staff.models import Weekday

KOLKATA = ZoneInfo("Asia/Kolkata")


class BookingAPITestCase(APITestCase):
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

    def _create_location(self, business_id, name: str = "Downtown", timezone_name="Asia/Kolkata"):
        response = self.client.post(
            reverse("location-list", kwargs={"business_id": business_id}),
            {"name": name, "timezone": timezone_name},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def _create_service(
        self,
        business_id,
        name: str = "Haircut",
        duration_minutes: int = 60,
        price: str = "499.00",
        buffer_before_minutes: int = 0,
        buffer_after_minutes: int = 0,
    ):
        response = self.client.post(
            reverse("service-list", kwargs={"business_id": business_id}),
            {
                "name": name,
                "duration_minutes": duration_minutes,
                "price": price,
                "buffer_before_minutes": buffer_before_minutes,
                "buffer_after_minutes": buffer_after_minutes,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def _assign_service_location(self, business_id, service_id, location_id):
        response = self.client.post(
            reverse(
                "service-location-list",
                kwargs={"business_id": business_id, "service_id": service_id},
            ),
            {"location_id": location_id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def _create_staff(self, business_id, location_id, display_name: str = "Priya"):
        response = self.client.post(
            reverse("staff-list", kwargs={"business_id": business_id}),
            {"display_name": display_name, "location_id": location_id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def _assign_staff_service(self, business_id, staff_id, service_id):
        response = self.client.post(
            reverse(
                "staff-service-list",
                kwargs={"business_id": business_id, "staff_id": staff_id},
            ),
            {"service_id": service_id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def _create_availability(
        self,
        business_id,
        staff_id,
        location_id,
        weekday=Weekday.MONDAY,
        starts_at="09:00:00",
        ends_at="17:00:00",
    ):
        response = self.client.post(
            reverse(
                "staff-availability-list",
                kwargs={"business_id": business_id, "staff_id": staff_id},
            ),
            {
                "location_id": location_id,
                "weekday": weekday,
                "starts_at": starts_at,
                "ends_at": ends_at,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def _create_customer(
        self,
        business_id,
        first_name: str = "Ananya",
        phone: str = "+919876543210",
    ):
        response = self.client.post(
            reverse("customer-list", kwargs={"business_id": business_id}),
            {"first_name": first_name, "phone": phone},
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

    def _next_weekday(self, weekday: int):
        """Next calendar date with ``weekday`` (Mon=0), always in the future."""
        today = timezone.now().astimezone(KOLKATA).date()
        days_ahead = (weekday - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return today + timedelta(days=days_ahead)

    def _local_iso(self, local_day, hhmm: str) -> str:
        hour, minute = map(int, hhmm.split(":"))
        local_dt = datetime.combine(local_day, time(hour, minute), tzinfo=KOLKATA)
        return local_dt.astimezone(UTC).isoformat().replace("+00:00", "Z")

    def _to_kolkata(self, iso_value: str) -> datetime:
        normalized = iso_value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).astimezone(KOLKATA)

    def _availability(self, business_id, location_id, service_id, local_day, staff_id=None):
        params = {"service_id": service_id, "date": local_day.isoformat()}
        if staff_id is not None:
            params["staff_id"] = staff_id
        return self.client.get(
            reverse(
                "location-availability",
                kwargs={"business_id": business_id, "location_id": location_id},
            ),
            params,
        )

    def _seed_bookable_monday(
        self,
        *,
        owner_email="owner@example.com",
        org_name="Org A",
        phone="+919876543210",
        buffer_before_minutes=10,
        buffer_after_minutes=10,
        staff_name="Priya",
    ):
        register = self._register(owner_email, org_name)
        self._auth(register.data["access"])
        business = self._create_business()
        location = self._create_location(business["id"])
        service = self._create_service(
            business["id"],
            duration_minutes=60,
            buffer_before_minutes=buffer_before_minutes,
            buffer_after_minutes=buffer_after_minutes,
        )
        self._assign_service_location(business["id"], service["id"], location["id"])
        staff = self._create_staff(business["id"], location["id"], staff_name)
        self._assign_staff_service(business["id"], staff["id"], service["id"])
        self._create_availability(
            business["id"],
            staff["id"],
            location["id"],
            weekday=Weekday.MONDAY,
            starts_at="09:00:00",
            ends_at="17:00:00",
        )
        customer = self._create_customer(business["id"], phone=phone)
        monday = self._next_weekday(Weekday.MONDAY)
        return {
            "token": register.data["access"],
            "business": business,
            "location": location,
            "service": service,
            "staff": staff,
            "customer": customer,
            "monday": monday,
        }


class AppointmentCoreTests(BookingAPITestCase):
    def test_create_list_snapshots_and_availability(self):
        ctx = self._seed_bookable_monday()
        business_id = ctx["business"]["id"]
        location_id = ctx["location"]["id"]
        service_id = ctx["service"]["id"]
        staff_id = ctx["staff"]["id"]
        customer_id = ctx["customer"]["id"]
        monday = ctx["monday"]

        before = self._availability(business_id, location_id, service_id, monday, staff_id)
        self.assertEqual(before.status_code, status.HTTP_200_OK)
        self.assertEqual(before.data["slot_grid_minutes"], 15)
        self.assertEqual(before.data["timezone"], "Asia/Kolkata")
        ten_slots = [
            slot
            for slot in before.data["slots"]
            if self._to_kolkata(slot["starts_at"]).strftime("%H:%M") == "10:00"
        ]
        self.assertEqual(len(ten_slots), 1)

        created = self.client.post(
            reverse("appointment-list", kwargs={"business_id": business_id}),
            {
                "location_id": location_id,
                "customer_id": customer_id,
                "service_id": service_id,
                "staff_id": staff_id,
                "starts_at": self._local_iso(monday, "10:00"),
                "organization_id": "ignored",
                "tenant_id": "ignored",
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(str(created.data["customer"]), customer_id)
        self.assertEqual(str(created.data["location"]), location_id)
        self.assertEqual(str(created.data["staff_profile"]), staff_id)
        self.assertEqual(created.data["status"], AppointmentStatus.CONFIRMED)

        starts_local = self._to_kolkata(created.data["starts_at"])
        ends_local = self._to_kolkata(created.data["ends_at"])
        occ_start_local = self._to_kolkata(created.data["occupancy_starts_at"])
        occ_end_local = self._to_kolkata(created.data["occupancy_ends_at"])
        self.assertEqual(starts_local.strftime("%H:%M"), "10:00")
        self.assertEqual(ends_local.strftime("%H:%M"), "11:00")
        self.assertEqual(occ_start_local.strftime("%H:%M"), "09:50")
        self.assertEqual(occ_end_local.strftime("%H:%M"), "11:10")
        self.assertEqual(starts_local.tzinfo.key, "Asia/Kolkata")

        self.assertEqual(len(created.data["items"]), 1)
        item = created.data["items"][0]
        self.assertEqual(str(item["service"]), service_id)
        self.assertEqual(item["service_name"], "Haircut")
        self.assertEqual(item["duration_minutes"], 60)
        self.assertEqual(item["buffer_before_minutes"], 10)
        self.assertEqual(item["buffer_after_minutes"], 10)
        self.assertEqual(item["price"], "499.00")

        listing = self.client.get(reverse("appointment-list", kwargs={"business_id": business_id}))
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual(listing.data["count"], 1)
        self.assertEqual(listing.data["results"][0]["id"], created.data["id"])

        after = self._availability(business_id, location_id, service_id, monday, staff_id)
        self.assertEqual(after.status_code, status.HTTP_200_OK)
        self.assertEqual(after.data["slot_grid_minutes"], 15)
        remaining_ten = [
            slot
            for slot in after.data["slots"]
            if self._to_kolkata(slot["starts_at"]).strftime("%H:%M") == "10:00"
        ]
        self.assertEqual(remaining_ten, [])

    def test_service_not_at_location_and_staff_capability(self):
        register = self._register("owner@example.com", "Org A")
        self._auth(register.data["access"])
        business = self._create_business()
        location = self._create_location(business["id"])
        other_location = self._create_location(business["id"], name="Uptown")
        service = self._create_service(business["id"], duration_minutes=60)
        self._assign_service_location(business["id"], service["id"], location["id"])
        staff = self._create_staff(business["id"], location["id"])
        self._create_availability(business["id"], staff["id"], location["id"])
        customer = self._create_customer(business["id"])
        monday = self._next_weekday(Weekday.MONDAY)
        starts = self._local_iso(monday, "10:00")

        # Staff lacks StaffService capability.
        no_capability = self.client.post(
            reverse("appointment-list", kwargs={"business_id": business["id"]}),
            {
                "location_id": location["id"],
                "customer_id": customer["id"],
                "service_id": service["id"],
                "staff_id": staff["id"],
                "starts_at": starts,
            },
            format="json",
        )
        self.assertEqual(no_capability.status_code, status.HTTP_400_BAD_REQUEST)

        self._assign_staff_service(business["id"], staff["id"], service["id"])

        # Service is not offered at other_location (no ServiceLocation).
        wrong_location = self.client.post(
            reverse("appointment-list", kwargs={"business_id": business["id"]}),
            {
                "location_id": other_location["id"],
                "customer_id": customer["id"],
                "service_id": service["id"],
                "staff_id": staff["id"],
                "starts_at": starts,
            },
            format="json",
        )
        self.assertEqual(wrong_location.status_code, status.HTTP_400_BAD_REQUEST)

        avail = self._availability(
            business["id"], other_location["id"], service["id"], monday, staff["id"]
        )
        self.assertEqual(avail.status_code, status.HTTP_400_BAD_REQUEST)

    def test_any_staff_selection_and_time_off(self):
        register = self._register("owner@example.com", "Org A")
        self._auth(register.data["access"])
        business = self._create_business()
        location = self._create_location(business["id"])
        service = self._create_service(
            business["id"],
            duration_minutes=60,
            buffer_before_minutes=10,
            buffer_after_minutes=10,
        )
        self._assign_service_location(business["id"], service["id"], location["id"])

        staff_a = self._create_staff(business["id"], location["id"], "Staff A")
        staff_b = self._create_staff(business["id"], location["id"], "Staff B")
        for staff in (staff_a, staff_b):
            self._assign_staff_service(business["id"], staff["id"], service["id"])
            self._create_availability(business["id"], staff["id"], location["id"])

        customer = self._create_customer(business["id"])
        monday = self._next_weekday(Weekday.MONDAY)

        day_start = datetime.combine(monday, time.min, tzinfo=KOLKATA).astimezone(UTC)
        day_end = datetime.combine(monday + timedelta(days=1), time.min, tzinfo=KOLKATA).astimezone(
            UTC
        )
        time_off = self.client.post(
            reverse(
                "staff-time-off-list",
                kwargs={"business_id": business["id"], "staff_id": staff_a["id"]},
            ),
            {
                "starts_at": day_start.isoformat().replace("+00:00", "Z"),
                "ends_at": day_end.isoformat().replace("+00:00", "Z"),
                "reason": "All-day leave",
            },
            format="json",
        )
        self.assertEqual(time_off.status_code, status.HTTP_201_CREATED)

        created = self.client.post(
            reverse("appointment-list", kwargs={"business_id": business["id"]}),
            {
                "location_id": location["id"],
                "customer_id": customer["id"],
                "service_id": service["id"],
                "starts_at": self._local_iso(monday, "10:00"),
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(str(created.data["staff_profile"]), staff_b["id"])

    def test_status_transitions_and_cancel_frees_slot(self):
        ctx = self._seed_bookable_monday(phone="+919811122233")
        business_id = ctx["business"]["id"]
        location_id = ctx["location"]["id"]
        service_id = ctx["service"]["id"]
        staff_id = ctx["staff"]["id"]
        customer_id = ctx["customer"]["id"]
        monday = ctx["monday"]

        created = self.client.post(
            reverse("appointment-list", kwargs={"business_id": business_id}),
            {
                "location_id": location_id,
                "customer_id": customer_id,
                "service_id": service_id,
                "staff_id": staff_id,
                "starts_at": self._local_iso(monday, "10:00"),
                "status": AppointmentStatus.PENDING,
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(created.data["status"], AppointmentStatus.PENDING)
        appointment_id = created.data["id"]

        illegal = self.client.patch(
            reverse(
                "appointment-detail",
                kwargs={"business_id": business_id, "appointment_id": appointment_id},
            ),
            {"status": AppointmentStatus.COMPLETED},
            format="json",
        )
        self.assertEqual(illegal.status_code, status.HTTP_400_BAD_REQUEST)

        confirmed = self.client.patch(
            reverse(
                "appointment-detail",
                kwargs={"business_id": business_id, "appointment_id": appointment_id},
            ),
            {"status": AppointmentStatus.CONFIRMED},
            format="json",
        )
        self.assertEqual(confirmed.status_code, status.HTTP_200_OK)
        self.assertEqual(confirmed.data["status"], AppointmentStatus.CONFIRMED)

        cancelled = self.client.post(
            reverse(
                "appointment-cancel",
                kwargs={"business_id": business_id, "appointment_id": appointment_id},
            ),
            {"reason": "Customer reschedule"},
            format="json",
        )
        self.assertEqual(cancelled.status_code, status.HTTP_200_OK)
        self.assertEqual(cancelled.data["status"], AppointmentStatus.CANCELLED)
        self.assertEqual(cancelled.data["cancellation_reason"], "Customer reschedule")
        self.assertIsNotNone(cancelled.data["cancelled_at"])

        after = self._availability(business_id, location_id, service_id, monday, staff_id)
        self.assertEqual(after.status_code, status.HTTP_200_OK)
        ten_slots = [
            slot
            for slot in after.data["slots"]
            if self._to_kolkata(slot["starts_at"]).strftime("%H:%M") == "10:00"
        ]
        self.assertEqual(len(ten_slots), 1)

    def test_tenant_isolation(self):
        ctx_a = self._seed_bookable_monday(
            owner_email="owner-a@example.com",
            org_name="Org A",
            phone="+919900011122",
        )
        created = self.client.post(
            reverse("appointment-list", kwargs={"business_id": ctx_a["business"]["id"]}),
            {
                "location_id": ctx_a["location"]["id"],
                "customer_id": ctx_a["customer"]["id"],
                "service_id": ctx_a["service"]["id"],
                "staff_id": ctx_a["staff"]["id"],
                "starts_at": self._local_iso(ctx_a["monday"], "10:00"),
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        appointment_id = created.data["id"]

        register_b = self._register("owner-b@example.com", "Org B")
        self._auth(register_b.data["access"])
        business_b = self._create_business("Salon B")

        avail = self._availability(
            ctx_a["business"]["id"],
            ctx_a["location"]["id"],
            ctx_a["service"]["id"],
            ctx_a["monday"],
        )
        self.assertEqual(avail.status_code, status.HTTP_404_NOT_FOUND)

        detail = self.client.get(
            reverse(
                "appointment-detail",
                kwargs={
                    "business_id": ctx_a["business"]["id"],
                    "appointment_id": appointment_id,
                },
            )
        )
        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)

        listing = self.client.get(
            reverse("appointment-list", kwargs={"business_id": ctx_a["business"]["id"]})
        )
        self.assertEqual(listing.status_code, status.HTTP_404_NOT_FOUND)

        create_under_a = self.client.post(
            reverse("appointment-list", kwargs={"business_id": ctx_a["business"]["id"]}),
            {
                "location_id": ctx_a["location"]["id"],
                "customer_id": ctx_a["customer"]["id"],
                "service_id": ctx_a["service"]["id"],
                "staff_id": ctx_a["staff"]["id"],
                "starts_at": self._local_iso(ctx_a["monday"], "14:00"),
            },
            format="json",
        )
        self.assertEqual(create_under_a.status_code, status.HTTP_404_NOT_FOUND)

        # Org B's own business cannot reuse A's location/customer/service/staff ids.
        create_mixed = self.client.post(
            reverse("appointment-list", kwargs={"business_id": business_b["id"]}),
            {
                "location_id": ctx_a["location"]["id"],
                "customer_id": ctx_a["customer"]["id"],
                "service_id": ctx_a["service"]["id"],
                "staff_id": ctx_a["staff"]["id"],
                "starts_at": self._local_iso(ctx_a["monday"], "14:00"),
            },
            format="json",
        )
        self.assertIn(
            create_mixed.status_code,
            {status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND},
        )

    def test_manager_write_staff_read(self):
        ctx = self._seed_bookable_monday(
            owner_email="owner@example.com",
            phone="+919744400004",
        )
        business_id = ctx["business"]["id"]

        self._login_as_role("owner@example.com", Role.MANAGER, "manager@example.com")
        created = self.client.post(
            reverse("appointment-list", kwargs={"business_id": business_id}),
            {
                "location_id": ctx["location"]["id"],
                "customer_id": ctx["customer"]["id"],
                "service_id": ctx["service"]["id"],
                "staff_id": ctx["staff"]["id"],
                "starts_at": self._local_iso(ctx["monday"], "10:00"),
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)

        self._login_as_role("owner@example.com", Role.STAFF, "staff@example.com")
        listing = self.client.get(reverse("appointment-list", kwargs={"business_id": business_id}))
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual(listing.data["count"], 1)

        write = self.client.post(
            reverse("appointment-list", kwargs={"business_id": business_id}),
            {
                "location_id": ctx["location"]["id"],
                "customer_id": ctx["customer"]["id"],
                "service_id": ctx["service"]["id"],
                "staff_id": ctx["staff"]["id"],
                "starts_at": self._local_iso(ctx["monday"], "14:00"),
            },
            format="json",
        )
        self.assertEqual(write.status_code, status.HTTP_403_FORBIDDEN)


class AppointmentConcurrencyTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL required for concurrency exclusion tests")
        self.client = APIClient()
        # Reuse BookingAPITestCase helpers against this TransactionTestCase client.
        self._api = BookingAPITestCase("runTest")
        self._api.client = self.client

    def test_concurrent_same_staff_slot_one_wins(self):
        api = self._api
        register = api._register("owner@example.com", "Org A")
        api._auth(register.data["access"])
        business = api._create_business()
        location = api._create_location(business["id"])
        service = api._create_service(
            business["id"],
            duration_minutes=60,
            buffer_before_minutes=10,
            buffer_after_minutes=10,
        )
        api._assign_service_location(business["id"], service["id"], location["id"])
        staff = api._create_staff(business["id"], location["id"])
        api._assign_staff_service(business["id"], staff["id"], service["id"])
        api._create_availability(business["id"], staff["id"], location["id"])
        customer = api._create_customer(business["id"])
        monday = api._next_weekday(Weekday.MONDAY)
        token = register.data["access"]
        payload = {
            "location_id": location["id"],
            "customer_id": customer["id"],
            "service_id": service["id"],
            "staff_id": staff["id"],
            "starts_at": api._local_iso(monday, "10:00"),
        }
        url = reverse("appointment-list", kwargs={"business_id": business["id"]})

        def _post():
            client = APIClient()
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
            try:
                return client.post(url, payload, format="json").status_code
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(_post), executor.submit(_post)]
            codes = sorted(future.result() for future in futures)

        self.assertEqual(codes, [status.HTTP_201_CREATED, status.HTTP_409_CONFLICT])
        self.assertEqual(
            Appointment.objects.filter(staff_profile_id=staff["id"]).count(),
            1,
        )
