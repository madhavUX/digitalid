"""Public manage-token booking APIs, security, and notification isolation."""

from datetime import timedelta
from unittest.mock import MagicMock
from uuid import uuid4

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from booking.events import (
    AppointmentBooked,
    AppointmentCancelled,
    clear_handlers,
    emit,
    register_handler,
)
from booking.manage_tokens import hash_manage_token
from booking.models import Appointment, AppointmentManageToken, AppointmentStatus
from booking.notifications import (
    BookingNotificationService,
    handle_appointment_booked,
    handle_appointment_cancelled,
    set_notification_service,
)
from booking.services import cancel_appointment
from booking.tests.test_public_booking_api import PublicBookingAPITestCase


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
class PublicManageBookingAPITests(PublicBookingAPITestCase):
    def _create_with_token(self, ctx, hhmm="10:00", phone="9833300001"):
        created = self._public_create(
            self._book_payload(ctx, hhmm, staff_id=ctx["staff"]["id"], phone=phone)
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertIn("manage_token", created.data)
        return created

    def test_create_returns_manage_token_and_stores_hash_only(self):
        ctx = self._seed_bookable_monday(phone="+919800000080")
        created = self._create_with_token(ctx, phone="9833300001")
        raw = created.data["manage_token"]
        self.assertTrue(raw)
        appointment = Appointment.objects.get(public_reference=created.data["public_reference"])
        row = AppointmentManageToken.objects.get(appointment=appointment)
        self.assertEqual(row.token_hash, hash_manage_token(raw))
        self.assertNotEqual(row.token_hash, raw)
        self.assertFalse(AppointmentManageToken.objects.filter(token_hash=raw).exists())

    def test_valid_token_returns_safe_payload(self):
        ctx = self._seed_bookable_monday(phone="+919800000081")
        created = self._create_with_token(ctx, phone="9833300002")
        token = created.data["manage_token"]
        response = self.public.get(reverse("public-booking-manage", kwargs={"token": token}))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        appointment = Appointment.objects.get(public_reference=created.data["public_reference"])
        self.assertEqual(data["public_reference"], created.data["public_reference"])
        self.assertEqual(data["status"], AppointmentStatus.CONFIRMED)
        self.assertEqual(data["location"]["name"], "Downtown")
        self.assertEqual(data["location"]["slug"], ctx["location"]["slug"])
        self.assertEqual(data["service"]["name"], "Haircut")
        self.assertEqual(data["staff"]["name"], "Priya")
        self.assertEqual(data["customer"]["name"], "Rahul Sharma")
        self.assertTrue(data["can_cancel"])
        self.assertNotIn("id", data)
        self.assertNotIn("manage_token", data)
        self.assertNotIn("phone", data.get("customer", {}))
        self.assertNotIn("email", data.get("customer", {}))
        blob = str(data)
        self.assertNotIn(str(appointment.id), blob)
        self.assertNotIn(ctx["staff"]["id"], blob)

    def test_invalid_token_returns_404(self):
        response = self.public.get(
            reverse("public-booking-manage", kwargs={"token": "not-a-real-token"})
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["code"], "BOOKING_NOT_FOUND")

    def test_expired_token_rejected(self):
        ctx = self._seed_bookable_monday(phone="+919800000082")
        created = self._create_with_token(ctx, phone="9833300003")
        token = created.data["manage_token"]
        AppointmentManageToken.objects.filter(token_hash=hash_manage_token(token)).update(
            expires_at=timezone.now() - timedelta(hours=1)
        )
        response = self.public.get(reverse("public-booking-manage", kwargs={"token": token}))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_token_isolation_cannot_access_other_appointment(self):
        ctx = self._seed_bookable_monday(phone="+919800000083")
        first = self._create_with_token(ctx, "10:00", phone="9833300004")
        second = self._create_with_token(ctx, "12:00", phone="9833300005")
        response = self.public.get(
            reverse(
                "public-booking-manage",
                kwargs={"token": first.data["manage_token"]},
            )
        )
        self.assertEqual(
            response.data["public_reference"],
            first.data["public_reference"],
        )
        self.assertNotEqual(
            response.data["public_reference"],
            second.data["public_reference"],
        )

    def test_cancel_via_token_uses_lifecycle_and_releases_slot(self):
        ctx = self._seed_bookable_monday(phone="+919800000084")
        created = self._create_with_token(ctx, "10:00", phone="9833300006")
        token = created.data["manage_token"]
        cancel = self.public.post(
            reverse("public-booking-manage-cancel", kwargs={"token": token}),
            {"reason": "Changed plans"},
            format="json",
        )
        self.assertEqual(cancel.status_code, status.HTTP_200_OK)
        self.assertEqual(cancel.data["status"], AppointmentStatus.CANCELLED)
        self.assertEqual(cancel.data["message"], "Your booking has been cancelled.")
        appointment = Appointment.objects.get(public_reference=created.data["public_reference"])
        self.assertEqual(appointment.status, AppointmentStatus.CANCELLED)
        self.assertEqual(appointment.cancellation_reason, "Changed plans")
        self.assertIsNotNone(appointment.cancelled_at)

        availability = self._public_availability(
            ctx["location"]["id"],
            ctx["service"]["id"],
            ctx["monday"],
            ctx["staff"]["id"],
        )
        starts = [s["start"] for s in availability.data["slots"]]
        self.assertTrue(any(s.startswith(f"{ctx['monday'].isoformat()}T10:00:00") for s in starts))

    def test_repeated_cancel_is_safe(self):
        ctx = self._seed_bookable_monday(phone="+919800000085")
        created = self._create_with_token(ctx, "10:00", phone="9833300007")
        token = created.data["manage_token"]
        url = reverse("public-booking-manage-cancel", kwargs={"token": token})
        first = self.public.post(url, {}, format="json")
        second = self.public.post(url, {}, format="json")
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.data["status"], AppointmentStatus.CANCELLED)
        self.assertIn("already been cancelled", second.data["message"].lower())
        self.assertEqual(
            Appointment.objects.filter(
                public_reference=created.data["public_reference"],
                status=AppointmentStatus.CANCELLED,
            ).count(),
            1,
        )

    def test_completed_cannot_cancel(self):
        ctx = self._seed_bookable_monday(phone="+919800000086")
        created = self._create_with_token(ctx, "10:00", phone="9833300008")
        appointment = Appointment.objects.get(public_reference=created.data["public_reference"])
        Appointment.objects.filter(pk=appointment.pk).update(status=AppointmentStatus.COMPLETED)
        response = self.public.post(
            reverse(
                "public-booking-manage-cancel",
                kwargs={"token": created.data["manage_token"]},
            ),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "CANCELLATION_NOT_ALLOWED")
        detail = self.public.get(
            reverse(
                "public-booking-manage",
                kwargs={"token": created.data["manage_token"]},
            )
        )
        self.assertFalse(detail.data["can_cancel"])

    def test_no_show_cannot_cancel(self):
        ctx = self._seed_bookable_monday(phone="+919800000087")
        created = self._create_with_token(ctx, "10:00", phone="9833300009")
        Appointment.objects.filter(public_reference=created.data["public_reference"]).update(
            status=AppointmentStatus.NO_SHOW
        )
        response = self.public.post(
            reverse(
                "public-booking-manage-cancel",
                kwargs={"token": created.data["manage_token"]},
            ),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "CANCELLATION_NOT_ALLOWED")

    def test_invalid_token_cannot_cancel(self):
        response = self.public.post(
            reverse("public-booking-manage-cancel", kwargs={"token": "bogus"}),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class BookingEventsNotificationTests(PublicBookingAPITestCase):
    def tearDown(self):
        clear_handlers()
        register_handler(AppointmentBooked, handle_appointment_booked)
        register_handler(AppointmentCancelled, handle_appointment_cancelled)
        set_notification_service(BookingNotificationService())
        super().tearDown()

    def test_booking_emits_confirmation_event(self):
        seen = []

        def handler(event):
            seen.append(event)

        clear_handlers()
        register_handler(AppointmentBooked, handler)
        ctx = self._seed_bookable_monday(phone="+919800000088")
        with self.captureOnCommitCallbacks(execute=True):
            created = self._public_create(
                self._book_payload(ctx, "10:00", staff_id=ctx["staff"]["id"], phone="9833300010")
            )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        appointment = Appointment.objects.get(public_reference=created.data["public_reference"])
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].appointment_id, appointment.id)

    def test_cancellation_emits_event(self):
        seen = []

        def handler(event):
            seen.append(event)

        clear_handlers()
        register_handler(AppointmentCancelled, handler)
        ctx = self._seed_bookable_monday(phone="+919800000089")
        created = self._public_create(
            self._book_payload(ctx, "10:00", staff_id=ctx["staff"]["id"], phone="9833300011")
        )
        appointment = Appointment.objects.get(public_reference=created.data["public_reference"])
        with self.captureOnCommitCallbacks(execute=True):
            cancel_appointment(appointment=appointment, actor=None, reason="test")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].appointment_id, appointment.id)

    def test_notification_failure_does_not_break_booking(self):
        failing = MagicMock()
        failing.send_booking_confirmation.side_effect = RuntimeError("provider down")
        set_notification_service(failing)

        clear_handlers()
        register_handler(AppointmentBooked, handle_appointment_booked)

        ctx = self._seed_bookable_monday(phone="+919800000090")
        with self.captureOnCommitCallbacks(execute=True):
            created = self._public_create(
                self._book_payload(ctx, "10:00", staff_id=ctx["staff"]["id"], phone="9833300012")
            )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            Appointment.objects.filter(public_reference=created.data["public_reference"]).exists()
        )
        failing.send_booking_confirmation.assert_called()

    def test_notification_failure_does_not_break_cancellation(self):
        failing = MagicMock()
        failing.send_booking_cancellation.side_effect = RuntimeError("provider down")
        set_notification_service(failing)

        clear_handlers()
        register_handler(AppointmentCancelled, handle_appointment_cancelled)

        ctx = self._seed_bookable_monday(phone="+919800000091")
        created = self._public_create(
            self._book_payload(ctx, "10:00", staff_id=ctx["staff"]["id"], phone="9833300013")
        )
        token = created.data["manage_token"]
        with self.captureOnCommitCallbacks(execute=True):
            response = self.public.post(
                reverse("public-booking-manage-cancel", kwargs={"token": token}),
                {},
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], AppointmentStatus.CANCELLED)
        failing.send_booking_cancellation.assert_called()

    def test_emit_swallows_handler_errors(self):
        def boom(_event):
            raise RuntimeError("boom")

        clear_handlers()
        register_handler(AppointmentBooked, boom)
        emit(AppointmentBooked(appointment_id=uuid4()))
