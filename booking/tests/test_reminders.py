"""Automated WhatsApp 24h / 1h appointment reminder tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from booking.models import (
    Appointment,
    AppointmentStatus,
    NotificationChannel,
    NotificationDelivery,
    NotificationStatus,
    NotificationType,
)
from booking.notifications import (
    BookingNotificationService,
    retry_notification,
    set_notification_service,
)
from booking.reminders import (
    is_reminder_in_send_window,
    process_due_reminders,
    reminder_due_at,
)
from booking.tests.test_public_booking_api import PublicBookingAPITestCase
from booking.whatsapp import LoggingWhatsAppProvider, WhatsAppProviderError


@override_settings(
    WHATSAPP_ENABLED=True,
    WHATSAPP_PROVIDER="mock",
    WHATSAPP_REMINDERS_ENABLED=True,
    WHATSAPP_REMINDER_24H_ENABLED=True,
    WHATSAPP_REMINDER_1H_ENABLED=True,
    WHATSAPP_REMINDER_24H_OFFSET_MINUTES=1440,
    WHATSAPP_REMINDER_1H_OFFSET_MINUTES=60,
    WHATSAPP_REMINDER_MAX_LATE_MINUTES=30,
    PUBLIC_APP_URL="https://book.example.com",
)
class ReminderWindowUnitTests(PublicBookingAPITestCase):
    def test_send_window_exact_due_and_lateness(self):
        starts = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)
        created = starts - timedelta(days=3)
        due = reminder_due_at(starts_at=starts, offset_minutes=1440)
        self.assertTrue(
            is_reminder_in_send_window(
                starts_at=starts,
                created_at=created,
                offset_minutes=1440,
                now=due,
                late_minutes=30,
            )
        )
        self.assertTrue(
            is_reminder_in_send_window(
                starts_at=starts,
                created_at=created,
                offset_minutes=1440,
                now=due + timedelta(minutes=20),
                late_minutes=30,
            )
        )
        self.assertFalse(
            is_reminder_in_send_window(
                starts_at=starts,
                created_at=created,
                offset_minutes=1440,
                now=due + timedelta(minutes=45),
                late_minutes=30,
            )
        )
        self.assertFalse(
            is_reminder_in_send_window(
                starts_at=starts,
                created_at=created,
                offset_minutes=1440,
                now=due - timedelta(hours=1),
                late_minutes=30,
            )
        )
        self.assertFalse(
            is_reminder_in_send_window(
                starts_at=starts,
                created_at=created,
                offset_minutes=1440,
                now=starts + timedelta(minutes=5),
                late_minutes=30,
            )
        )

    def test_booking_inside_offset_skips_reminder(self):
        starts = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)
        created = starts - timedelta(minutes=30)
        due_1h = reminder_due_at(starts_at=starts, offset_minutes=60)
        self.assertFalse(
            is_reminder_in_send_window(
                starts_at=starts,
                created_at=created,
                offset_minutes=60,
                now=due_1h + timedelta(minutes=10),
                late_minutes=30,
            )
        )


@override_settings(
    WHATSAPP_ENABLED=True,
    WHATSAPP_PROVIDER="mock",
    WHATSAPP_REMINDERS_ENABLED=True,
    WHATSAPP_REMINDER_24H_ENABLED=True,
    WHATSAPP_REMINDER_1H_ENABLED=True,
    WHATSAPP_REMINDER_24H_OFFSET_MINUTES=1440,
    WHATSAPP_REMINDER_1H_OFFSET_MINUTES=60,
    WHATSAPP_REMINDER_MAX_LATE_MINUTES=30,
    PUBLIC_APP_URL="https://book.example.com",
)
class ReminderServiceTests(PublicBookingAPITestCase):
    def setUp(self):
        super().setUp()
        set_notification_service(BookingNotificationService())
        self._send_calls = []
        self._orig_send = LoggingWhatsAppProvider.send

        def tracking_send(provider, **kwargs):
            self._send_calls.append(kwargs)
            return self._orig_send(provider, **kwargs)

        self._send_patch = patch.object(
            LoggingWhatsAppProvider, "send", side_effect=tracking_send, autospec=True
        )
        self._send_patch.start()

    def tearDown(self):
        self._send_patch.stop()
        set_notification_service(BookingNotificationService())
        super().tearDown()

    def _book_and_shift(
        self,
        *,
        starts_at: datetime,
        created_at: datetime,
        phone_suffix: str = "01",
        status: str = AppointmentStatus.CONFIRMED,
        manage_url: str | None = "https://book.example.com/book/manage/test-token",
    ) -> Appointment:
        ctx = self._seed_bookable_monday(
            owner_email=f"owner-{phone_suffix}@example.com",
            org_name=f"Org {phone_suffix}",
            phone=f"+9198000001{phone_suffix}",
        )
        with override_settings(WHATSAPP_ENABLED=False):
            with self.captureOnCommitCallbacks(execute=True):
                created = self._public_create(
                    self._book_payload(
                        ctx,
                        "10:00",
                        staff_id=ctx["staff"]["id"],
                        phone=f"98444000{phone_suffix}",
                    )
                )
        self.assertEqual(created.status_code, 201)
        appointment = Appointment.objects.get(public_reference=created.data["public_reference"])
        duration = appointment.ends_at - appointment.starts_at
        occ_before = appointment.starts_at - appointment.occupancy_starts_at
        occ_after = appointment.occupancy_ends_at - appointment.ends_at
        ends_at = starts_at + duration
        Appointment.objects.filter(pk=appointment.pk).update(
            starts_at=starts_at,
            ends_at=ends_at,
            occupancy_starts_at=starts_at - occ_before,
            occupancy_ends_at=ends_at + occ_after,
            created_at=created_at,
            status=status,
        )
        appointment.refresh_from_db()
        if manage_url is not None:
            NotificationDelivery.objects.create(
                appointment=appointment,
                channel=NotificationChannel.WHATSAPP,
                notification_type=NotificationType.BOOKING_CONFIRMATION,
                recipient=appointment.customer.phone,
                status=NotificationStatus.SENT,
                attempt_count=1,
                payload_snapshot={
                    "payload_version": 1,
                    "message_type": NotificationType.BOOKING_CONFIRMATION,
                    "manage_url": manage_url,
                    "text": "confirmed",
                    "public_reference": appointment.public_reference,
                },
            )
        self._send_calls.clear()
        return appointment

    def test_24h_reminder_sent_when_due(self):
        now = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)
        starts = now + timedelta(hours=24)
        appointment = self._book_and_shift(
            starts_at=starts,
            created_at=starts - timedelta(days=3),
            phone_suffix="11",
        )
        result = process_due_reminders(now=now)
        self.assertEqual(result.sent, 1)
        delivery = NotificationDelivery.objects.get(
            appointment=appointment,
            notification_type=NotificationType.REMINDER_24H,
        )
        self.assertEqual(delivery.status, NotificationStatus.SENT)
        self.assertEqual(
            delivery.payload_snapshot["manage_url"],
            "https://book.example.com/book/manage/test-token",
        )
        self.assertIn("tomorrow", delivery.payload_snapshot["text"].lower())
        self.assertEqual(len(self._send_calls), 1)

    def test_1h_reminder_sent_when_due(self):
        now = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
        starts = now + timedelta(hours=1)
        appointment = self._book_and_shift(
            starts_at=starts,
            created_at=starts - timedelta(days=2),
            phone_suffix="12",
        )
        result = process_due_reminders(now=now)
        self.assertEqual(result.sent, 1)
        delivery = NotificationDelivery.objects.get(
            appointment=appointment,
            notification_type=NotificationType.REMINDER_1H,
        )
        self.assertEqual(delivery.status, NotificationStatus.SENT)
        self.assertIn("1 hour", delivery.payload_snapshot["text"].lower())

    def test_too_early_not_sent(self):
        now = datetime(2026, 9, 8, 10, 0, tzinfo=UTC)
        starts = now + timedelta(hours=48)
        self._book_and_shift(
            starts_at=starts,
            created_at=starts - timedelta(days=5),
            phone_suffix="13",
        )
        result = process_due_reminders(now=now)
        self.assertEqual(result.sent, 0)
        self.assertFalse(
            NotificationDelivery.objects.filter(
                notification_type__in=[
                    NotificationType.REMINDER_24H,
                    NotificationType.REMINDER_1H,
                ]
            ).exists()
        )

    def test_after_start_not_sent(self):
        starts = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)
        now = starts + timedelta(minutes=5)
        self._book_and_shift(
            starts_at=starts,
            created_at=starts - timedelta(days=3),
            phone_suffix="14",
        )
        result = process_due_reminders(now=now)
        self.assertEqual(result.sent, 0)

    def test_late_within_window_sent(self):
        starts = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)
        due = starts - timedelta(hours=1)
        now = due + timedelta(minutes=20)
        appointment = self._book_and_shift(
            starts_at=starts,
            created_at=starts - timedelta(days=2),
            phone_suffix="15",
        )
        result = process_due_reminders(now=now)
        self.assertEqual(result.sent, 1)
        self.assertTrue(
            NotificationDelivery.objects.filter(
                appointment=appointment,
                notification_type=NotificationType.REMINDER_1H,
                status=NotificationStatus.SENT,
            ).exists()
        )

    def test_late_beyond_window_skipped(self):
        starts = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)
        due = starts - timedelta(hours=1)
        now = due + timedelta(minutes=45)
        self._book_and_shift(
            starts_at=starts,
            created_at=starts - timedelta(days=2),
            phone_suffix="16",
        )
        result = process_due_reminders(now=now)
        self.assertEqual(result.sent, 0)

    def test_cancelled_not_reminded(self):
        now = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)
        starts = now + timedelta(hours=24)
        self._book_and_shift(
            starts_at=starts,
            created_at=starts - timedelta(days=3),
            phone_suffix="17",
            status=AppointmentStatus.CANCELLED,
        )
        result = process_due_reminders(now=now)
        self.assertEqual(result.sent, 0)

    def test_checked_in_not_reminded(self):
        now = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
        starts = now + timedelta(hours=1)
        self._book_and_shift(
            starts_at=starts,
            created_at=starts - timedelta(days=2),
            phone_suffix="18",
            status=AppointmentStatus.CHECKED_IN,
        )
        result = process_due_reminders(now=now)
        self.assertEqual(result.sent, 0)

    def test_completed_and_no_show_not_reminded(self):
        now = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
        starts = now + timedelta(hours=1)
        for suffix, status in (
            ("19", AppointmentStatus.COMPLETED),
            ("20", AppointmentStatus.NO_SHOW),
        ):
            self._book_and_shift(
                starts_at=starts,
                created_at=starts - timedelta(days=2),
                phone_suffix=suffix,
                status=status,
            )
        result = process_due_reminders(now=now)
        self.assertEqual(result.sent, 0)

    def test_soft_deleted_not_reminded(self):
        now = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)
        starts = now + timedelta(hours=24)
        appointment = self._book_and_shift(
            starts_at=starts,
            created_at=starts - timedelta(days=3),
            phone_suffix="21",
        )
        Appointment.objects.filter(pk=appointment.pk).update(deleted_at=timezone.now())
        result = process_due_reminders(now=now)
        self.assertEqual(result.sent, 0)

    def test_cancellation_race_skips_send(self):
        now = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)
        starts = now + timedelta(hours=24)
        appointment = self._book_and_shift(
            starts_at=starts,
            created_at=starts - timedelta(days=3),
            phone_suffix="22",
        )
        # Becomes due, then cancelled before processing lock completes eligibility.
        Appointment.objects.filter(pk=appointment.pk).update(status=AppointmentStatus.CANCELLED)
        result = process_due_reminders(now=now)
        self.assertEqual(result.sent, 0)
        self.assertFalse(
            NotificationDelivery.objects.filter(
                appointment=appointment,
                notification_type=NotificationType.REMINDER_24H,
            ).exists()
        )

    def test_idempotent_multiple_runs(self):
        now = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)
        starts = now + timedelta(hours=24)
        appointment = self._book_and_shift(
            starts_at=starts,
            created_at=starts - timedelta(days=3),
            phone_suffix="23",
        )
        process_due_reminders(now=now)
        process_due_reminders(now=now)
        process_due_reminders(now=now)
        self.assertEqual(
            NotificationDelivery.objects.filter(
                appointment=appointment,
                notification_type=NotificationType.REMINDER_24H,
            ).count(),
            1,
        )
        reminder_sends = [
            c
            for c in self._send_calls
            if c.get("notification_type") == NotificationType.REMINDER_24H
        ]
        self.assertEqual(len(reminder_sends), 1)

    def test_provider_failure_keeps_appointment_confirmed(self):
        now = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)
        starts = now + timedelta(hours=24)
        appointment = self._book_and_shift(
            starts_at=starts,
            created_at=starts - timedelta(days=3),
            phone_suffix="24",
        )
        self._send_patch.stop()
        with patch.object(
            LoggingWhatsAppProvider,
            "send",
            side_effect=WhatsAppProviderError("timeout", permanent=False),
        ):
            result = process_due_reminders(now=now)
        self._send_patch.start()
        self.assertEqual(result.failed, 1)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, AppointmentStatus.CONFIRMED)
        delivery = NotificationDelivery.objects.get(
            appointment=appointment,
            notification_type=NotificationType.REMINDER_24H,
        )
        self.assertEqual(delivery.status, NotificationStatus.FAILED)
        self.assertEqual(delivery.error_class, "TRANSIENT")

    def test_retry_preserves_snapshot_no_new_token(self):
        now = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)
        starts = now + timedelta(hours=24)
        appointment = self._book_and_shift(
            starts_at=starts,
            created_at=starts - timedelta(days=3),
            phone_suffix="25",
            manage_url="https://book.example.com/book/manage/frozen-token",
        )
        self._send_patch.stop()
        with patch.object(
            LoggingWhatsAppProvider,
            "send",
            side_effect=WhatsAppProviderError("rate limit", permanent=False),
        ):
            process_due_reminders(now=now)
        delivery = NotificationDelivery.objects.get(
            appointment=appointment,
            notification_type=NotificationType.REMINDER_24H,
        )
        snap = dict(delivery.payload_snapshot)
        manage_url = snap["manage_url"]
        with patch.object(
            LoggingWhatsAppProvider,
            "send",
            side_effect=self._orig_send,
            autospec=True,
        ):
            retried = retry_notification(delivery.id)
        self.assertEqual(retried.status, NotificationStatus.SENT)
        self.assertEqual(retried.payload_snapshot["manage_url"], manage_url)
        self.assertEqual(
            NotificationDelivery.objects.filter(
                appointment=appointment,
                notification_type=NotificationType.REMINDER_24H,
            ).count(),
            1,
        )
        self._send_patch.start()

    def test_timezone_labels_use_location_tz(self):
        # 2026-03-08 14:30 UTC → America/New_York (EDT) = 10:30 AM
        starts = datetime(2026, 3, 8, 14, 30, tzinfo=UTC)
        now = starts - timedelta(hours=24)
        appointment = self._book_and_shift(
            starts_at=starts,
            created_at=starts - timedelta(days=5),
            phone_suffix="26",
        )
        from locations.models import Location

        Location.objects.filter(pk=appointment.location_id).update(timezone="America/New_York")
        appointment.refresh_from_db()
        process_due_reminders(now=now)
        delivery = NotificationDelivery.objects.get(
            appointment=appointment,
            notification_type=NotificationType.REMINDER_24H,
        )
        self.assertIn("10:30 AM", delivery.payload_snapshot["time_label"])
        self.assertIn("8 March", delivery.payload_snapshot["date_label"])
        self.assertEqual(appointment.starts_at, starts)

    def test_reminders_disabled(self):
        now = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)
        starts = now + timedelta(hours=24)
        self._book_and_shift(
            starts_at=starts,
            created_at=starts - timedelta(days=3),
            phone_suffix="27",
        )
        with override_settings(WHATSAPP_REMINDERS_ENABLED=False):
            result = process_due_reminders(now=now)
        self.assertEqual(result.processed, 0)
        self.assertEqual(result.sent, 0)

    def test_1h_disabled_only_24h(self):
        now = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)
        starts_24 = now + timedelta(hours=24)
        starts_1 = now + timedelta(hours=1)
        a24 = self._book_and_shift(
            starts_at=starts_24,
            created_at=starts_24 - timedelta(days=3),
            phone_suffix="28",
        )
        self._book_and_shift(
            starts_at=starts_1,
            created_at=starts_1 - timedelta(days=2),
            phone_suffix="29",
        )
        with override_settings(WHATSAPP_REMINDER_1H_ENABLED=False):
            result = process_due_reminders(now=now)
        self.assertEqual(result.sent, 1)
        self.assertTrue(
            NotificationDelivery.objects.filter(
                appointment=a24,
                notification_type=NotificationType.REMINDER_24H,
            ).exists()
        )
        self.assertFalse(
            NotificationDelivery.objects.filter(
                notification_type=NotificationType.REMINDER_1H,
            ).exists()
        )

    def test_management_command(self):
        now = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)
        starts = now + timedelta(hours=24)
        self._book_and_shift(
            starts_at=starts,
            created_at=starts - timedelta(days=3),
            phone_suffix="30",
        )
        out = StringIO()
        with patch("booking.management.commands.send_due_reminders.timezone.now", return_value=now):
            call_command("send_due_reminders", stdout=out)
        text = out.getvalue()
        self.assertIn("Processed: 1", text)
        self.assertIn("Sent: 1", text)
        # Idempotent second run
        out2 = StringIO()
        with patch("booking.management.commands.send_due_reminders.timezone.now", return_value=now):
            call_command("send_due_reminders", stdout=out2)
        self.assertIn("Processed: 0", out2.getvalue())


@override_settings(
    WHATSAPP_ENABLED=True,
    WHATSAPP_PROVIDER="mock",
    WHATSAPP_REMINDERS_ENABLED=True,
    WHATSAPP_REMINDER_24H_ENABLED=True,
    WHATSAPP_REMINDER_1H_ENABLED=False,
    WHATSAPP_REMINDER_24H_OFFSET_MINUTES=1440,
    WHATSAPP_REMINDER_MAX_LATE_MINUTES=30,
    PUBLIC_APP_URL="https://book.example.com",
)
class ReminderConcurrencyTests(TransactionTestCase):
    def test_concurrent_scheduler_one_send(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL required for concurrent reminder tests")

        from rest_framework.test import APIClient

        from booking.tests.test_booking_api import BookingAPITestCase
        from staff.models import Weekday

        client = APIClient()
        api = BookingAPITestCase("runTest")
        api.client = client

        register = api._register("conc-rem@example.com", "Conc Rem Org")
        api._auth(register.data["access"])
        business = api._create_business()
        location = api._create_location(business["id"])
        service = api._create_service(business["id"])
        api._assign_service_location(business["id"], service["id"], location["id"])
        staff = api._create_staff(business["id"], location["id"])
        api._assign_staff_service(business["id"], staff["id"], service["id"])
        api._create_availability(business["id"], staff["id"], location["id"])
        customer = api._create_customer(business["id"], phone="+919800009999")
        monday = api._next_weekday(Weekday.MONDAY)
        created = client.post(
            reverse("appointment-list", kwargs={"business_id": business["id"]}),
            {
                "location_id": location["id"],
                "customer_id": customer["id"],
                "service_id": service["id"],
                "staff_id": staff["id"],
                "starts_at": api._local_iso(monday, "10:00"),
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        appointment = Appointment.objects.get(pk=created.data["id"])
        now = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)
        starts = now + timedelta(hours=24)
        duration = appointment.ends_at - appointment.starts_at
        Appointment.objects.filter(pk=appointment.pk).update(
            starts_at=starts,
            ends_at=starts + duration,
            occupancy_starts_at=starts,
            occupancy_ends_at=starts + duration,
            created_at=starts - timedelta(days=3),
            status=AppointmentStatus.CONFIRMED,
        )
        NotificationDelivery.objects.update_or_create(
            appointment=appointment,
            channel=NotificationChannel.WHATSAPP,
            notification_type=NotificationType.BOOKING_CONFIRMATION,
            defaults={
                "recipient": "+919800009999",
                "status": NotificationStatus.SENT,
                "attempt_count": 1,
                "payload_snapshot": {
                    "manage_url": "https://book.example.com/book/manage/x",
                    "text": "ok",
                },
            },
        )

        send_count = {"n": 0}
        orig = LoggingWhatsAppProvider.send

        def counting_send(provider, **kwargs):
            send_count["n"] += 1
            return orig(provider, **kwargs)

        def worker():
            try:
                process_due_reminders(now=now)
            finally:
                connection.close()

        with patch.object(
            LoggingWhatsAppProvider, "send", side_effect=counting_send, autospec=True
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(worker), executor.submit(worker)]
                for f in futures:
                    f.result()

        self.assertEqual(
            NotificationDelivery.objects.filter(
                appointment=appointment,
                notification_type=NotificationType.REMINDER_24H,
            ).count(),
            1,
        )
        delivery = NotificationDelivery.objects.get(
            appointment=appointment,
            notification_type=NotificationType.REMINDER_24H,
        )
        self.assertEqual(delivery.status, NotificationStatus.SENT)
        self.assertEqual(send_count["n"], 1)


class ReminderConfigCheckTests(PublicBookingAPITestCase):
    def test_meta_reminders_require_templates(self):
        from django.core.checks import run_checks

        with override_settings(
            WHATSAPP_ENABLED=True,
            WHATSAPP_PROVIDER="meta",
            WHATSAPP_REMINDERS_ENABLED=True,
            WHATSAPP_REMINDER_24H_ENABLED=True,
            WHATSAPP_REMINDER_1H_ENABLED=True,
            META_WHATSAPP_ACCESS_TOKEN="t",
            META_WHATSAPP_PHONE_NUMBER_ID="1",
            META_WHATSAPP_VERIFY_TOKEN="v",
            META_WHATSAPP_APP_SECRET="s",
            META_WHATSAPP_API_VERSION="v21.0",
            WHATSAPP_BOOKING_CONFIRMATION_TEMPLATE="c",
            WHATSAPP_BOOKING_CANCELLATION_TEMPLATE="x",
            WHATSAPP_REMINDER_24H_TEMPLATE="",
            WHATSAPP_REMINDER_1H_TEMPLATE="",
        ):
            errors = [e for e in run_checks() if e.id in ("booking.E002", "booking.E003")]
        self.assertEqual(len(errors), 2)
