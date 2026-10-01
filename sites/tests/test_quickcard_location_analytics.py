"""Location-scoped QuickCard analytics. Business totals stay the default."""

from __future__ import annotations

import uuid
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
from locations.models import Location
from sites.models import QuickCard, QuickCardCtaType, QuickCardEvent, QuickCardEventType


class QuickCardLocationAnalyticsTests(PublicBookingAPITestCase):
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
        start = when or timezone.now()
        Appointment.objects.create(
            organization_id=card.organization_id,
            business_id=card.business_id,
            location_id=card.location_id,
            customer=business.customers.first(),
            staff_profile=business.staff_profiles.first(),
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

    def test_location_filter_splits_events_bookings_and_keeps_business_total(self):
        ctx = self._seed_bookable_monday(
            owner_email="locan1@example.com", org_name="Loc An 1", phone="+919800000601"
        )
        home = self._card(ctx, ctx["location"]["id"], "loc-home")
        uptown = self._create_location(ctx["business"]["id"], name="Uptown")
        second = self._card(ctx, uptown["id"], "loc-uptown")
        old = timezone.now() - timedelta(days=40)
        self._events(home, views=2, clicks={QuickCardCtaType.BOOK: 4, QuickCardCtaType.CALL: 1})
        self._events(second, views=5, clicks={QuickCardCtaType.BOOK: 1, QuickCardCtaType.SHARE: 3})
        self._events(home, clicks={QuickCardCtaType.BOOK: 9}, when=old)
        self._booking(home)
        self._booking(second)
        self._booking(second)
        stale = Appointment.objects.filter(acquisition_reference=home.id).get()
        stale.created_at = old
        stale.save(update_fields=["created_at"])
        self._booking(home)

        wide = self._summary(ctx["business"]["id"])
        self.assertEqual(wide.data["views"], 7)
        self.assertEqual(wide.data["cta_clicks"]["book"], 5)
        self.assertEqual(wide.data["cta_clicks"]["call"], 1)
        self.assertEqual(wide.data["cta_clicks"]["share"], 3)
        self.assertEqual(wide.data["bookings"], 3)
        self.assertEqual(wide.data["booking_conversion_rate"], 60.0)
        self.assertNotIn("location_id", wide.data)

        only_home = self._summary(ctx["business"]["id"], location_id=ctx["location"]["id"])
        self.assertEqual(only_home.status_code, status.HTTP_200_OK)
        self.assertEqual(only_home.data["views"], 2)
        self.assertEqual(only_home.data["cta_clicks"]["book"], 4)
        self.assertEqual(only_home.data["cta_clicks"]["share"], 0)
        self.assertEqual(only_home.data["bookings"], 1)
        self.assertEqual(only_home.data["booking_conversion_rate"], 25.0)

        only_uptown = self._summary(ctx["business"]["id"], location_id=uptown["id"])
        self.assertEqual(only_uptown.data["views"], 5)
        self.assertEqual(only_uptown.data["cta_clicks"]["book"], 1)
        self.assertEqual(only_uptown.data["bookings"], 2)
        self.assertEqual(only_uptown.data["booking_conversion_rate"], 200.0)

        quiet = self._summary(
            ctx["business"]["id"],
            location_id=uptown["id"],
            date_from=(timezone.now() - timedelta(days=1)).date().isoformat(),
        )
        self.assertEqual(quiet.data["cta_clicks"]["book"], 1)
        self.assertEqual(quiet.data["bookings"], 2)

        ranged = self._summary(
            ctx["business"]["id"],
            location_id=ctx["location"]["id"],
            date_from=(timezone.now() - timedelta(days=50)).date().isoformat(),
        )
        self.assertEqual(ranged.data["cta_clicks"]["book"], 13)
        self.assertEqual(ranged.data["bookings"], 2)
        self.assertEqual(only_uptown.data["bookings"], 2)

        QuickCard.objects.get(slug="loc-home").delete()
        QuickCard.objects.get(slug="loc-uptown").delete()
        after = self._summary(ctx["business"]["id"], location_id=ctx["location"]["id"])
        self.assertEqual(after.data["bookings"], 1)
        self.assertEqual(after.data["views"], 2)
        other_place = self._summary(ctx["business"]["id"], location_id=uptown["id"])
        self.assertEqual(other_place.data["bookings"], 2)
        self.assertEqual(other_place.data["views"], 5)

    def test_unknown_and_foreign_locations_are_not_found(self):
        ctx = self._seed_bookable_monday(
            owner_email="locan3@example.com", org_name="Loc An 3", phone="+919800000603"
        )
        other_business = self._create_business(name="Other Salon")
        other_location = self._create_location(other_business["id"], name="Elsewhere")
        foreign = self._seed_bookable_monday(
            owner_email="locan4@example.com", org_name="Loc An 4", phone="+919800000604"
        )
        self._auth(ctx["token"])
        path = reverse("quickcard-analytics", kwargs={"business_id": ctx["business"]["id"]})
        missing = self.client.get(path, {"location_id": str(uuid.uuid4())})
        malformed = self.client.get(path, {"location_id": "not-a-location"})
        cross_business = self.client.get(path, {"location_id": other_location["id"]})
        cross_org = self.client.get(path, {"location_id": foreign["location"]["id"]})
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(malformed.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(cross_business.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(cross_org.status_code, status.HTTP_404_NOT_FOUND)
        Location.objects.get(pk=ctx["location"]["id"]).delete()
        deleted = self.client.get(path, {"location_id": ctx["location"]["id"]})
        self.assertEqual(deleted.status_code, status.HTTP_404_NOT_FOUND)

    def test_location_filter_query_count_stays_flat(self):
        ctx = self._seed_bookable_monday(
            owner_email="locan5@example.com", org_name="Loc An 5", phone="+919800000605"
        )
        card = self._card(ctx, ctx["location"]["id"], "loc-queries")
        self._events(card, views=2, clicks={QuickCardCtaType.BOOK: 1})
        self._booking(card)
        path = reverse("quickcard-analytics", kwargs={"business_id": ctx["business"]["id"]})
        query = {"location_id": ctx["location"]["id"]}
        with CaptureQueriesContext(connection) as first:
            self.assertEqual(self.client.get(path, query).status_code, status.HTTP_200_OK)
        self._events(card, views=30, clicks={QuickCardCtaType.BOOK: 30})
        with CaptureQueriesContext(connection) as second:
            self.assertEqual(self.client.get(path, query).status_code, status.HTTP_200_OK)
        self.assertLessEqual(len(first), 12)
        self.assertEqual(len(first), len(second))

    def test_location_with_no_book_clicks_has_null_conversion(self):
        ctx = self._seed_bookable_monday(
            owner_email="locan6@example.com", org_name="Loc An 6", phone="+919800000606"
        )
        self._card(ctx, ctx["location"]["id"], "loc-empty-clicks")
        summary = self._summary(ctx["business"]["id"], location_id=ctx["location"]["id"])
        self.assertEqual(summary.data["cta_clicks"]["book"], 0)
        self.assertEqual(summary.data["bookings"], 0)
        self.assertIsNone(summary.data["booking_conversion_rate"])
