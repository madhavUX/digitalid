"""Retention booking attribution. Invalid refs still book without a source."""

from __future__ import annotations

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from booking.models import Appointment, AppointmentSource
from booking.tests.test_public_booking_api import PublicBookingAPITestCase
from customers.models import (
    Customer,
    CustomerRetentionMessage,
    CustomerRetentionMessageStatus,
    RetentionSegment,
)
from locations.models import Location


class RetentionAttributionTests(PublicBookingAPITestCase):
    def _retention_row(
        self,
        ctx,
        *,
        customer,
        status=CustomerRetentionMessageStatus.SENT,
        location=None,
    ):
        loc = location
        if loc is None:
            loc = Location.objects.get(pk=ctx["location"]["id"])
        return CustomerRetentionMessage.objects.create(
            organization_id=customer.organization_id,
            business_id=customer.business_id,
            customer=customer,
            location=loc,
            segment=RetentionSegment.DUE_FOR_RETURN,
            trigger_visit_at=customer.last_visit_at or timezone.now() - timedelta(days=40),
            scheduled_for=timezone.now() - timedelta(hours=1),
            status=status,
            idempotency_key=f"retention:due:{customer.id}:{timezone.now().timestamp()}",
        )

    def _book(self, ctx, phone, hhmm="10:00", **extra):
        payload = self._book_payload(ctx, hhmm, staff_id=ctx["staff"]["id"], phone=phone)
        payload.update(extra)
        return self._public_create(payload)

    def _seed(self, **kwargs):
        defaults = {
            "buffer_before_minutes": 0,
            "buffer_after_minutes": 0,
        }
        defaults.update(kwargs)
        return self._seed_bookable_monday(**defaults)

    def test_valid_retention_attribution_persists_uuid(self):
        ctx = self._seed(
            owner_email="retattr@example.com",
            org_name="Ret Attr",
            phone="+919811100201",
        )
        customer = Customer.objects.get(pk=ctx["customer"]["id"])
        row = self._retention_row(ctx, customer=customer)
        created = self._book(
            ctx,
            "9811100201",
            attribution_source="retention",
            attribution_ref=row.public_reference,
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        self.assertNotIn("acquisition_source", created.data)
        self.assertNotIn("acquisition_reference", created.data)
        appointment = Appointment.objects.get(public_reference=created.data["public_reference"])
        self.assertEqual(appointment.source, AppointmentSource.ONLINE)
        self.assertEqual(appointment.acquisition_source, "RETENTION")
        self.assertEqual(appointment.acquisition_reference, row.id)

    def test_invalid_malformed_missing_and_cancelled_do_not_attribute(self):
        ctx = self._seed(
            owner_email="retattr2@example.com",
            org_name="Ret Attr 2",
            phone="+919811100202",
        )
        customer = Customer.objects.get(pk=ctx["customer"]["id"])
        row = self._retention_row(ctx, customer=customer)

        missing = self._book(ctx, "9811100202", "10:00")
        self.assertEqual(missing.status_code, status.HTTP_201_CREATED, missing.data)
        self.assertIsNone(
            Appointment.objects.get(
                public_reference=missing.data["public_reference"]
            ).acquisition_source
        )

        malformed = self._book(
            ctx,
            "9811100203",
            "11:00",
            attribution_source="retention",
            attribution_ref="not-a-real-ref",
        )
        self.assertEqual(malformed.status_code, status.HTTP_201_CREATED, malformed.data)
        self.assertIsNone(
            Appointment.objects.get(
                public_reference=malformed.data["public_reference"]
            ).acquisition_source
        )

        empty_ref = self._book(
            ctx,
            "9811100204",
            "12:00",
            attribution_source="retention",
            attribution_ref="",
        )
        self.assertEqual(empty_ref.status_code, status.HTTP_201_CREATED, empty_ref.data)
        self.assertIsNone(
            Appointment.objects.get(
                public_reference=empty_ref.data["public_reference"]
            ).acquisition_source
        )

        cancelled = self._retention_row(
            ctx,
            customer=customer,
            status=CustomerRetentionMessageStatus.CANCELLED,
        )
        cancelled_book = self._book(
            ctx,
            "9811100205",
            "13:00",
            attribution_source="retention",
            attribution_ref=cancelled.public_reference,
        )
        self.assertEqual(cancelled_book.status_code, status.HTTP_201_CREATED, cancelled_book.data)
        self.assertIsNone(
            Appointment.objects.get(
                public_reference=cancelled_book.data["public_reference"]
            ).acquisition_source
        )

        ok = self._book(
            ctx,
            "9811100202",
            "14:00",
            attribution_source="retention",
            attribution_ref=row.public_reference,
        )
        self.assertEqual(ok.status_code, status.HTTP_201_CREATED, ok.data)
        self.assertEqual(
            Appointment.objects.get(
                public_reference=ok.data["public_reference"]
            ).acquisition_source,
            "RETENTION",
        )

    def test_cross_location_business_org_and_customer_rejected(self):
        ctx = self._seed(
            owner_email="retattr3@example.com",
            org_name="Ret Attr 3",
            phone="+919811100301",
        )
        customer = Customer.objects.get(pk=ctx["customer"]["id"])
        row = self._retention_row(ctx, customer=customer)

        other_location = self._create_location(ctx["business"]["id"], name="Uptown Ret")
        row.location_id = other_location["id"]
        row.save(update_fields=["location_id", "updated_at"])
        cross_loc = self._book(
            ctx,
            "9811100301",
            attribution_source="retention",
            attribution_ref=row.public_reference,
        )
        self.assertEqual(cross_loc.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(
            Appointment.objects.get(
                public_reference=cross_loc.data["public_reference"]
            ).acquisition_source
        )

        row.location_id = ctx["location"]["id"]
        row.save(update_fields=["location_id", "updated_at"])

        other = self._seed(
            owner_email="retattr4@example.com",
            org_name="Ret Attr 4",
            phone="+919811100401",
        )
        foreign = self._book(
            other,
            "9811100401",
            attribution_source="retention",
            attribution_ref=row.public_reference,
        )
        self.assertEqual(foreign.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(
            Appointment.objects.get(
                public_reference=foreign.data["public_reference"]
            ).acquisition_source
        )

        other_customer = self._book(
            ctx,
            "9811100309",
            "12:00",
            attribution_source="retention",
            attribution_ref=row.public_reference,
        )
        self.assertEqual(other_customer.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(
            Appointment.objects.get(
                public_reference=other_customer.data["public_reference"]
            ).acquisition_source
        )

    def test_normal_and_quickcard_remain_unchanged(self):
        ctx = self._seed(
            owner_email="retattr5@example.com",
            org_name="Ret Attr 5",
            phone="+919811100501",
        )
        direct = self._book(ctx, "9811100501")
        plain = Appointment.objects.get(public_reference=direct.data["public_reference"])
        self.assertEqual(plain.source, AppointmentSource.ONLINE)
        self.assertIsNone(plain.acquisition_source)
        self.assertIsNone(plain.acquisition_reference)

        created = self.client.post(
            reverse(
                "quickcard-detail",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            ),
            {"slug": "ret-qc", "headline": "Book"},
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.client.post(
            reverse(
                "quickcard-publish",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            )
        )
        qc = self._book(
            ctx,
            "9811100502",
            "12:00",
            attribution_source="quickcard",
            attribution_ref="ret-qc",
        )
        self.assertEqual(qc.status_code, status.HTTP_201_CREATED)
        stored = Appointment.objects.get(public_reference=qc.data["public_reference"])
        self.assertEqual(stored.acquisition_source, "QUICKCARD")
        self.assertIsNotNone(stored.acquisition_reference)
        self.assertNotEqual(stored.acquisition_source, "RETENTION")
