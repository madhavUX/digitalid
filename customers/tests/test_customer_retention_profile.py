"""Phase 5.2 retention profile: recent visits and factual history aggregates."""

from __future__ import annotations

from datetime import timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from accounts.models import User
from booking.models import Appointment, AppointmentStatus
from booking.services import transition_appointment_status
from booking.tests.test_booking_api import BookingAPITestCase
from catalog.models import Service
from customers.models import Customer
from organizations.models import Role
from staff.models import Weekday


class CustomerRetentionProfileTests(BookingAPITestCase):
    def _complete(self, appointment, actor):
        return transition_appointment_status(
            appointment=appointment,
            actor=actor,
            new_status=AppointmentStatus.COMPLETED,
        )

    def _book_confirmed(self, ctx, hhmm="10:00", day=None):
        created = self.client.post(
            reverse("appointment-list", kwargs={"business_id": ctx["business"]["id"]}),
            {
                "location_id": ctx["location"]["id"],
                "customer_id": ctx["customer"]["id"],
                "service_id": ctx["service"]["id"],
                "staff_id": ctx["staff"]["id"],
                "starts_at": self._local_iso(day or ctx["monday"], hhmm),
                "status": AppointmentStatus.CONFIRMED,
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        return Appointment.objects.get(pk=created.data["id"])

    def _path(self, ctx, customer_id=None):
        return reverse(
            "customer-retention-summary",
            kwargs={
                "business_id": ctx["business"]["id"],
                "customer_id": customer_id or ctx["customer"]["id"],
            },
        )

    def _enable_weekdays(self, ctx, weekdays):
        for weekday in weekdays:
            self._create_availability(
                ctx["business"]["id"],
                ctx["staff"]["id"],
                ctx["location"]["id"],
                weekday=weekday,
            )

    def test_zero_one_and_multiple_visits_profile(self):
        ctx = self._seed_bookable_monday(
            owner_email="prof1@example.com", org_name="Prof 1", phone="+919800001101"
        )
        owner = User.objects.get(email="prof1@example.com")
        path = self._path(ctx)

        empty = self.client.get(path)
        self.assertEqual(empty.status_code, status.HTTP_200_OK)
        self.assertEqual(empty.data["total_visits"], 0)
        self.assertEqual(empty.data["completed_appointments"], 0)
        self.assertIsNone(empty.data["first_visit_at"])
        self.assertIsNone(empty.data["last_visit_at"])
        self.assertIsNone(empty.data["days_since_last_visit"])
        self.assertIsNone(empty.data["average_days_between_visits"])
        self.assertEqual(empty.data["visits"], [])
        self.assertEqual(empty.data["service_history"], [])
        self.assertEqual(empty.data["staff_history"], [])
        self.assertEqual(empty.data["location_history"], [])
        self.assertNotIn("phone", empty.data)
        self.assertNotIn("email", empty.data)

        first = self._complete(self._book_confirmed(ctx, "10:00"), owner)
        one = self.client.get(path)
        self.assertEqual(one.data["total_visits"], 1)
        self.assertEqual(one.data["completed_appointments"], 1)
        self.assertIsNone(one.data["average_days_between_visits"])
        self.assertEqual(len(one.data["visits"]), 1)
        visit = one.data["visits"][0]
        self.assertEqual(visit["appointment_reference"], first.public_reference)
        self.assertEqual(visit["service"], "Haircut")
        self.assertEqual(visit["staff"], "Priya")
        self.assertEqual(visit["location"], ctx["location"]["name"])
        self.assertEqual(visit["price_snapshot"], "499.00")
        self.assertEqual(visit["currency"], "INR")
        self.assertEqual(one.data["service_history"][0]["service_name"], "Haircut")
        self.assertEqual(one.data["service_history"][0]["visit_count"], 1)
        self.assertEqual(one.data["staff_history"][0]["staff_name"], "Priya")
        self.assertEqual(one.data["location_history"][0]["visit_count"], 1)

        second = self._complete(self._book_confirmed(ctx, "12:00"), owner)
        first.completed_at = timezone.now() - timedelta(days=40)
        first.save(update_fields=["completed_at"])
        second.completed_at = timezone.now() - timedelta(days=10)
        second.save(update_fields=["completed_at"])
        from customers.services import refresh_customer_visit_totals

        refresh_customer_visit_totals(customer_id=ctx["customer"]["id"])
        many = self.client.get(path)
        self.assertEqual(many.data["total_visits"], 2)
        self.assertEqual(many.data["average_days_between_visits"], 30.0)
        self.assertEqual(len(many.data["visits"]), 2)
        self.assertEqual(many.data["visits"][0]["appointment_reference"], second.public_reference)
        self.assertEqual(many.data["visits"][1]["appointment_reference"], first.public_reference)
        self.assertEqual(many.data["service_history"][0]["visit_count"], 2)

    def test_recent_visits_cap_exclusions_and_snapshot(self):
        ctx = self._seed_bookable_monday(
            owner_email="prof2@example.com",
            org_name="Prof 2",
            phone="+919800001102",
            staff_name="Asha",
        )
        owner = User.objects.get(email="prof2@example.com")
        self._enable_weekdays(
            ctx,
            [
                Weekday.TUESDAY,
                Weekday.WEDNESDAY,
                Weekday.THURSDAY,
                Weekday.FRIDAY,
                Weekday.SATURDAY,
                Weekday.SUNDAY,
            ],
        )
        refs = []
        for offset in range(11):
            day = ctx["monday"] + timedelta(days=offset)
            appt = self._complete(self._book_confirmed(ctx, "10:00", day=day), owner)
            refs.append(appt.public_reference)

        cancelled = self._book_confirmed(ctx, "12:00", day=ctx["monday"] + timedelta(days=1))
        transition_appointment_status(
            appointment=cancelled, actor=owner, new_status=AppointmentStatus.CANCELLED
        )
        no_show = self._book_confirmed(ctx, "12:00", day=ctx["monday"] + timedelta(days=2))
        transition_appointment_status(
            appointment=no_show, actor=owner, new_status=AppointmentStatus.NO_SHOW
        )
        soft = Appointment.objects.get(public_reference=refs[0])
        soft.soft_delete(actor=owner)
        from customers.services import refresh_customer_visit_totals

        refresh_customer_visit_totals(customer_id=ctx["customer"]["id"])

        Service.objects.filter(pk=ctx["service"]["id"]).update(name="New Cut Name")
        data = self.client.get(self._path(ctx)).data
        self.assertEqual(data["total_visits"], 10)
        self.assertEqual(len(data["visits"]), 10)
        self.assertNotIn(refs[0], [v["appointment_reference"] for v in data["visits"]])
        self.assertEqual(data["visits"][0]["appointment_reference"], refs[-1])
        self.assertEqual(data["service_history"][0]["service_name"], "Haircut")
        self.assertNotEqual(data["service_history"][0]["service_name"], "New Cut Name")
        self.assertEqual(data["staff_history"][0]["staff_name"], "Asha")

    def test_permissions_tenant_isolation_and_query_bound(self):
        ctx = self._seed_bookable_monday(
            owner_email="prof3@example.com", org_name="Prof 3", phone="+919800001103"
        )
        owner = User.objects.get(email="prof3@example.com")
        self._complete(self._book_confirmed(ctx, "10:00"), owner)
        path = self._path(ctx)

        self.assertEqual(self.client.get(path).status_code, status.HTTP_200_OK)
        self._login_as_role("prof3@example.com", Role.MANAGER, "prof3-mgr@example.com")
        self.assertEqual(self.client.get(path).status_code, status.HTTP_200_OK)
        self._login_as_role("prof3@example.com", Role.STAFF, "prof3-staff@example.com")
        self.assertEqual(self.client.get(path).status_code, status.HTTP_200_OK)

        self._auth(ctx["token"])
        other_biz = self._create_business(name="Other Biz Prof")
        other_customer = self._create_customer(other_biz["id"], phone="+919800001104")
        cross_biz = self.client.get(self._path(ctx, customer_id=other_customer["id"]))
        self.assertEqual(cross_biz.status_code, status.HTTP_404_NOT_FOUND)

        foreign = self._seed_bookable_monday(
            owner_email="prof4@example.com", org_name="Prof 4", phone="+919800001105"
        )
        self._auth(ctx["token"])
        cross_org = self.client.get(self._path(ctx, customer_id=foreign["customer"]["id"]))
        self.assertEqual(cross_org.status_code, status.HTTP_404_NOT_FOUND)

        # Business B customer must not receive Business A visit rows.
        self._auth(ctx["token"])
        biz_b = self._create_business(name="Biz B Prof")
        customer_b = self._create_customer(biz_b["id"], phone="+919800001106")
        summary_b = self.client.get(
            reverse(
                "customer-retention-summary",
                kwargs={
                    "business_id": biz_b["id"],
                    "customer_id": customer_b["id"],
                },
            )
        )
        self.assertEqual(summary_b.status_code, status.HTTP_200_OK)
        self.assertEqual(summary_b.data["total_visits"], 0)
        self.assertEqual(summary_b.data["visits"], [])

        with CaptureQueriesContext(connection) as captured:
            self.assertEqual(self.client.get(path).status_code, status.HTTP_200_OK)
        self.assertLessEqual(len(captured), 20)

        customer = Customer.objects.get(pk=ctx["customer"]["id"])
        self.assertEqual(customer.total_visits, 1)
