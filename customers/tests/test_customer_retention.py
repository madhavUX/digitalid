"""Customer visit totals from COMPLETED appointments. Retention foundation only."""

from __future__ import annotations

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from accounts.models import User
from booking.models import Appointment, AppointmentStatus
from booking.services import transition_appointment_status
from booking.tests.test_booking_api import BookingAPITestCase
from customers.models import Customer
from customers.services import (
    get_customer_retention_summary,
    reconcile_customer_visit_totals,
    refresh_customer_visit_totals,
)
from organizations.models import Role
from staff.models import Weekday


class CustomerRetentionFoundationTests(BookingAPITestCase):
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
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        return Appointment.objects.get(pk=created.data["id"])

    def test_only_completed_appointments_update_visit_totals(self):
        ctx = self._seed_bookable_monday(
            owner_email="ret1@example.com", org_name="Ret 1", phone="+919800000701"
        )
        owner = User.objects.get(email="ret1@example.com")
        customer = Customer.objects.get(pk=ctx["customer"]["id"])
        self.assertEqual(customer.total_visits, 0)

        pending = self.client.post(
            reverse("appointment-list", kwargs={"business_id": ctx["business"]["id"]}),
            {
                "location_id": ctx["location"]["id"],
                "customer_id": ctx["customer"]["id"],
                "service_id": ctx["service"]["id"],
                "staff_id": ctx["staff"]["id"],
                "starts_at": self._local_iso(ctx["monday"], "10:00"),
                "status": AppointmentStatus.PENDING,
            },
            format="json",
        )
        self.assertEqual(pending.status_code, status.HTTP_201_CREATED)
        customer.refresh_from_db()
        self.assertEqual(customer.total_visits, 0)

        confirmed = Appointment.objects.get(pk=pending.data["id"])
        transition_appointment_status(
            appointment=confirmed, actor=owner, new_status=AppointmentStatus.CONFIRMED
        )
        customer.refresh_from_db()
        self.assertEqual(customer.total_visits, 0)

        checked = transition_appointment_status(
            appointment=Appointment.objects.get(pk=confirmed.pk),
            actor=owner,
            new_status=AppointmentStatus.CHECKED_IN,
        )
        customer.refresh_from_db()
        self.assertEqual(customer.total_visits, 0)
        self.assertIsNone(checked.completed_at)

        completed = self._complete(Appointment.objects.get(pk=checked.pk), owner)
        self.assertIsNotNone(completed.completed_at)
        first_completed_at = completed.completed_at
        customer.refresh_from_db()
        self.assertEqual(customer.total_visits, 1)
        self.assertEqual(customer.first_visit_at, first_completed_at)
        self.assertEqual(customer.last_visit_at, first_completed_at)

        again = self.client.patch(
            reverse(
                "appointment-detail",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "appointment_id": completed.id,
                },
            ),
            {"status": AppointmentStatus.COMPLETED},
            format="json",
        )
        self.assertEqual(again.status_code, status.HTTP_200_OK)
        completed.refresh_from_db()
        self.assertEqual(completed.completed_at, first_completed_at)
        customer.refresh_from_db()
        self.assertEqual(customer.total_visits, 1)

        cancelled = self._book_confirmed(ctx, "12:00")
        transition_appointment_status(
            appointment=cancelled, actor=owner, new_status=AppointmentStatus.CANCELLED
        )
        customer.refresh_from_db()
        self.assertEqual(customer.total_visits, 1)

        no_show = self._book_confirmed(ctx, "14:00")
        transition_appointment_status(
            appointment=no_show, actor=owner, new_status=AppointmentStatus.NO_SHOW
        )
        customer.refresh_from_db()
        self.assertEqual(customer.total_visits, 1)

        second = self._complete(self._book_confirmed(ctx, "15:00"), owner)
        customer.refresh_from_db()
        self.assertEqual(customer.total_visits, 2)
        self.assertEqual(customer.first_visit_at, first_completed_at)
        self.assertEqual(customer.last_visit_at, second.completed_at)

        self._create_availability(
            ctx["business"]["id"],
            ctx["staff"]["id"],
            ctx["location"]["id"],
            weekday=Weekday.TUESDAY,
        )
        tuesday = ctx["monday"] + timedelta(days=1)
        soft_row = self._complete(self._book_confirmed(ctx, "10:00", day=tuesday), owner)
        customer.refresh_from_db()
        self.assertEqual(customer.total_visits, 3)
        soft_row.soft_delete(actor=owner)
        refresh_customer_visit_totals(customer_id=customer.id)
        customer.refresh_from_db()
        self.assertEqual(customer.total_visits, 2)
        self.assertEqual(customer.first_visit_at, first_completed_at)
        self.assertEqual(customer.last_visit_at, second.completed_at)

    def test_retention_summary_api_permissions_and_values(self):
        ctx = self._seed_bookable_monday(
            owner_email="ret2@example.com", org_name="Ret 2", phone="+919800000703"
        )
        owner = User.objects.get(email="ret2@example.com")
        path = reverse(
            "customer-retention-summary",
            kwargs={
                "business_id": ctx["business"]["id"],
                "customer_id": ctx["customer"]["id"],
            },
        )
        empty = self.client.get(path)
        self.assertEqual(empty.status_code, status.HTTP_200_OK)
        self.assertEqual(empty.data["customer_id"], str(ctx["customer"]["id"]))
        self.assertEqual(empty.data["total_visits"], 0)
        self.assertIsNone(empty.data["first_visit_at"])
        self.assertIsNone(empty.data["last_visit_at"])
        self.assertIsNone(empty.data["days_since_last_visit"])
        self.assertNotIn("phone", empty.data)
        self.assertNotIn("email", empty.data)

        first = self._complete(self._book_confirmed(ctx, "10:00"), owner)
        first.completed_at = timezone.now() - timedelta(days=5)
        first.save(update_fields=["completed_at"])
        refresh_customer_visit_totals(customer_id=ctx["customer"]["id"])
        one = self.client.get(path)
        self.assertEqual(one.data["total_visits"], 1)
        self.assertEqual(one.data["days_since_last_visit"], 5)

        self._complete(self._book_confirmed(ctx, "12:00"), owner)
        many = self.client.get(path)
        self.assertEqual(many.data["total_visits"], 2)
        self.assertEqual(many.data["days_since_last_visit"], 0)

        self._login_as_role("ret2@example.com", Role.MANAGER, "ret2-mgr@example.com")
        self.assertEqual(self.client.get(path).status_code, status.HTTP_200_OK)
        self._login_as_role("ret2@example.com", Role.STAFF, "ret2-staff@example.com")
        self.assertEqual(self.client.get(path).status_code, status.HTTP_200_OK)

        self._auth(ctx["token"])
        other_biz = self._create_business(name="Other Biz")
        other_customer = self._create_customer(other_biz["id"], phone="+919800000704")
        cross_biz = self.client.get(
            reverse(
                "customer-retention-summary",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "customer_id": other_customer["id"],
                },
            )
        )
        self.assertEqual(cross_biz.status_code, status.HTTP_404_NOT_FOUND)

        foreign = self._seed_bookable_monday(
            owner_email="ret3@example.com", org_name="Ret 3", phone="+919800000705"
        )
        self._auth(ctx["token"])
        cross_org = self.client.get(
            reverse(
                "customer-retention-summary",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "customer_id": foreign["customer"]["id"],
                },
            )
        )
        self.assertEqual(cross_org.status_code, status.HTTP_404_NOT_FOUND)

    def test_reconciliation_repairs_totals_and_is_idempotent(self):
        ctx = self._seed_bookable_monday(
            owner_email="ret4@example.com", org_name="Ret 4", phone="+919800000706"
        )
        owner = User.objects.get(email="ret4@example.com")
        customer = Customer.objects.get(pk=ctx["customer"]["id"])
        a = self._complete(self._book_confirmed(ctx, "10:00"), owner)
        self._complete(self._book_confirmed(ctx, "12:00"), owner)
        Appointment.objects.filter(pk=a.pk).update(completed_at=None)
        customer.total_visits = 99
        customer.first_visit_at = None
        customer.last_visit_at = None
        customer.save(update_fields=["total_visits", "first_visit_at", "last_visit_at"])

        cancelled = self._book_confirmed(ctx, "14:00")
        transition_appointment_status(
            appointment=cancelled, actor=owner, new_status=AppointmentStatus.CANCELLED
        )
        no_show = self._book_confirmed(ctx, "15:00")
        transition_appointment_status(
            appointment=no_show, actor=owner, new_status=AppointmentStatus.NO_SHOW
        )

        first = reconcile_customer_visit_totals(business_id=ctx["business"]["id"])
        customer.refresh_from_db()
        a.refresh_from_db()
        self.assertEqual(customer.total_visits, 2)
        self.assertIsNotNone(a.completed_at)
        self.assertIsNotNone(customer.first_visit_at)
        self.assertIsNotNone(customer.last_visit_at)
        self.assertLessEqual(customer.first_visit_at, customer.last_visit_at)
        self.assertEqual(first["updated"], 1)

        second = reconcile_customer_visit_totals(business_id=ctx["business"]["id"])
        customer.refresh_from_db()
        self.assertEqual(customer.total_visits, 2)
        self.assertEqual(second["updated"], 0)

        empty = self._create_customer(ctx["business"]["id"], phone="+919800000707")
        empty_row = Customer.objects.get(pk=empty["id"])
        empty_row.total_visits = 5
        empty_row.save(update_fields=["total_visits"])
        reconcile_customer_visit_totals(business_id=ctx["business"]["id"])
        empty_row.refresh_from_db()
        self.assertEqual(empty_row.total_visits, 0)
        self.assertIsNone(empty_row.first_visit_at)
        self.assertIsNone(empty_row.last_visit_at)

        out = StringIO()
        call_command("reconcile_customer_visits", stdout=out)
        self.assertIn("Customers processed:", out.getvalue())
        self.assertNotIn("+91", out.getvalue())

        summary = get_customer_retention_summary(customer=customer)
        self.assertEqual(summary["total_visits"], 2)
        self.assertNotIn("phone", summary)

        self._create_availability(
            ctx["business"]["id"],
            ctx["staff"]["id"],
            ctx["location"]["id"],
            weekday=Weekday.TUESDAY,
        )
        tuesday = ctx["monday"] + timedelta(days=1)
        soft = self._complete(self._book_confirmed(ctx, "10:00", day=tuesday), owner)
        soft.soft_delete(actor=owner)
        reconcile_customer_visit_totals(business_id=ctx["business"]["id"])
        customer.refresh_from_db()
        self.assertEqual(customer.total_visits, 2)

    def test_cross_business_appointments_do_not_affect_visit_totals(self):
        ctx_a = self._seed_bookable_monday(
            owner_email="ret5a@example.com", org_name="Ret 5", phone="+919800000708"
        )
        owner_a = User.objects.get(email="ret5a@example.com")
        self._complete(self._book_confirmed(ctx_a, "10:00"), owner_a)
        customer_a = Customer.objects.get(pk=ctx_a["customer"]["id"])
        customer_a.refresh_from_db()
        self.assertEqual(customer_a.total_visits, 1)

        biz_b = self._create_business(name="Biz B Ret")
        customer_b = Customer.objects.get(
            pk=self._create_customer(biz_b["id"], phone="+919800000709")["id"]
        )
        # Same org, different business: completing A must not change B's counters.
        customer_b.total_visits = 0
        customer_b.first_visit_at = None
        customer_b.last_visit_at = None
        customer_b.save(update_fields=["total_visits", "first_visit_at", "last_visit_at"])
        refresh_customer_visit_totals(customer_id=customer_a.id)
        customer_b.refresh_from_db()
        self.assertEqual(customer_b.total_visits, 0)
        self.assertIsNone(customer_b.first_visit_at)
        self.assertIsNone(customer_b.last_visit_at)

        refresh_customer_visit_totals(customer_id=customer_b.id)
        customer_b.refresh_from_db()
        self.assertEqual(customer_b.total_visits, 0)
        customer_a.refresh_from_db()
        self.assertEqual(customer_a.total_visits, 1)
