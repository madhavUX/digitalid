from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from booking.models import Appointment, AppointmentStatus
from booking.tests.test_booking_api import KOLKATA, BookingAPITestCase
from businesses.models import BusinessVertical
from catalog.models import Service
from customers.models import Customer
from locations.models import Location
from staff.models import Weekday


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
        },
    }
)
class PublicBookingAPITestCase(BookingAPITestCase):
    def setUp(self):
        super().setUp()
        from django.core.cache import cache

        cache.clear()
        self.public = APIClient()

    def _public_availability(self, location_id, service_id, local_day, staff_id=None):
        params = {
            "location_id": location_id,
            "service_id": service_id,
            "date": local_day.isoformat(),
        }
        if staff_id is not None:
            params["staff_id"] = staff_id
        return self.public.get(reverse("public-booking-availability"), params)

    def _public_create(self, payload, *, idempotency_key=None, client=None):
        client = client or self.public
        headers = {}
        if idempotency_key:
            headers["HTTP_IDEMPOTENCY_KEY"] = idempotency_key
        return client.post(
            reverse("public-booking-appointment-create"),
            payload,
            format="json",
            **headers,
        )

    def _book_payload(self, ctx, hhmm="10:00", staff_id=None, phone="9876543210"):
        return {
            "location_id": ctx["location"]["id"],
            "service_id": ctx["service"]["id"],
            "staff_id": staff_id,
            "start": datetime.combine(
                ctx["monday"],
                time(*map(int, hhmm.split(":"))),
                tzinfo=KOLKATA,
            ).isoformat(),
            "customer": {
                "name": "Rahul Sharma",
                "phone": phone,
                "email": "rahul@example.com",
            },
        }


class PublicAvailabilityTests(PublicBookingAPITestCase):
    def test_valid_availability_asia_kolkata(self):
        ctx = self._seed_bookable_monday()
        self.client.credentials()
        response = self._public_availability(
            ctx["location"]["id"],
            ctx["service"]["id"],
            ctx["monday"],
            ctx["staff"]["id"],
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["location"]["timezone"], "Asia/Kolkata")
        self.assertEqual(response.data["service"]["duration_minutes"], 60)
        self.assertEqual(response.data["service"]["price"], "499.00")
        ten = [
            s
            for s in response.data["slots"]
            if s["start"].startswith(f"{ctx['monday'].isoformat()}T10:00:00")
        ]
        self.assertEqual(len(ten), 1)
        self.assertEqual(ten[0]["staff_id"], ctx["staff"]["id"])
        self.assertNotIn("occupancy_starts_at", ten[0])

    def test_missing_location_and_service(self):
        response = self.public.get(
            reverse("public-booking-availability"),
            {"date": "2026-09-10"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_location(self):
        ctx = self._seed_bookable_monday()
        response = self._public_availability(
            uuid4(),
            ctx["service"]["id"],
            ctx["monday"],
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["code"], "INVALID_LOCATION")

    def test_invalid_service(self):
        ctx = self._seed_bookable_monday()
        response = self._public_availability(
            ctx["location"]["id"],
            uuid4(),
            ctx["monday"],
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["code"], "INVALID_SERVICE")

    def test_service_unavailable_at_location(self):
        ctx = self._seed_bookable_monday()
        other_location = self._create_location(ctx["business"]["id"], name="Other")
        response = self._public_availability(
            other_location["id"],
            ctx["service"]["id"],
            ctx["monday"],
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "INVALID_SERVICE")

    def test_any_staff_and_staff_filter(self):
        ctx = self._seed_bookable_monday()
        any_staff = self._public_availability(
            ctx["location"]["id"],
            ctx["service"]["id"],
            ctx["monday"],
        )
        self.assertEqual(any_staff.status_code, status.HTTP_200_OK)
        self.assertTrue(any_staff.data["slots"])
        self.assertIsNone(any_staff.data["slots"][0]["staff_id"])
        self.assertIn(ctx["staff"]["id"], any_staff.data["slots"][0]["staff_options"])

        filtered = self._public_availability(
            ctx["location"]["id"],
            ctx["service"]["id"],
            ctx["monday"],
            ctx["staff"]["id"],
        )
        self.assertEqual(filtered.status_code, status.HTTP_200_OK)
        self.assertEqual(filtered.data["slots"][0]["staff_id"], ctx["staff"]["id"])

    def test_invalid_staff(self):
        ctx = self._seed_bookable_monday()
        response = self._public_availability(
            ctx["location"]["id"],
            ctx["service"]["id"],
            ctx["monday"],
            uuid4(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "INVALID_STAFF")

    def test_time_off_and_existing_appointment_hide_slots(self):
        ctx = self._seed_bookable_monday()
        monday = ctx["monday"]
        starts = datetime.combine(monday, time(9, 0), tzinfo=KOLKATA).astimezone(UTC)
        ends = datetime.combine(monday, time(12, 0), tzinfo=KOLKATA).astimezone(UTC)
        self.client.post(
            reverse(
                "staff-time-off-list",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "staff_id": ctx["staff"]["id"],
                },
            ),
            {
                "starts_at": starts.isoformat().replace("+00:00", "Z"),
                "ends_at": ends.isoformat().replace("+00:00", "Z"),
                "reason": "Leave",
            },
            format="json",
        )
        response = self._public_availability(
            ctx["location"]["id"],
            ctx["service"]["id"],
            monday,
            ctx["staff"]["id"],
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        morning = [
            s
            for s in response.data["slots"]
            if s["start"].startswith(f"{monday.isoformat()}T10:00:00")
        ]
        self.assertEqual(len(morning), 0)

    def test_buffers_affect_availability(self):
        ctx = self._seed_bookable_monday(
            buffer_before_minutes=15,
            buffer_after_minutes=15,
            phone="+919800000089",
        )
        payload = self._book_payload(ctx, "10:00", staff_id=ctx["staff"]["id"], phone="9800000001")
        created = self._public_create(payload)
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)

        response = self._public_availability(
            ctx["location"]["id"],
            ctx["service"]["id"],
            ctx["monday"],
            ctx["staff"]["id"],
        )
        blocked = [
            s
            for s in response.data["slots"]
            if s["start"].startswith(f"{ctx['monday'].isoformat()}T11:00:00")
        ]
        # 10:00–11:00 visible + 15 after → occupancy to 11:15; 11:00 start needs before buffer
        self.assertEqual(len(blocked), 0)


class PublicAppointmentCreateTests(PublicBookingAPITestCase):
    def test_successful_public_booking_snapshots_and_customer(self):
        ctx = self._seed_bookable_monday(phone="+919800000099")
        payload = self._book_payload(ctx, "10:00", staff_id=ctx["staff"]["id"], phone="9811100001")
        response = self._public_create(payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["public_reference"])
        self.assertEqual(response.data["status"], AppointmentStatus.CONFIRMED)
        self.assertEqual(response.data["service"], "Haircut")
        self.assertEqual(response.data["location"], "Downtown")
        self.assertEqual(response.data["staff"], "Priya")
        self.assertEqual(response.data["total"], "499.00")
        self.assertEqual(response.data["currency"], "INR")
        self.assertNotIn("id", response.data)
        self.assertNotIn("customer", response.data)
        self.assertNotIn("occupancy_starts_at", response.data)

        appointment = Appointment.objects.get(public_reference=response.data["public_reference"])
        self.assertEqual(appointment.source, "ONLINE")
        item = appointment.items.get()
        self.assertEqual(item.duration_minutes, 60)
        self.assertEqual(item.buffer_before_minutes, 10)
        self.assertEqual(item.buffer_after_minutes, 10)
        self.assertEqual(item.price, appointment.total_price)

        customer = Customer.objects.get(pk=appointment.customer_id)
        self.assertEqual(customer.phone, "+919811100001")
        self.assertEqual(customer.first_name, "Rahul")
        self.assertEqual(customer.last_name, "Sharma")

    def test_any_staff_assignment(self):
        ctx = self._seed_bookable_monday(phone="+919800000098")
        payload = self._book_payload(ctx, "11:00", staff_id=None, phone="9811100002")
        response = self._public_create(payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        appointment = Appointment.objects.get(public_reference=response.data["public_reference"])
        self.assertEqual(str(appointment.staff_profile_id), ctx["staff"]["id"])

    def test_slot_unavailable(self):
        ctx = self._seed_bookable_monday(phone="+919800000097")
        first = self._public_create(
            self._book_payload(ctx, "10:00", staff_id=ctx["staff"]["id"], phone="9811100003")
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        second = self._public_create(
            self._book_payload(ctx, "10:00", staff_id=ctx["staff"]["id"], phone="9811100004")
        )
        self.assertEqual(second.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(second.data["code"], "SLOT_UNAVAILABLE")

    def test_inactive_service_and_location_cannot_book(self):
        ctx = self._seed_bookable_monday(phone="+919800000096")
        Service.objects.filter(pk=ctx["service"]["id"]).update(is_active=False)
        bad_service = self._public_create(
            self._book_payload(ctx, "10:00", staff_id=ctx["staff"]["id"], phone="9811100005")
        )
        self.assertEqual(bad_service.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(bad_service.data["code"], "INVALID_SERVICE")

        Service.objects.filter(pk=ctx["service"]["id"]).update(is_active=True)
        Location.objects.filter(pk=ctx["location"]["id"]).update(is_active=False)
        bad_location = self._public_create(
            self._book_payload(ctx, "10:00", staff_id=ctx["staff"]["id"], phone="9811100006")
        )
        self.assertEqual(bad_location.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(bad_location.data["code"], "INVALID_LOCATION")

    def test_not_bookable_online(self):
        ctx = self._seed_bookable_monday(phone="+919800000095")
        Service.objects.filter(pk=ctx["service"]["id"]).update(is_bookable_online=False)
        response = self._public_create(
            self._book_payload(ctx, "10:00", staff_id=ctx["staff"]["id"], phone="9811100007")
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "INVALID_SERVICE")


class PublicLookupCancelTests(PublicBookingAPITestCase):
    def test_lookup_and_cancel(self):
        ctx = self._seed_bookable_monday(phone="+919800000094")
        created = self._public_create(
            self._book_payload(ctx, "10:00", staff_id=ctx["staff"]["id"], phone="9822200001")
        )
        ref = created.data["public_reference"]

        detail = self.public.get(
            reverse("public-booking-appointment-detail", kwargs={"public_reference": ref})
        )
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertEqual(detail.data["public_reference"], ref)
        self.assertNotIn("id", detail.data)

        cancelled = self.public.post(
            reverse("public-booking-appointment-cancel", kwargs={"public_reference": ref}),
            {"reason": "Cannot make it"},
            format="json",
        )
        self.assertEqual(cancelled.status_code, status.HTTP_200_OK)
        self.assertEqual(cancelled.data["status"], AppointmentStatus.CANCELLED)

        again = self.public.post(
            reverse("public-booking-appointment-cancel", kwargs={"public_reference": ref}),
            {"reason": "again"},
            format="json",
        )
        self.assertEqual(again.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(again.data["code"], "CANCELLATION_NOT_ALLOWED")

    def test_invalid_public_reference(self):
        response = self.public.get(
            reverse(
                "public-booking-appointment-detail",
                kwargs={"public_reference": "BK-DOESNOTEXIST"},
            )
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["code"], "BOOKING_NOT_FOUND")

    def test_soft_deleted_not_accessible(self):
        ctx = self._seed_bookable_monday(phone="+919800000093")
        created = self._public_create(
            self._book_payload(ctx, "10:00", staff_id=ctx["staff"]["id"], phone="9822200002")
        )
        appointment = Appointment.objects.get(public_reference=created.data["public_reference"])
        appointment.soft_delete()
        detail = self.public.get(
            reverse(
                "public-booking-appointment-detail",
                kwargs={"public_reference": created.data["public_reference"]},
            )
        )
        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)

    def test_completed_cannot_cancel(self):
        ctx = self._seed_bookable_monday(phone="+919800000092")
        created = self._public_create(
            self._book_payload(ctx, "10:00", staff_id=ctx["staff"]["id"], phone="9822200003")
        )
        appointment = Appointment.objects.get(public_reference=created.data["public_reference"])
        appointment.status = AppointmentStatus.COMPLETED
        appointment.save(update_fields=["status", "updated_at"])
        response = self.public.post(
            reverse(
                "public-booking-appointment-cancel",
                kwargs={"public_reference": created.data["public_reference"]},
            ),
            {"reason": "late"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "CANCELLATION_NOT_ALLOWED")

    def test_public_cannot_use_internal_appointment_id(self):
        ctx = self._seed_bookable_monday(phone="+919800000091")
        created = self._public_create(
            self._book_payload(ctx, "10:00", staff_id=ctx["staff"]["id"], phone="9822200004")
        )
        appointment = Appointment.objects.get(public_reference=created.data["public_reference"])
        response = self.public.get(
            reverse(
                "public-booking-appointment-detail",
                kwargs={"public_reference": str(appointment.id)},
            )
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class PublicIdempotencyTests(PublicBookingAPITestCase):
    def test_idempotent_replay_and_conflict(self):
        ctx = self._seed_bookable_monday(phone="+919800000090")
        payload = self._book_payload(ctx, "10:00", staff_id=ctx["staff"]["id"], phone="9833300001")
        key = "8f9a2d7c-example"
        first = self._public_create(payload, idempotency_key=key)
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        second = self._public_create(payload, idempotency_key=key)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.data["public_reference"], first.data["public_reference"])
        self.assertEqual(
            Appointment.objects.filter(public_reference=first.data["public_reference"]).count(),
            1,
        )
        self.assertEqual(Appointment.objects.filter(location_id=ctx["location"]["id"]).count(), 1)

        different = dict(payload)
        different["start"] = datetime.combine(
            ctx["monday"], time(11, 0), tzinfo=KOLKATA
        ).isoformat()
        conflict = self._public_create(different, idempotency_key=key)
        self.assertEqual(conflict.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(conflict.data["code"], "IDEMPOTENCY_CONFLICT")


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
        },
    }
)
class PublicBookingConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.owner_client = APIClient()
        register = self.owner_client.post(
            reverse("auth-register"),
            {
                "email": "public-conc@example.com",
                "password": "StrongPass123",
                "organization_name": "Public Conc Org",
            },
            format="json",
        )
        self.assertEqual(register.status_code, status.HTTP_201_CREATED)
        self.owner_client.credentials(HTTP_AUTHORIZATION=f"Bearer {register.data['access']}")

        business = self.owner_client.post(
            reverse("business-list"),
            {"name": "Conc Salon", "vertical": BusinessVertical.SALON},
            format="json",
        ).data
        location = self.owner_client.post(
            reverse("location-list", kwargs={"business_id": business["id"]}),
            {"name": "Main", "timezone": "Asia/Kolkata"},
            format="json",
        ).data
        service = self.owner_client.post(
            reverse("service-list", kwargs={"business_id": business["id"]}),
            {
                "name": "Haircut",
                "duration_minutes": 60,
                "price": "499.00",
                "buffer_before_minutes": 0,
                "buffer_after_minutes": 0,
            },
            format="json",
        ).data
        self.owner_client.post(
            reverse(
                "service-location-list",
                kwargs={"business_id": business["id"], "service_id": service["id"]},
            ),
            {"location_id": location["id"]},
            format="json",
        )
        staff = self.owner_client.post(
            reverse("staff-list", kwargs={"business_id": business["id"]}),
            {"display_name": "Priya", "location_id": location["id"]},
            format="json",
        ).data
        self.owner_client.post(
            reverse(
                "staff-service-list",
                kwargs={"business_id": business["id"], "staff_id": staff["id"]},
            ),
            {"service_id": service["id"]},
            format="json",
        )
        self.owner_client.post(
            reverse(
                "staff-availability-list",
                kwargs={"business_id": business["id"], "staff_id": staff["id"]},
            ),
            {
                "location_id": location["id"],
                "weekday": Weekday.MONDAY,
                "starts_at": "09:00:00",
                "ends_at": "17:00:00",
            },
            format="json",
        )
        today = timezone.now().astimezone(KOLKATA).date()
        days_ahead = (Weekday.MONDAY - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        monday = today + timedelta(days=days_ahead)
        start = datetime.combine(monday, time(10, 0), tzinfo=KOLKATA).isoformat()
        self.payload_a = {
            "location_id": location["id"],
            "service_id": service["id"],
            "staff_id": staff["id"],
            "start": start,
            "customer": {"name": "A", "phone": "9811111111", "email": ""},
        }
        self.payload_b = {
            "location_id": location["id"],
            "service_id": service["id"],
            "staff_id": staff["id"],
            "start": start,
            "customer": {"name": "B", "phone": "9822222222", "email": ""},
        }
        self.location_id = location["id"]

    def test_concurrent_public_create_one_wins(self):
        if connection.vendor != "postgresql":
            self.skipTest("Concurrency exclusion requires PostgreSQL")

        def book(payload):
            client = APIClient()
            response = client.post(
                reverse("public-booking-appointment-create"),
                payload,
                format="json",
            )
            return response.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(book, self.payload_a),
                pool.submit(book, self.payload_b),
            ]
            codes = sorted(future.result() for future in futures)

        self.assertEqual(codes, [201, 409])
        self.assertEqual(
            Appointment.objects.filter(location_id=self.location_id).count(),
            1,
        )
