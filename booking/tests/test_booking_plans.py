"""Book Regularly — BookingPlan API, recurrence, scheduler, security."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time, timedelta

from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from booking.models import Appointment, AppointmentStatus, BookingPlan, BookingPlanStatus
from booking.plan_services import add_plan_interval, process_due_booking_plans
from booking.tests.test_booking_api import KOLKATA, BookingAPITestCase
from booking.tests.test_public_booking_api import PublicBookingAPITestCase
from catalog.models import Service
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
            "public_catalog": "10000/min",
        },
    }
)
class BookingPlanAPITests(PublicBookingAPITestCase):
    def _plan_payload(self, ctx, *, frequency="MONTH", interval=1, staff_id=None, hhmm="10:00"):
        payload = self._book_payload(ctx, hhmm=hhmm, staff_id=staff_id)
        payload["frequency"] = frequency
        payload["interval"] = interval
        if staff_id:
            payload["staff_preference"] = "SAME_STAFF"
        else:
            payload["staff_preference"] = "ANY_STAFF"
        return payload

    def _create_plan(self, ctx, **kwargs):
        return self.public.post(
            reverse("public-booking-plan-create"),
            self._plan_payload(ctx, **kwargs),
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"plan-{timezone.now().timestamp()}",
        )

    def test_create_plan_and_first_appointment(self):
        ctx = self._seed_bookable_monday()
        response = self._create_plan(ctx, staff_id=ctx["staff"]["id"])
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("manage_token", response.data)
        self.assertIn("plan_token", response.data)
        self.assertEqual(response.data["regular_booking"]["frequency"], "MONTH")
        self.assertEqual(response.data["regular_booking"]["interval"], 1)
        self.assertNotIn("id", response.data["regular_booking"])

        plan = BookingPlan.objects.get()
        self.assertEqual(plan.status, BookingPlanStatus.ACTIVE)
        appt = Appointment.objects.get()
        self.assertEqual(appt.booking_plan_id, plan.id)
        self.assertEqual(appt.plan_occurrence_date, ctx["monday"])
        self.assertEqual(Appointment.objects.filter(booking_plan=plan).count(), 1)

        # next_due_at is one month later at preferred time
        expected_next = date(
            ctx["monday"].year + (1 if ctx["monday"].month == 12 else 0),
            1 if ctx["monday"].month == 12 else ctx["monday"].month + 1,
            ctx["monday"].day,
        )
        next_local = plan.next_due_at.astimezone(KOLKATA)
        self.assertEqual(next_local.date(), expected_next)
        self.assertEqual(next_local.hour, 10)

    def test_frequency_helpers_month_end(self):
        self.assertEqual(
            add_plan_interval(date(2026, 1, 31), frequency="MONTH", interval=1),
            date(2026, 2, 28),
        )
        self.assertEqual(
            add_plan_interval(date(2026, 10, 5), frequency="WEEK", interval=2),
            date(2026, 10, 19),
        )

    def test_pause_resume_cancel_idempotent_and_keeps_appointment(self):
        ctx = self._seed_bookable_monday()
        created = self._create_plan(ctx, staff_id=ctx["staff"]["id"])
        plan_token = created.data["plan_token"]
        manage_token = created.data["manage_token"]
        appt_ref = created.data["public_reference"]

        pause = self.public.post(reverse("public-booking-plan-pause", kwargs={"token": plan_token}))
        self.assertEqual(pause.status_code, status.HTTP_200_OK)
        self.assertEqual(pause.data["status"], "PAUSED")
        pause2 = self.public.post(
            reverse("public-booking-plan-pause", kwargs={"token": plan_token})
        )
        self.assertEqual(pause2.data["status"], "PAUSED")

        resume = self.public.post(
            reverse("public-booking-plan-resume", kwargs={"token": plan_token})
        )
        self.assertEqual(resume.data["status"], "ACTIVE")

        cancel = self.public.post(
            reverse("public-booking-plan-cancel", kwargs={"token": plan_token})
        )
        self.assertEqual(cancel.data["status"], "CANCELLED")
        cancel2 = self.public.post(
            reverse("public-booking-plan-cancel", kwargs={"token": plan_token})
        )
        self.assertEqual(cancel2.data["status"], "CANCELLED")

        appt = Appointment.objects.get(public_reference=appt_ref)
        self.assertEqual(appt.status, AppointmentStatus.CONFIRMED)

        managed = self.public.get(reverse("public-booking-manage", kwargs={"token": manage_token}))
        self.assertEqual(managed.status_code, status.HTTP_200_OK)
        self.assertTrue(managed.data["is_regular_booking"])
        self.assertEqual(managed.data["regular_booking"]["status"], "CANCELLED")

    def test_manage_plan_via_appointment_token(self):
        ctx = self._seed_bookable_monday()
        created = self._create_plan(ctx, staff_id=ctx["staff"]["id"])
        token = created.data["manage_token"]
        paused = self.public.post(
            reverse("public-booking-manage-plan-pause", kwargs={"token": token})
        )
        self.assertEqual(paused.data["status"], "PAUSED")

    def test_security_invalid_token_404(self):
        response = self.public.get(
            reverse("public-booking-plan-detail", kwargs={"token": "not-a-real-token"})
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["code"], "BOOKING_NOT_FOUND")

    def test_history_marks_regular(self):
        ctx = self._seed_bookable_monday()
        created = self._create_plan(ctx, staff_id=ctx["staff"]["id"])
        history = self.public.get(
            reverse(
                "public-booking-history",
                kwargs={"token": created.data["manage_token"]},
            ),
            {"category": "upcoming"},
        )
        self.assertEqual(history.status_code, status.HTTP_200_OK)
        self.assertTrue(history.data["results"][0]["is_regular_booking"])

    def test_scheduler_creates_when_slot_free_and_skips_paused(self):
        ctx = self._seed_bookable_monday()
        self._create_plan(ctx, frequency="WEEK", interval=1, staff_id=ctx["staff"]["id"])
        plan = BookingPlan.objects.get()
        # Force next due to next Monday 10:00 and ensure staff availability that day
        next_monday = ctx["monday"] + timedelta(days=7)
        plan.next_due_at = datetime.combine(next_monday, time(10, 0), tzinfo=KOLKATA).astimezone(
            UTC
        )
        plan.save(update_fields=["next_due_at"])

        # Paused → skipped
        plan.status = BookingPlanStatus.PAUSED
        plan.save(update_fields=["status"])
        result = process_due_booking_plans(
            now=plan.next_due_at + timedelta(minutes=1),
        )
        self.assertEqual(Appointment.objects.filter(booking_plan=plan).count(), 1)

        plan.status = BookingPlanStatus.ACTIVE
        plan.save(update_fields=["status"])
        result = process_due_booking_plans(now=plan.next_due_at + timedelta(minutes=1))
        self.assertGreaterEqual(result.created, 1)
        self.assertEqual(Appointment.objects.filter(booking_plan=plan).count(), 2)

    def test_scheduler_unavailable_marks_needs_action(self):
        ctx = self._seed_bookable_monday()
        self._create_plan(ctx, frequency="WEEK", interval=1, staff_id=ctx["staff"]["id"])
        plan = BookingPlan.objects.get()
        # Due on a Tuesday when staff has no availability
        tuesday = ctx["monday"] + timedelta(days=1)
        plan.next_due_at = datetime.combine(tuesday, time(10, 0), tzinfo=KOLKATA).astimezone(UTC)
        plan.save(update_fields=["next_due_at"])
        result = process_due_booking_plans(now=plan.next_due_at + timedelta(minutes=1))
        plan.refresh_from_db()
        self.assertTrue(plan.needs_action)
        self.assertEqual(Appointment.objects.filter(booking_plan=plan).count(), 1)
        self.assertGreaterEqual(result.skipped, 1)

    def test_service_inactive_needs_action(self):
        ctx = self._seed_bookable_monday()
        self._create_plan(ctx, frequency="WEEK", interval=1, staff_id=ctx["staff"]["id"])
        plan = BookingPlan.objects.get()
        next_monday = ctx["monday"] + timedelta(days=7)
        plan.next_due_at = datetime.combine(next_monday, time(10, 0), tzinfo=KOLKATA).astimezone(
            UTC
        )
        plan.save(update_fields=["next_due_at"])
        Service.objects.filter(pk=ctx["service"]["id"]).update(is_active=False)
        process_due_booking_plans(now=plan.next_due_at + timedelta(minutes=1))
        plan.refresh_from_db()
        self.assertTrue(plan.needs_action)
        self.assertEqual(plan.needs_action_code, "SERVICE_INACTIVE")

    def test_price_change_snapshots_new_price_on_next_occurrence(self):
        ctx = self._seed_bookable_monday(buffer_before_minutes=0, buffer_after_minutes=0)
        self._create_plan(ctx, frequency="WEEK", interval=1, staff_id=ctx["staff"]["id"])
        first = Appointment.objects.get()
        first_price = first.total_price
        Service.objects.filter(pk=ctx["service"]["id"]).update(price="777.00")
        plan = BookingPlan.objects.get()
        next_monday = ctx["monday"] + timedelta(days=7)
        plan.next_due_at = datetime.combine(next_monday, time(10, 0), tzinfo=KOLKATA).astimezone(
            UTC
        )
        plan.save(update_fields=["next_due_at"])
        process_due_booking_plans(now=plan.next_due_at + timedelta(minutes=1))
        second = Appointment.objects.filter(booking_plan=plan).exclude(pk=first.pk).get()
        self.assertEqual(first.total_price, first_price)
        self.assertEqual(str(second.total_price), "777.00")


class BookingPlanConcurrencyTests(TransactionTestCase):
    def test_concurrent_process_creates_one_occurrence(self):
        owner = APIClient()
        register = owner.post(
            reverse("auth-register"),
            {
                "email": "conc-plan@example.com",
                "password": "StrongPass123",
                "organization_name": "Conc Plan Org",
            },
            format="json",
        )
        self.assertEqual(register.status_code, status.HTTP_201_CREATED)
        owner.credentials(HTTP_AUTHORIZATION=f"Bearer {register.data['access']}")
        from businesses.models import BusinessVertical

        business = owner.post(
            reverse("business-list"),
            {"name": "Plan Conc", "vertical": BusinessVertical.SALON},
            format="json",
        ).data
        location = owner.post(
            reverse("location-list", kwargs={"business_id": business["id"]}),
            {"name": "Main", "timezone": "Asia/Kolkata"},
            format="json",
        ).data
        service = owner.post(
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
        owner.post(
            reverse(
                "service-location-list",
                kwargs={"business_id": business["id"], "service_id": service["id"]},
            ),
            {"location_id": location["id"]},
            format="json",
        )
        staff = owner.post(
            reverse("staff-list", kwargs={"business_id": business["id"]}),
            {"display_name": "Priya", "location_id": location["id"]},
            format="json",
        ).data
        owner.post(
            reverse(
                "staff-service-list",
                kwargs={"business_id": business["id"], "staff_id": staff["id"]},
            ),
            {"service_id": service["id"]},
            format="json",
        )
        owner.post(
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
        monday = BookingAPITestCase()._next_weekday(Weekday.MONDAY)
        public = APIClient()
        created = public.post(
            reverse("public-booking-plan-create"),
            {
                "location_id": location["id"],
                "service_id": service["id"],
                "staff_id": staff["id"],
                "start": datetime.combine(monday, time(10, 0), tzinfo=KOLKATA).isoformat(),
                "customer": {"name": "Rahul", "phone": "9800000099"},
                "frequency": "WEEK",
                "interval": 1,
                "staff_preference": "SAME_STAFF",
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY="conc-plan-unique",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        plan = BookingPlan.objects.get()
        next_monday = monday + timedelta(days=7)
        due = datetime.combine(next_monday, time(10, 0), tzinfo=KOLKATA).astimezone(UTC)
        plan.next_due_at = due
        plan.save(update_fields=["next_due_at"])
        now = due + timedelta(minutes=1)

        def worker():
            connection.close()
            return process_due_booking_plans(now=now, limit=10)

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: worker(), range(2)))

        self.assertEqual(
            Appointment.objects.filter(
                booking_plan=plan,
                plan_occurrence_date=next_monday,
            ).count(),
            1,
        )
