"""QuickCard booking attribution. Invalid refs still book, without a source."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from booking.models import Appointment
from booking.tests.test_booking_api import KOLKATA
from booking.tests.test_public_booking_api import PublicBookingAPITestCase
from sites.models import QuickCard
from staff.models import Weekday


class QuickCardAttributionTests(PublicBookingAPITestCase):
    def _card(self, ctx, slug="qc-downtown", published=True):
        created = self.client.post(
            reverse(
                "quickcard-detail",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": ctx["location"]["id"],
                },
            ),
            {"slug": slug, "headline": "Book"},
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        if published:
            published_resp = self.client.post(
                reverse(
                    "quickcard-publish",
                    kwargs={
                        "business_id": ctx["business"]["id"],
                        "location_id": ctx["location"]["id"],
                    },
                )
            )
            self.assertEqual(published_resp.status_code, status.HTTP_200_OK)
        return created.data["slug"]

    def _book(self, ctx, phone, hhmm="10:00", **extra):
        payload = self._book_payload(ctx, hhmm, staff_id=ctx["staff"]["id"], phone=phone)
        payload.update(extra)
        return self._public_create(payload)

    def test_valid_quickcard_is_stored_and_direct_booking_is_not(self):
        ctx = self._seed_bookable_monday(owner_email="attr@example.com", org_name="Attr")
        slug = self._card(ctx)
        public = self.public.get(reverse("public-quickcard-detail", kwargs={"slug": slug}))
        self.assertEqual(public.status_code, status.HTTP_200_OK)
        self.assertTrue(
            public.data["actions"]["booking_url"].startswith(f"/book/{ctx['location']['slug']}?")
        )
        self.assertIn("source=quickcard", public.data["actions"]["booking_url"])
        self.assertIn(f"ref={slug}", public.data["actions"]["booking_url"])
        self.assertNotIn(ctx["business"]["id"], public.data["actions"]["booking_url"])

        attributed = self._book(
            ctx,
            "9811100101",
            attribution_source="quickcard",
            attribution_ref=slug,
        )
        self.assertEqual(attributed.status_code, status.HTTP_201_CREATED)
        self.assertNotIn("acquisition_source", attributed.data)
        self.assertNotIn("acquisition_reference", attributed.data)
        appointment = Appointment.objects.get(public_reference=attributed.data["public_reference"])
        card = QuickCard.objects.get(slug=slug)
        self.assertEqual(appointment.acquisition_source, "QUICKCARD")
        self.assertEqual(appointment.acquisition_reference, card.id)

        ctx2 = self._seed_bookable_monday(owner_email="attr2@example.com", org_name="Attr 2")
        direct = self._book(ctx2, "9811100102")
        plain = Appointment.objects.get(public_reference=direct.data["public_reference"])
        self.assertIsNone(plain.acquisition_source)
        self.assertIsNone(plain.acquisition_reference)

    def test_bad_refs_book_without_attribution(self):
        ctx = self._seed_bookable_monday(owner_email="attr3@example.com", org_name="Attr 3")
        self._card(ctx, slug="live-card")
        malformed = self._book(
            ctx, "9811100103", attribution_source="quickcard", attribution_ref="no-such-card"
        )
        self.assertEqual(malformed.status_code, status.HTTP_201_CREATED)
        row = Appointment.objects.get(public_reference=malformed.data["public_reference"])
        self.assertIsNone(row.acquisition_source)

        claimed = self._book(
            ctx, "9811100104", "12:00", attribution_source="QUICKCARD", attribution_ref=""
        )
        self.assertIsNone(
            Appointment.objects.get(
                public_reference=claimed.data["public_reference"]
            ).acquisition_source
        )

    def test_unpublished_deleted_and_foreign_cards_are_not_applied(self):
        ctx = self._seed_bookable_monday(
            owner_email="attr4@example.com", org_name="Attr 4", phone="+919800000401"
        )
        slug = self._card(ctx, slug="home-card")
        self.client.post(
            reverse(
                "quickcard-unpublish",
                kwargs={"business_id": ctx["business"]["id"], "location_id": ctx["location"]["id"]},
            )
        )
        hidden = self._book(
            ctx, "9811100105", "10:00", attribution_source="quickcard", attribution_ref=slug
        )
        self.assertIsNone(
            Appointment.objects.get(
                public_reference=hidden.data["public_reference"]
            ).acquisition_source
        )
        self.client.post(
            reverse(
                "quickcard-publish",
                kwargs={"business_id": ctx["business"]["id"], "location_id": ctx["location"]["id"]},
            )
        )
        other_location = self._create_location(ctx["business"]["id"], name="Uptown")
        other_local = self.client.post(
            reverse(
                "quickcard-detail",
                kwargs={
                    "business_id": ctx["business"]["id"],
                    "location_id": other_location["id"],
                },
            ),
            {"slug": "uptown-card"},
            format="json",
        )
        self.assertEqual(other_local.status_code, status.HTTP_201_CREATED)
        self.client.post(
            reverse(
                "quickcard-publish",
                kwargs={"business_id": ctx["business"]["id"], "location_id": other_location["id"]},
            )
        )
        mismatched = self._book(
            ctx,
            "9811100106",
            "12:00",
            attribution_source="quickcard",
            attribution_ref="uptown-card",
        )
        self.assertIsNone(
            Appointment.objects.get(
                public_reference=mismatched.data["public_reference"]
            ).acquisition_source
        )
        other = self._seed_bookable_monday(
            owner_email="attr5@example.com", org_name="Attr 5", phone="+919800000402"
        )
        other_slug = self._card(other, slug="other-card")
        crossed = self._book(
            ctx, "9811100107", "14:00", attribution_source="quickcard", attribution_ref=other_slug
        )
        self.assertIsNone(
            Appointment.objects.get(
                public_reference=crossed.data["public_reference"]
            ).acquisition_source
        )
        self._auth(ctx["token"])
        self._create_availability(
            ctx["business"]["id"],
            ctx["staff"]["id"],
            ctx["location"]["id"],
            weekday=Weekday.TUESDAY,
            starts_at="09:00:00",
            ends_at="17:00:00",
        )
        tuesday = ctx["monday"] + timedelta(days=1)
        kept_payload = self._book_payload(
            ctx, "10:00", staff_id=ctx["staff"]["id"], phone="9811100108"
        )
        kept_payload["start"] = datetime.combine(tuesday, time(10, 0), tzinfo=KOLKATA).isoformat()
        kept_payload["attribution_source"] = "quickcard"
        kept_payload["attribution_ref"] = slug
        kept = self._public_create(kept_payload)
        self.assertEqual(kept.status_code, status.HTTP_201_CREATED)
        stored = Appointment.objects.get(public_reference=kept.data["public_reference"])
        self.assertEqual(stored.acquisition_reference, QuickCard.objects.get(slug=slug).id)
        QuickCard.objects.get(slug=slug).delete()
        stored.refresh_from_db()
        self.assertEqual(stored.acquisition_source, "QUICKCARD")
        payload = self._book_payload(ctx, "12:00", staff_id=ctx["staff"]["id"], phone="9811100109")
        payload["start"] = datetime.combine(tuesday, time(12, 0), tzinfo=KOLKATA).isoformat()
        payload["attribution_source"] = "quickcard"
        payload["attribution_ref"] = slug
        after = self._public_create(payload)
        self.assertEqual(after.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(
            Appointment.objects.get(
                public_reference=after.data["public_reference"]
            ).acquisition_source
        )

        summary = self.client.get(
            reverse("quickcard-analytics", kwargs={"business_id": ctx["business"]["id"]})
        )
        self.assertEqual(summary.status_code, status.HTTP_200_OK)
        self.assertEqual(summary.data["bookings"], 1)
        self.assertIn("book", summary.data["cta_clicks"])
        old = Appointment.objects.get(pk=stored.pk)
        old.created_at = timezone.now() - timedelta(days=40)
        old.save(update_fields=["created_at"])
        recent = self.client.get(
            reverse("quickcard-analytics", kwargs={"business_id": ctx["business"]["id"]})
        )
        self.assertEqual(recent.data["bookings"], 0)
        wide = self.client.get(
            reverse("quickcard-analytics", kwargs={"business_id": ctx["business"]["id"]}),
            {"date_from": (timezone.now() - timedelta(days=50)).date().isoformat()},
        )
        self.assertEqual(wide.data["bookings"], 1)
