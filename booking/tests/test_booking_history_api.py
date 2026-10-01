"""Guest booking history + Book Again public API tests."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from booking.models import Appointment, AppointmentStatus, NotificationDelivery, NotificationType
from booking.tests.test_public_booking_api import PublicBookingAPITestCase
from catalog.models import Service
from staff.models import StaffProfile


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
    },
    MAX_PUBLIC_BOOKING_HISTORY_PAGE_SIZE=50,
    WHATSAPP_ENABLED=True,
    WHATSAPP_PROVIDER="mock",
)
class GuestBookingHistoryAPITests(PublicBookingAPITestCase):
    def _book(self, ctx, *, hhmm="10:00", phone="9844500001"):
        with self.captureOnCommitCallbacks(execute=True):
            created = self._public_create(
                self._book_payload(ctx, hhmm, staff_id=ctx["staff"]["id"], phone=phone)
            )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        return created

    def _history(self, token, **params):
        return self.public.get(
            reverse("public-booking-history", kwargs={"token": token}),
            params,
        )

    def _book_again(self, token, public_reference):
        return self.public.get(
            reverse(
                "public-booking-book-again",
                kwargs={"token": token, "public_reference": public_reference},
            )
        )

    def test_valid_token_lists_upcoming(self):
        ctx = self._seed_bookable_monday(phone="+919811110001")
        created = self._book(ctx, phone="9844500001")
        token = created.data["manage_token"]
        response = self._history(token, category="upcoming")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["category"], "upcoming")
        self.assertEqual(response.data["count"], 1)
        row = response.data["results"][0]
        self.assertEqual(row["public_reference"], created.data["public_reference"])
        self.assertEqual(row["status"], AppointmentStatus.CONFIRMED)
        self.assertTrue(row["can_book_again"])
        self.assertNotIn("id", row)
        self.assertNotIn("phone", str(response.data))
        self.assertNotIn("email", str(response.data).lower())
        self.assertNotIn(str(Appointment.objects.get().id), str(response.data))

    def test_invalid_token_404(self):
        response = self._history("not-a-real-token")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data.get("code"), "BOOKING_NOT_FOUND")

    def test_token_isolation_across_customers(self):
        ctx_a = self._seed_bookable_monday(
            owner_email="hist-a@example.com",
            org_name="Hist Org A",
            phone="+919811110010",
        )
        created_a = self._book(ctx_a, phone="9844500010")
        token_a = created_a.data["manage_token"]

        ctx_b = self._seed_bookable_monday(
            owner_email="hist-b@example.com",
            org_name="Hist Org B",
            phone="+919811110011",
        )
        created_b = self._book(ctx_b, phone="9844500011")

        response = self._history(token_a, category="upcoming")
        refs = {r["public_reference"] for r in response.data["results"]}
        self.assertIn(created_a.data["public_reference"], refs)
        self.assertNotIn(created_b.data["public_reference"], refs)

    def test_cannot_enumerate_by_phone_or_reference(self):
        ctx = self._seed_bookable_monday(phone="+919811110020")
        created = self._book(ctx, phone="9844500020")
        # No phone lookup endpoint — history requires token path.
        bad = self.public.get("/api/v1/public/booking/history/", {"phone": "+919844500020"})
        self.assertIn(bad.status_code, (404, 405))
        # public_reference alone cannot open history
        alone = self.public.get(
            reverse(
                "public-booking-book-again",
                kwargs={
                    "token": "wrong",
                    "public_reference": created.data["public_reference"],
                },
            )
        )
        self.assertEqual(alone.status_code, status.HTTP_404_NOT_FOUND)

    def test_past_cancelled_ordering_and_categories(self):
        ctx = self._seed_bookable_monday(phone="+919811110030")
        created = self._book(ctx, hhmm="10:00", phone="9844500030")
        token = created.data["manage_token"]
        appointment = Appointment.objects.get(public_reference=created.data["public_reference"])
        customer = appointment.customer

        # Second booking same customer (later slot — avoid buffer overlap with 10:00)
        created2 = self._book(ctx, hhmm="12:00", phone="9844500030")
        appt2 = Appointment.objects.get(public_reference=created2.data["public_reference"])

        # Make first completed (past), second cancelled
        now = timezone.now()
        Appointment.objects.filter(pk=appointment.pk).update(
            status=AppointmentStatus.COMPLETED,
            starts_at=now - timedelta(days=2),
            ends_at=now - timedelta(days=2) + timedelta(hours=1),
            occupancy_starts_at=now - timedelta(days=2),
            occupancy_ends_at=now - timedelta(days=2) + timedelta(hours=1),
        )
        Appointment.objects.filter(pk=appt2.pk).update(
            status=AppointmentStatus.CANCELLED,
            starts_at=now - timedelta(days=1),
            ends_at=now - timedelta(days=1) + timedelta(hours=1),
            occupancy_starts_at=now - timedelta(days=1),
            occupancy_ends_at=now - timedelta(days=1) + timedelta(hours=1),
            cancelled_at=now,
        )

        # Third upcoming
        created3 = self._book(ctx, hhmm="14:00", phone="9844500030")

        past = self._history(token, category="past")
        self.assertEqual(past.data["count"], 1)
        self.assertEqual(past.data["results"][0]["public_reference"], appointment.public_reference)

        cancelled = self._history(token, category="cancelled")
        self.assertEqual(cancelled.data["count"], 1)
        self.assertEqual(cancelled.data["results"][0]["public_reference"], appt2.public_reference)

        upcoming = self._history(token, category="upcoming")
        self.assertEqual(upcoming.data["count"], 1)
        self.assertEqual(
            upcoming.data["results"][0]["public_reference"],
            created3.data["public_reference"],
        )
        self.assertEqual(customer.appointments.count(), 3)

    def test_pagination_and_max_page_size(self):
        ctx = self._seed_bookable_monday(phone="+919811110040")
        created = self._book(ctx, hhmm="10:00", phone="9844500040")
        token = created.data["manage_token"]
        appointment = Appointment.objects.get(public_reference=created.data["public_reference"])
        base = timezone.now() - timedelta(days=30)
        Appointment.objects.filter(pk=appointment.pk).update(
            status=AppointmentStatus.COMPLETED,
            starts_at=base,
            ends_at=base + timedelta(hours=1),
            occupancy_starts_at=base,
            occupancy_ends_at=base + timedelta(hours=1),
        )
        for hhmm in ("11:00", "12:00", "13:00", "14:00", "15:00"):
            c = self._book(ctx, hhmm=hhmm, phone="9844500040")
            a = Appointment.objects.get(public_reference=c.data["public_reference"])
            starts = base + timedelta(hours=int(hhmm.split(":")[0]))
            Appointment.objects.filter(pk=a.pk).update(
                status=AppointmentStatus.COMPLETED,
                starts_at=starts,
                ends_at=starts + timedelta(hours=1),
                occupancy_starts_at=starts,
                occupancy_ends_at=starts + timedelta(hours=1),
            )

        page = self._history(token, category="past", limit=2, offset=0)
        self.assertEqual(page.data["limit"], 2)
        self.assertEqual(len(page.data["results"]), 2)
        self.assertGreaterEqual(page.data["count"], 6)

        capped = self._history(token, category="past", limit=1000, offset=0)
        self.assertEqual(capped.data["limit"], 50)

    def test_empty_history(self):
        ctx = self._seed_bookable_monday(phone="+919811110050")
        created = self._book(ctx, phone="9844500050")
        token = created.data["manage_token"]
        past = self._history(token, category="past")
        self.assertEqual(past.data["count"], 0)
        self.assertEqual(past.data["results"], [])

    def test_book_again_prefill_and_new_appointment(self):
        ctx = self._seed_bookable_monday(phone="+919811110060")
        created = self._book(ctx, hhmm="10:00", phone="9844500060")
        token = created.data["manage_token"]
        ref = created.data["public_reference"]
        appointment = Appointment.objects.get(public_reference=ref)
        Appointment.objects.filter(pk=appointment.pk).update(status=AppointmentStatus.COMPLETED)

        prefill = self._book_again(token, ref)
        self.assertEqual(prefill.status_code, status.HTTP_200_OK)
        self.assertTrue(prefill.data["available"])
        self.assertEqual(prefill.data["prefill"]["service_id"], ctx["service"]["id"])
        self.assertEqual(prefill.data["prefill"]["staff_id"], ctx["staff"]["id"])
        self.assertEqual(prefill.data["location"]["slug"], ctx["location"]["slug"])

        # Create new appointment via existing public create (fresh slot)
        with self.captureOnCommitCallbacks(execute=True):
            again = self._public_create(
                self._book_payload(ctx, "11:00", staff_id=ctx["staff"]["id"], phone="9844500060")
            )
        self.assertEqual(again.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(again.data["public_reference"], ref)
        self.assertNotEqual(again.data["manage_token"], token)
        self.assertTrue(
            NotificationDelivery.objects.filter(
                appointment__public_reference=again.data["public_reference"],
                notification_type=NotificationType.BOOKING_CONFIRMATION,
            ).exists()
        )

    def test_book_again_uses_current_price(self):
        ctx = self._seed_bookable_monday(phone="+919811110070")
        created = self._book(ctx, phone="9844500070")
        token = created.data["manage_token"]
        ref = created.data["public_reference"]
        appointment = Appointment.objects.get(public_reference=ref)
        old_total = appointment.total_price
        Service.objects.filter(pk=ctx["service"]["id"]).update(price=Decimal("450.00"))
        Appointment.objects.filter(pk=appointment.pk).update(status=AppointmentStatus.COMPLETED)

        prefill = self._book_again(token, ref)
        self.assertTrue(prefill.data["available"])

        with self.captureOnCommitCallbacks(execute=True):
            again = self._public_create(
                self._book_payload(ctx, "11:00", staff_id=ctx["staff"]["id"], phone="9844500070")
            )
        self.assertEqual(again.status_code, status.HTTP_201_CREATED)
        self.assertEqual(again.data["total"], "450.00")
        self.assertNotEqual(Decimal(again.data["total"]), old_total)

    def test_book_again_service_unavailable(self):
        ctx = self._seed_bookable_monday(phone="+919811110080")
        created = self._book(ctx, phone="9844500080")
        token = created.data["manage_token"]
        ref = created.data["public_reference"]
        Service.objects.filter(pk=ctx["service"]["id"]).update(is_bookable_online=False)
        response = self._book_again(token, ref)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["available"])
        self.assertEqual(response.data["reason"], "SERVICE_UNAVAILABLE")

    def test_book_again_staff_fallback_to_any(self):
        ctx = self._seed_bookable_monday(phone="+919811110090")
        created = self._book(ctx, phone="9844500090")
        token = created.data["manage_token"]
        ref = created.data["public_reference"]
        StaffProfile.objects.filter(pk=ctx["staff"]["id"]).update(is_bookable=False)
        response = self._book_again(token, ref)
        self.assertTrue(response.data["available"])
        self.assertFalse(response.data["staff"]["available"])
        self.assertIsNone(response.data["prefill"]["staff_id"])

    def test_book_again_authorization_other_customer_reference(self):
        ctx_a = self._seed_bookable_monday(
            owner_email="ba-a@example.com",
            org_name="BA Org A",
            phone="+919811110100",
        )
        created_a = self._book(ctx_a, phone="9844500100")
        token_a = created_a.data["manage_token"]

        ctx_b = self._seed_bookable_monday(
            owner_email="ba-b@example.com",
            org_name="BA Org B",
            phone="+919811110101",
        )
        created_b = self._book(ctx_b, phone="9844500101")
        response = self._book_again(token_a, created_b.data["public_reference"])
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_soft_deleted_excluded(self):
        ctx = self._seed_bookable_monday(phone="+919811110110")
        created = self._book(ctx, phone="9844500110")
        token = created.data["manage_token"]
        appointment = Appointment.objects.get(public_reference=created.data["public_reference"])
        Appointment.objects.filter(pk=appointment.pk).update(deleted_at=timezone.now())
        # Token resolves deleted appointment as invalid
        response = self._history(token)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
