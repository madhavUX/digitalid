"""WhatsApp notification infrastructure tests."""

from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from booking.events import (
    AppointmentBooked,
    AppointmentCancelled,
    clear_handlers,
    register_handler,
)
from booking.manage_tokens import hash_manage_token
from booking.models import (
    Appointment,
    AppointmentManageToken,
    AppointmentStatus,
    NotificationChannel,
    NotificationDelivery,
    NotificationStatus,
    NotificationType,
)
from booking.notifications import (
    BookingNotificationService,
    handle_appointment_booked,
    handle_appointment_cancelled,
    retry_notification,
    sanitize_url_for_log,
    set_notification_service,
)
from booking.services import cancel_appointment
from booking.tests.test_public_booking_api import PublicBookingAPITestCase
from booking.whatsapp import LoggingWhatsAppProvider, WhatsAppProviderError, mask_phone


@override_settings(
    WHATSAPP_ENABLED=True,
    WHATSAPP_PROVIDER="mock",
    PUBLIC_APP_URL="https://book.example.com",
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
)
class WhatsAppNotificationInfrastructureTests(PublicBookingAPITestCase):
    def setUp(self):
        super().setUp()
        from django.core.cache import cache

        cache.clear()
        clear_handlers()
        register_handler(AppointmentBooked, handle_appointment_booked)
        register_handler(AppointmentCancelled, handle_appointment_cancelled)
        set_notification_service(BookingNotificationService())

    def tearDown(self):
        clear_handlers()
        register_handler(AppointmentBooked, handle_appointment_booked)
        register_handler(AppointmentCancelled, handle_appointment_cancelled)
        set_notification_service(BookingNotificationService())
        super().tearDown()

    def _book(self, phone_suffix="01"):
        ctx = self._seed_bookable_monday(phone=f"+9198000001{phone_suffix}")
        with self.captureOnCommitCallbacks(execute=True):
            created = self._public_create(
                self._book_payload(
                    ctx,
                    "10:00",
                    staff_id=ctx["staff"]["id"],
                    phone=f"98444000{phone_suffix}",
                )
            )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        appointment = Appointment.objects.get(public_reference=created.data["public_reference"])
        return ctx, created, appointment

    def test_booking_creates_sent_whatsapp_confirmation(self):
        _ctx, created, appointment = self._book("11")
        delivery = NotificationDelivery.objects.get(
            appointment=appointment,
            channel=NotificationChannel.WHATSAPP,
            notification_type=NotificationType.BOOKING_CONFIRMATION,
        )
        self.assertEqual(delivery.status, NotificationStatus.SENT)
        self.assertEqual(delivery.attempt_count, 1)
        self.assertTrue(delivery.provider_message_id.startswith("mock-wa-"))
        self.assertEqual(delivery.provider_message_id, f"mock-wa-{delivery.id}")
        self.assertIsNotNone(delivery.sent_at)
        self.assertEqual(appointment.status, AppointmentStatus.CONFIRMED)
        self.assertEqual(delivery.recipient, appointment.customer.phone)

    def test_confirmation_snapshot_contains_manage_url_not_raw_token_field(self):
        _ctx, created, appointment = self._book("12")
        raw = created.data["manage_token"]
        delivery = NotificationDelivery.objects.get(appointment=appointment)
        snap = delivery.payload_snapshot
        self.assertEqual(snap["payload_version"], 1)
        self.assertEqual(snap["message_type"], NotificationType.BOOKING_CONFIRMATION)
        self.assertIn(raw, snap["manage_url"])
        self.assertIn("/book/manage/", snap["manage_url"])
        self.assertNotIn("raw_token", snap)
        self.assertNotIn("manage_token", snap)
        self.assertNotIn(raw, delivery.recipient)
        self.assertNotIn(raw, delivery.last_error)
        self.assertNotIn(raw, delivery.provider_message_id)
        token_row = AppointmentManageToken.objects.get(appointment=appointment)
        self.assertEqual(token_row.token_hash, hash_manage_token(raw))
        self.assertNotEqual(token_row.token_hash, raw)
        for field in token_row._meta.fields:
            value = getattr(token_row, field.name)
            if isinstance(value, str):
                self.assertNotIn(raw, value)

    def test_provider_receives_secure_manage_url(self):
        captured = {}

        class CapturingProvider(LoggingWhatsAppProvider):
            def send(self, *, to, notification_type, snapshot, notification_id):
                captured["to"] = to
                captured["body"] = (snapshot or {}).get("text") or ""
                return super().send(
                    to=to,
                    notification_type=notification_type,
                    snapshot=snapshot,
                    notification_id=notification_id,
                )

        with patch(
            "booking.notifications.get_whatsapp_provider",
            return_value=CapturingProvider(),
        ):
            _ctx, created, appointment = self._book("13")
        self.assertIn(created.data["manage_token"], captured["body"])
        self.assertIn(appointment.public_reference, captured["body"])
        self.assertIn("confirmed", captured["body"].lower())

    def test_provider_failure_does_not_break_booking(self):
        class FailingProvider:
            def send(self, *, to, notification_type, snapshot, notification_id):
                raise WhatsAppProviderError("timeout")

        with patch(
            "booking.notifications.get_whatsapp_provider",
            return_value=FailingProvider(),
        ):
            _ctx, created, appointment = self._book("14")
        self.assertEqual(appointment.status, AppointmentStatus.CONFIRMED)
        delivery = NotificationDelivery.objects.get(appointment=appointment)
        self.assertEqual(delivery.status, NotificationStatus.FAILED)
        self.assertIn("timeout", delivery.last_error)
        self.assertEqual(delivery.attempt_count, 1)
        self.assertTrue(delivery.payload_snapshot.get("manage_url"))
        self.assertIn(created.data["manage_token"], delivery.payload_snapshot["manage_url"])

    def test_duplicate_event_does_not_duplicate_successful_confirmation(self):
        _ctx, _created, appointment = self._book("15")
        self.assertEqual(
            NotificationDelivery.objects.filter(
                appointment=appointment,
                notification_type=NotificationType.BOOKING_CONFIRMATION,
            ).count(),
            1,
        )
        BookingNotificationService().send_booking_confirmation(appointment)
        self.assertEqual(
            NotificationDelivery.objects.filter(
                appointment=appointment,
                notification_type=NotificationType.BOOKING_CONFIRMATION,
            ).count(),
            1,
        )
        delivery = NotificationDelivery.objects.get(appointment=appointment)
        self.assertEqual(delivery.status, NotificationStatus.SENT)
        self.assertEqual(delivery.attempt_count, 1)

    def test_failed_delivery_retry_preserves_manage_url_without_token_rotation(self):
        captured_bodies: list[str] = []

        class Flaky:
            def __init__(self):
                self.calls = 0

            def send(self, *, to, notification_type, snapshot, notification_id):
                self.calls += 1
                body = (snapshot or {}).get("text") or ""
                captured_bodies.append(body)
                if self.calls == 1:
                    raise WhatsAppProviderError("provider 500")
                return LoggingWhatsAppProvider().send(
                    to=to,
                    notification_type=notification_type,
                    snapshot=snapshot,
                    notification_id=notification_id,
                )

        flaky = Flaky()
        with patch("booking.notifications.get_whatsapp_provider", return_value=flaky):
            _ctx, created, appointment = self._book("16")
            delivery = NotificationDelivery.objects.get(appointment=appointment)
            self.assertEqual(delivery.status, NotificationStatus.FAILED)
            manage_url = delivery.payload_snapshot["manage_url"]
            token_hash_before = AppointmentManageToken.objects.get(
                appointment=appointment
            ).token_hash
            with patch(
                "booking.notifications.issue_manage_token",
                side_effect=AssertionError("retry must not issue a new manage token"),
            ):
                retried = retry_notification(delivery.id)
        self.assertEqual(retried.status, NotificationStatus.SENT)
        self.assertEqual(retried.attempt_count, 2)
        self.assertTrue(retried.provider_message_id)
        self.assertEqual(retried.payload_snapshot["manage_url"], manage_url)
        self.assertIn(created.data["manage_token"], captured_bodies[0])
        self.assertIn(created.data["manage_token"], captured_bodies[1])
        self.assertEqual(captured_bodies[0], captured_bodies[1])
        self.assertEqual(
            AppointmentManageToken.objects.get(appointment=appointment).token_hash,
            token_hash_before,
        )
        self.assertEqual(
            NotificationDelivery.objects.filter(appointment=appointment).count(),
            1,
        )

    def test_cancellation_creates_whatsapp_notification(self):
        _ctx, created, appointment = self._book("17")
        with self.captureOnCommitCallbacks(execute=True):
            cancel = self.public.post(
                reverse(
                    "public-booking-manage-cancel",
                    kwargs={"token": created.data["manage_token"]},
                ),
                {},
                format="json",
            )
        self.assertEqual(cancel.status_code, status.HTTP_200_OK)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, AppointmentStatus.CANCELLED)
        delivery = NotificationDelivery.objects.get(
            appointment=appointment,
            notification_type=NotificationType.BOOKING_CANCELLATION,
        )
        self.assertEqual(delivery.status, NotificationStatus.SENT)
        self.assertEqual(delivery.channel, NotificationChannel.WHATSAPP)

    def test_cancellation_provider_failure_keeps_appointment_cancelled(self):
        _ctx, created, appointment = self._book("18")

        class FailingProvider:
            def send(self, *, to, notification_type, snapshot, notification_id):
                raise WhatsAppProviderError("connection failure")

        with patch(
            "booking.notifications.get_whatsapp_provider",
            return_value=FailingProvider(),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                cancel_appointment(appointment=appointment, actor=None, reason="x")
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, AppointmentStatus.CANCELLED)
        delivery = NotificationDelivery.objects.get(
            appointment=appointment,
            notification_type=NotificationType.BOOKING_CANCELLATION,
        )
        self.assertEqual(delivery.status, NotificationStatus.FAILED)

    def test_duplicate_cancellation_event_is_idempotent(self):
        _ctx, created, appointment = self._book("19")
        with self.captureOnCommitCallbacks(execute=True):
            cancel_appointment(appointment=appointment, actor=None, reason="once")
        BookingNotificationService().send_booking_cancellation(appointment)
        self.assertEqual(
            NotificationDelivery.objects.filter(
                appointment=appointment,
                notification_type=NotificationType.BOOKING_CANCELLATION,
            ).count(),
            1,
        )

    def test_public_api_does_not_expose_notification_internals(self):
        _ctx, created, _appointment = self._book("20")
        self.assertNotIn("provider_message_id", created.data)
        self.assertNotIn("notification_status", created.data)
        detail = self.public.get(
            reverse(
                "public-booking-appointment-detail",
                kwargs={"public_reference": created.data["public_reference"]},
            )
        )
        self.assertNotIn("provider_message_id", detail.data)
        manage = self.public.get(
            reverse(
                "public-booking-manage",
                kwargs={"token": created.data["manage_token"]},
            )
        )
        self.assertNotIn("provider_message_id", manage.data)
        self.assertNotIn("notification", str(manage.data).lower())

    def test_sanitize_and_mask_helpers(self):
        url = "https://book.example.com/book/manage/super-secret-token"
        self.assertIn("<redacted>", sanitize_url_for_log(url))
        self.assertNotIn("super-secret-token", sanitize_url_for_log(url))
        self.assertEqual(mask_phone("+919876543210"), "+91******3210")

    def test_raw_token_not_logged_on_dispatch(self):
        with self.assertLogs("booking.notifications", level="INFO") as captured:
            _ctx, created, _appointment = self._book("21")
        raw = created.data["manage_token"]
        joined = "\n".join(captured.output)
        self.assertNotIn(raw, joined)

    def test_whatsapp_disabled_skips_delivery(self):
        with override_settings(WHATSAPP_ENABLED=False):
            ctx = self._seed_bookable_monday(phone="+919800000122")
            with self.captureOnCommitCallbacks(execute=True):
                created = self._public_create(
                    self._book_payload(
                        ctx, "10:00", staff_id=ctx["staff"]["id"], phone="9844400022"
                    )
                )
        appointment = Appointment.objects.get(public_reference=created.data["public_reference"])
        self.assertEqual(appointment.status, AppointmentStatus.CONFIRMED)
        self.assertFalse(NotificationDelivery.objects.filter(appointment=appointment).exists())
