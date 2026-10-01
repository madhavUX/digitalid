"""Phase 5.3 retention settings, segments, and list filters."""

from __future__ import annotations

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError

from accounts.models import User
from booking.models import AppointmentStatus
from booking.services import transition_appointment_status
from booking.tests.test_booking_api import BookingAPITestCase
from customers.models import Customer, RetentionSegment
from customers.services import (
    classify_retention_segment,
    get_customer_retention_status,
    get_or_create_retention_settings,
    update_retention_settings,
)
from organizations.models import Role


class CustomerRetentionSettingsTests(BookingAPITestCase):
    def test_defaults_permissions_and_validation(self):
        ctx = self._seed_bookable_monday(
            owner_email="segset@example.com",
            org_name="Seg Set",
            phone="+919800002201",
        )
        path = reverse(
            "customer-retention-settings",
            kwargs={"business_id": ctx["business"]["id"]},
        )
        got = self.client.get(path)
        self.assertEqual(got.status_code, status.HTTP_200_OK)
        self.assertEqual(got.data["return_after_days"], 30)
        self.assertEqual(got.data["inactive_after_days"], 90)
        self.assertTrue(got.data["enabled"])
        self.assertNotIn("id", got.data)
        self.assertNotIn("business", got.data)

        updated = self.client.patch(
            path,
            {"return_after_days": 21, "inactive_after_days": 60},
            format="json",
        )
        self.assertEqual(updated.status_code, status.HTTP_200_OK)
        self.assertEqual(updated.data["return_after_days"], 21)
        self.assertEqual(updated.data["inactive_after_days"], 60)

        bad = self.client.patch(
            path,
            {"return_after_days": 0},
            format="json",
        )
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)

        bad_order = self.client.patch(
            path,
            {"return_after_days": 40, "inactive_after_days": 40},
            format="json",
        )
        self.assertEqual(bad_order.status_code, status.HTTP_400_BAD_REQUEST)

        self._login_as_role("segset@example.com", Role.MANAGER, "segset-mgr@example.com")
        self.assertEqual(self.client.get(path).status_code, status.HTTP_200_OK)
        mgr_patch = self.client.patch(path, {"return_after_days": 25}, format="json")
        self.assertEqual(mgr_patch.status_code, status.HTTP_403_FORBIDDEN)

        self._login_as_role("segset@example.com", Role.STAFF, "segset-staff@example.com")
        self.assertEqual(self.client.get(path).status_code, status.HTTP_403_FORBIDDEN)
        staff_patch = self.client.patch(path, {"return_after_days": 25}, format="json")
        self.assertEqual(staff_patch.status_code, status.HTTP_403_FORBIDDEN)

        self._auth(ctx["token"])
        foreign = self._seed_bookable_monday(
            owner_email="segset2@example.com",
            org_name="Seg Set 2",
            phone="+919800002202",
        )
        self._auth(ctx["token"])
        cross = self.client.get(
            reverse(
                "customer-retention-settings",
                kwargs={"business_id": foreign["business"]["id"]},
            )
        )
        self.assertEqual(cross.status_code, status.HTTP_404_NOT_FOUND)


class CustomerRetentionSegmentTests(BookingAPITestCase):
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
        from booking.models import Appointment

        return Appointment.objects.get(pk=created.data["id"])

    def test_segment_priority_and_settings_change(self):
        self.assertEqual(
            classify_retention_segment(
                total_visits=0,
                days_since=None,
                return_after_days=30,
                inactive_after_days=90,
            ),
            RetentionSegment.NO_VISITS,
        )
        self.assertEqual(
            classify_retention_segment(
                total_visits=1,
                days_since=100,
                return_after_days=30,
                inactive_after_days=90,
            ),
            RetentionSegment.NEW,
        )
        self.assertEqual(
            classify_retention_segment(
                total_visits=2,
                days_since=10,
                return_after_days=30,
                inactive_after_days=90,
            ),
            RetentionSegment.RETURNING,
        )
        self.assertEqual(
            classify_retention_segment(
                total_visits=2,
                days_since=30,
                return_after_days=30,
                inactive_after_days=90,
            ),
            RetentionSegment.DUE_FOR_RETURN,
        )
        self.assertEqual(
            classify_retention_segment(
                total_visits=2,
                days_since=45,
                return_after_days=30,
                inactive_after_days=90,
            ),
            RetentionSegment.DUE_FOR_RETURN,
        )
        self.assertEqual(
            classify_retention_segment(
                total_visits=2,
                days_since=90,
                return_after_days=30,
                inactive_after_days=90,
            ),
            RetentionSegment.INACTIVE,
        )
        self.assertEqual(
            classify_retention_segment(
                total_visits=2,
                days_since=120,
                return_after_days=30,
                inactive_after_days=90,
            ),
            RetentionSegment.INACTIVE,
        )

        ctx = self._seed_bookable_monday(
            owner_email="seg1@example.com", org_name="Seg 1", phone="+919800002203"
        )
        owner = User.objects.get(email="seg1@example.com")
        customer = Customer.objects.get(pk=ctx["customer"]["id"])
        path = reverse(
            "customer-retention-summary",
            kwargs={
                "business_id": ctx["business"]["id"],
                "customer_id": customer.id,
            },
        )
        empty = self.client.get(path)
        self.assertEqual(empty.data["segment"], RetentionSegment.NO_VISITS)
        self.assertIsNone(empty.data["days_since_last_visit"])
        self.assertEqual(empty.data["return_after_days"], 30)

        first = self._complete(self._book_confirmed(ctx, "10:00"), owner)
        first.completed_at = timezone.now() - timedelta(days=5)
        first.save(update_fields=["completed_at"])
        from customers.services import refresh_customer_visit_totals

        refresh_customer_visit_totals(customer_id=customer.id)
        one = self.client.get(path)
        self.assertEqual(one.data["segment"], RetentionSegment.NEW)

        second = self._complete(self._book_confirmed(ctx, "12:00"), owner)
        second.completed_at = timezone.now() - timedelta(days=5)
        second.save(update_fields=["completed_at"])
        refresh_customer_visit_totals(customer_id=customer.id)
        returning = self.client.get(path)
        self.assertEqual(returning.data["segment"], RetentionSegment.RETURNING)

        second.completed_at = timezone.now() - timedelta(days=40)
        second.save(update_fields=["completed_at"])
        first.completed_at = timezone.now() - timedelta(days=50)
        first.save(update_fields=["completed_at"])
        refresh_customer_visit_totals(customer_id=customer.id)
        due = self.client.get(path)
        self.assertEqual(due.data["segment"], RetentionSegment.DUE_FOR_RETURN)
        self.assertEqual(due.data["days_since_last_visit"], 40)

        settings = get_or_create_retention_settings(
            organization=customer.organization,
            business=customer.business,
        )
        update_retention_settings(
            settings=settings,
            actor=owner,
            return_after_days=10,
            inactive_after_days=35,
        )
        flipped = self.client.get(path)
        self.assertEqual(flipped.data["segment"], RetentionSegment.INACTIVE)
        self.assertEqual(flipped.data["return_after_days"], 10)
        self.assertEqual(flipped.data["inactive_after_days"], 35)

        customer.refresh_from_db()
        status_payload = get_customer_retention_status(customer=customer)
        self.assertEqual(status_payload["segment"], RetentionSegment.INACTIVE)

        with self.assertRaises(ValidationError):
            update_retention_settings(
                settings=settings,
                actor=owner,
                return_after_days=50,
                inactive_after_days=40,
            )


class CustomerRetentionListFilterTests(BookingAPITestCase):
    def _complete(self, appointment, actor):
        return transition_appointment_status(
            appointment=appointment,
            actor=actor,
            new_status=AppointmentStatus.COMPLETED,
        )

    def _book(self, ctx, customer_id, hhmm, day=None):
        created = self.client.post(
            reverse("appointment-list", kwargs={"business_id": ctx["business"]["id"]}),
            {
                "location_id": ctx["location"]["id"],
                "customer_id": customer_id,
                "service_id": ctx["service"]["id"],
                "staff_id": ctx["staff"]["id"],
                "starts_at": self._local_iso(day or ctx["monday"], hhmm),
                "status": AppointmentStatus.CONFIRMED,
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        from booking.models import Appointment

        return Appointment.objects.get(pk=created.data["id"])

    def test_segment_filters_and_isolation(self):
        ctx = self._seed_bookable_monday(
            owner_email="seglist@example.com",
            org_name="Seg List",
            phone="+919800002210",
        )
        owner = User.objects.get(email="seglist@example.com")
        from customers.services import refresh_customer_visit_totals
        from staff.models import Weekday

        for weekday in (
            Weekday.TUESDAY,
            Weekday.WEDNESDAY,
            Weekday.THURSDAY,
            Weekday.FRIDAY,
        ):
            self._create_availability(
                ctx["business"]["id"],
                ctx["staff"]["id"],
                ctx["location"]["id"],
                weekday=weekday,
            )
        tuesday = ctx["monday"] + timedelta(days=1)
        wednesday = ctx["monday"] + timedelta(days=2)
        thursday = ctx["monday"] + timedelta(days=3)
        friday = ctx["monday"] + timedelta(days=4)

        none_c = Customer.objects.get(pk=ctx["customer"]["id"])

        new_c = Customer.objects.get(
            pk=self._create_customer(ctx["business"]["id"], phone="+919800002211")["id"]
        )
        a1 = self._complete(self._book(ctx, new_c.id, "10:00"), owner)
        a1.completed_at = timezone.now() - timedelta(days=3)
        a1.save(update_fields=["completed_at"])
        refresh_customer_visit_totals(customer_id=new_c.id)

        ret_c = Customer.objects.get(
            pk=self._create_customer(ctx["business"]["id"], phone="+919800002212")["id"]
        )
        r1 = self._complete(self._book(ctx, ret_c.id, "12:00"), owner)
        r2 = self._complete(self._book(ctx, ret_c.id, "14:00"), owner)
        r1.completed_at = timezone.now() - timedelta(days=10)
        r2.completed_at = timezone.now() - timedelta(days=5)
        r1.save(update_fields=["completed_at"])
        r2.save(update_fields=["completed_at"])
        refresh_customer_visit_totals(customer_id=ret_c.id)

        due_c = Customer.objects.get(
            pk=self._create_customer(ctx["business"]["id"], phone="+919800002213")["id"]
        )
        d1 = self._complete(self._book(ctx, due_c.id, "10:00", day=tuesday), owner)
        d2 = self._complete(self._book(ctx, due_c.id, "10:00", day=wednesday), owner)
        d1.completed_at = timezone.now() - timedelta(days=50)
        d2.completed_at = timezone.now() - timedelta(days=40)
        d1.save(update_fields=["completed_at"])
        d2.save(update_fields=["completed_at"])
        refresh_customer_visit_totals(customer_id=due_c.id)

        inactive_c = Customer.objects.get(
            pk=self._create_customer(ctx["business"]["id"], phone="+919800002214")["id"]
        )
        i1 = self._complete(self._book(ctx, inactive_c.id, "10:00", day=thursday), owner)
        i2 = self._complete(self._book(ctx, inactive_c.id, "10:00", day=friday), owner)
        i1.completed_at = timezone.now() - timedelta(days=120)
        i2.completed_at = timezone.now() - timedelta(days=100)
        i1.save(update_fields=["completed_at"])
        i2.save(update_fields=["completed_at"])
        refresh_customer_visit_totals(customer_id=inactive_c.id)

        list_path = reverse("customer-list", kwargs={"business_id": ctx["business"]["id"]})
        all_rows = self.client.get(list_path, {"limit": 50})
        self.assertEqual(all_rows.status_code, status.HTTP_200_OK)
        self.assertEqual(all_rows.data["count"], 5)

        def ids(segment):
            response = self.client.get(list_path, {"segment": segment, "limit": 50})
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            return {row["id"] for row in response.data["results"]}

        self.assertEqual(ids(RetentionSegment.NO_VISITS), {str(none_c.id)})
        self.assertEqual(ids(RetentionSegment.NEW), {str(new_c.id)})
        self.assertEqual(ids(RetentionSegment.RETURNING), {str(ret_c.id)})
        self.assertEqual(ids(RetentionSegment.DUE_FOR_RETURN), {str(due_c.id)})
        self.assertEqual(ids(RetentionSegment.INACTIVE), {str(inactive_c.id)})

        other = self._create_business(name="Other Seg Biz")
        other_customer = self._create_customer(other["id"], phone="+919800002215")
        leaked = self.client.get(list_path, {"segment": RetentionSegment.NO_VISITS})
        leaked_ids = {row["id"] for row in leaked.data["results"]}
        self.assertNotIn(other_customer["id"], leaked_ids)
        self.assertIn(str(none_c.id), leaked_ids)
