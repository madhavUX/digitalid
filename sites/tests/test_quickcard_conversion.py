"""Book Now click to attributed booking conversion. No visitor identity."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from booking.models import Appointment, AppointmentStatus
from booking.tests.test_public_booking_api import PublicBookingAPITestCase
from businesses.models import Business
from sites.models import QuickCard, QuickCardCtaType, QuickCardEvent, QuickCardEventType


class QuickCardConversionTests(PublicBookingAPITestCase):
    def _card(self, ctx, location_id, slug):
        created = self.client.post(
            reverse(
                "quickcard-detail",
                kwargs={"business_id": ctx["business"]["id"], "location_id": location_id},
            ),
            {"slug": slug, "headline": "Book"},
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        published = self.client.post(
            reverse(
                "quickcard-publish",
                kwargs={"business_id": ctx["business"]["id"], "location_id": location_id},
            )
        )
        self.assertEqual(published.status_code, status.HTTP_200_OK)
        return QuickCard.objects.get(slug=slug)

    def _events(self, card, *, views=0, clicks=None, when=None):
        clicks = clicks or {}
        moment = when or timezone.now()
        rows = [
            QuickCardEvent(
                organization_id=card.organization_id,
                business_id=card.business_id,
                location_id=card.location_id,
                quickcard=card,
                event_type=QuickCardEventType.PAGE_VIEW,
                cta_type="",
                occurred_at=moment,
            )
            for _ in range(views)
        ]
        for cta, count in clicks.items():
            rows.extend(
                QuickCardEvent(
                    organization_id=card.organization_id,
                    business_id=card.business_id,
                    location_id=card.location_id,
                    quickcard=card,
                    event_type=QuickCardEventType.CTA_CLICK,
                    cta_type=cta,
                    occurred_at=moment,
                )
                for _ in range(count)
            )
        QuickCardEvent.objects.bulk_create(rows)

    def _booking(self, card, *, when=None):
        business = Business.objects.get(pk=card.business_id)
        staff = business.staff_profiles.first()
        customer = business.customers.first()
        start = when or timezone.now()
        Appointment.objects.create(
            organization_id=card.organization_id,
            business_id=card.business_id,
            location_id=card.location_id,
            customer=customer,
            staff_profile=staff,
            starts_at=start,
            ends_at=start + timedelta(minutes=30),
            occupancy_starts_at=start,
            occupancy_ends_at=start + timedelta(minutes=30),
            status=AppointmentStatus.CANCELLED,
            total_price=Decimal("0.00"),
            acquisition_source="QUICKCARD",
            acquisition_reference=card.id,
        )

    def _summary(self, business_id, **query):
        return self.client.get(
            reverse("quickcard-analytics", kwargs={"business_id": business_id}),
            query,
        )

    def test_conversion_uses_book_clicks_and_attributed_bookings(self):
        ctx = self._seed_bookable_monday(
            owner_email="conv1@example.com", org_name="Conv 1", phone="+919800000501"
        )
        card = self._card(ctx, ctx["location"]["id"], "conv-home")
        self._events(
            card,
            views=9,
            clicks={
                QuickCardCtaType.BOOK: 100,
                QuickCardCtaType.WHATSAPP: 4,
                QuickCardCtaType.CALL: 3,
                QuickCardCtaType.DIRECTIONS: 2,
                QuickCardCtaType.REVIEW: 1,
                QuickCardCtaType.SHARE: 6,
            },
        )
        for _ in range(8):
            self._booking(card)
        summary = self._summary(ctx["business"]["id"])
        self.assertEqual(summary.status_code, status.HTTP_200_OK)
        self.assertEqual(summary.data["views"], 9)
        self.assertEqual(summary.data["cta_clicks"]["book"], 100)
        self.assertEqual(summary.data["bookings"], 8)
        self.assertEqual(summary.data["booking_conversion_rate"], 8.0)

        quiet = self._seed_bookable_monday(
            owner_email="conv2@example.com", org_name="Conv 2", phone="+919800000502"
        )
        quiet_card = self._card(quiet, quiet["location"]["id"], "conv-quiet")
        self._events(quiet_card, clicks={QuickCardCtaType.BOOK: 10})
        none_booked = self._summary(quiet["business"]["id"])
        self.assertEqual(none_booked.data["bookings"], 0)
        self.assertEqual(none_booked.data["booking_conversion_rate"], 0.0)

        empty = self._seed_bookable_monday(
            owner_email="conv3@example.com", org_name="Conv 3", phone="+919800000503"
        )
        self._card(empty, empty["location"]["id"], "conv-empty")
        undefined = self._summary(empty["business"]["id"])
        self.assertEqual(undefined.data["cta_clicks"]["book"], 0)
        self.assertIsNone(undefined.data["booking_conversion_rate"])

    def test_window_multiple_cards_and_foreign_references(self):
        ctx = self._seed_bookable_monday(
            owner_email="conv4@example.com", org_name="Conv 4", phone="+919800000504"
        )
        home = self._card(ctx, ctx["location"]["id"], "conv-a")
        other_location = self._create_location(ctx["business"]["id"], name="Uptown")
        second = self._card(ctx, other_location["id"], "conv-b")
        self._events(home, clicks={QuickCardCtaType.BOOK: 2})
        self._events(second, clicks={QuickCardCtaType.BOOK: 2})
        self._booking(home)
        self._booking(second)
        stale_click = QuickCardEvent.objects.filter(
            quickcard=home, cta_type=QuickCardCtaType.BOOK
        ).first()
        stale_click.occurred_at = timezone.now() - timedelta(days=40)
        stale_click.save(update_fields=["occurred_at", "updated_at"])
        stale_booking = Appointment.objects.filter(acquisition_reference=second.id).get()
        stale_booking.created_at = timezone.now() - timedelta(days=40)
        stale_booking.save(update_fields=["created_at"])

        other = self._seed_bookable_monday(
            owner_email="conv5@example.com", org_name="Conv 5", phone="+919800000505"
        )
        foreign = self._card(other, other["location"]["id"], "conv-foreign")
        self._auth(ctx["token"])
        self._booking(home)
        stray = (
            Appointment.objects.filter(acquisition_reference=home.id)
            .order_by("-created_at")
            .first()
        )
        stray.acquisition_reference = foreign.id
        stray.save(update_fields=["acquisition_reference"])

        summary = self._summary(ctx["business"]["id"])
        self.assertEqual(summary.data["cta_clicks"]["book"], 3)
        self.assertEqual(summary.data["bookings"], 1)
        self.assertEqual(summary.data["booking_conversion_rate"], 33.3)

        wide = self._summary(
            ctx["business"]["id"],
            date_from=(timezone.now() - timedelta(days=50)).date().isoformat(),
        )
        self.assertEqual(wide.data["cta_clicks"]["book"], 4)
        self.assertEqual(wide.data["bookings"], 2)

        QuickCard.objects.get(slug="conv-a").delete()
        after_delete = self._summary(ctx["business"]["id"])
        self.assertEqual(after_delete.data["bookings"], 1)
        self.assertEqual(after_delete.data["booking_conversion_rate"], 33.3)

        self._auth(other["token"])
        foreign_summary = self._summary(other["business"]["id"])
        self.assertEqual(foreign_summary.data["bookings"], 0)
        self.assertIsNone(foreign_summary.data["booking_conversion_rate"])

    def test_unmatched_click_and_booking_counts_can_exceed_one_hundred(self):
        ctx = self._seed_bookable_monday(
            owner_email="conv6@example.com", org_name="Conv 6", phone="+919800000506"
        )
        card = self._card(ctx, ctx["location"]["id"], "conv-over")
        self._events(card, clicks={QuickCardCtaType.BOOK: 1})
        self._booking(card)
        self._booking(card)
        summary = self._summary(ctx["business"]["id"])
        self.assertEqual(summary.data["booking_conversion_rate"], 200.0)

    def test_aggregation_query_count_does_not_grow_with_rows(self):
        ctx = self._seed_bookable_monday(
            owner_email="conv7@example.com", org_name="Conv 7", phone="+919800000507"
        )
        card = self._card(ctx, ctx["location"]["id"], "conv-queries")
        self._events(card, views=2, clicks={QuickCardCtaType.BOOK: 2})
        self._booking(card)
        path = reverse("quickcard-analytics", kwargs={"business_id": ctx["business"]["id"]})
        with CaptureQueriesContext(connection) as first:
            self.assertEqual(self.client.get(path).status_code, status.HTTP_200_OK)
        self._events(card, views=40, clicks={QuickCardCtaType.BOOK: 40})
        with CaptureQueriesContext(connection) as second:
            self.assertEqual(self.client.get(path).status_code, status.HTTP_200_OK)
        self.assertLessEqual(len(first), 12)
        self.assertEqual(len(first), len(second))
