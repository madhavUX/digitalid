"""Durable 24-hour reminder, delivery, and webhook tests. No live Meta calls."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from booking.events import (
    _HANDLERS,
    AppointmentBooked,
    AppointmentCancelled,
    AppointmentCompleted,
    AppointmentConfirmed,
    AppointmentCreated,
    AppointmentRescheduled,
)
from booking.models import Appointment, AppointmentStatus, NotificationDelivery, NotificationType
from booking.notifications import handle_appointment_booked, handle_appointment_cancelled
from booking.reminders import process_due_reminders
from booking.services import cancel_appointment, reschedule_appointment
from booking.tests.test_booking_api import BookingAPITestCase
from config.celery import app as celery_app
from messaging.lifecycle import observe_appointment_lifecycle
from messaging.models import (
    AppointmentReminder,
    AppointmentReminderStatus,
    WhatsAppMessage,
    WhatsAppMessageStatus,
)
from messaging.reminders import _create_reminder, process_due_appointment_reminders
from messaging.services import deliver_queued_message, queue_whatsapp_message
from messaging.variables import render_template_snapshot
from messaging.whatsapp_provider import (
    get_whatsapp_business_provider,
    reset_mock_whatsapp_business_provider,
)
from organizations.models import OrganizationMember, Role


def _ensure(event_type, handler) -> None:
    bucket = _HANDLERS.setdefault(event_type, [])
    if handler not in bucket:
        bucket.append(handler)


def _sign(body: bytes) -> str:
    digest = hmac.new(b"app-secret-value", body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@override_settings(
    WHATSAPP_BUSINESS_PROVIDER="mock",
    WHATSAPP_TOKEN_ENCRYPTION_KEY="test-whatsapp-token-key",
    WHATSAPP_ENABLED=True,
    WHATSAPP_REMINDERS_ENABLED=True,
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    PUBLIC_APP_URL="https://book.example.com",
    META_WHATSAPP_APP_SECRET="app-secret-value",
    META_WHATSAPP_VERIFY_TOKEN="verify-secret",
)
class AppointmentReminderTests(BookingAPITestCase):
    def setUp(self):
        super().setUp()
        celery_app.conf.task_always_eager = True
        celery_app.conf.task_eager_propagates = True
        reset_mock_whatsapp_business_provider()
        for event_type in (
            AppointmentCreated,
            AppointmentConfirmed,
            AppointmentCancelled,
            AppointmentRescheduled,
            AppointmentCompleted,
        ):
            _ensure(event_type, observe_appointment_lifecycle)
        _ensure(AppointmentBooked, handle_appointment_booked)
        _ensure(AppointmentCancelled, handle_appointment_cancelled)

    def _connect(self, business_id, phone_number_id="pn-reminder"):
        return self.client.post(
            reverse("business-whatsapp-connect", kwargs={"business_id": business_id}),
            {
                "access_token": "reminder-token",
                "phone_number_id": phone_number_id,
                "business_account_id": "waba-reminder",
                "display_phone_number": "+919876543210",
            },
            format="json",
        )

    def _template(self, business_id, *, template_status="APPROVED", name="appt_reminder"):
        return self.client.post(
            reverse("business-whatsapp-templates", kwargs={"business_id": business_id}),
            {
                "name": name,
                "language": "en",
                "purpose": "APPOINTMENT_REMINDER",
                "category": "REMINDER",
                "status": template_status,
                "body": "Hi {{customer_name}} at {{appointment_time}} ref {{booking_reference}}",
                "variables": ["customer_name", "appointment_time", "booking_reference"],
            },
            format="json",
        )

    def _book(self, ctx, hhmm="10:00"):
        with self.captureOnCommitCallbacks(execute=True):
            created = self.client.post(
                reverse("appointment-list", kwargs={"business_id": ctx["business"]["id"]}),
                {
                    "location_id": ctx["location"]["id"],
                    "customer_id": ctx["customer"]["id"],
                    "service_id": ctx["service"]["id"],
                    "staff_id": ctx["staff"]["id"],
                    "starts_at": self._local_iso(ctx["monday"], hhmm),
                },
                format="json",
            )
        return created

    def _ready(self, email, phone, template_status="APPROVED"):
        ctx = self._seed_bookable_monday(owner_email=email, org_name=email, phone=phone)
        connected = self._connect(ctx["business"]["id"])
        self.assertEqual(connected.status_code, status.HTTP_200_OK)
        if template_status is not None:
            created = self._template(ctx["business"]["id"], template_status=template_status)
            self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        return ctx

    def test_confirmed_booking_creates_one_utc_reminder(self):
        ctx = self._ready("wa-rem@example.com", "+919811110001")
        created = self._book(ctx)
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        appointment = Appointment.objects.get(pk=created.data["id"])
        reminders = AppointmentReminder.objects.filter(appointment=appointment)
        self.assertEqual(reminders.count(), 2)
        reminder = reminders.get(notification_type="APPOINTMENT_REMINDER_24H")
        self.assertEqual(reminder.status, AppointmentReminderStatus.PENDING)
        self.assertEqual(reminder.scheduled_for, appointment.starts_at - timedelta(hours=24))
        self.assertEqual(reminder.scheduled_for.utcoffset(), timedelta(0))
        again = observe_appointment_lifecycle(AppointmentConfirmed(appointment_id=appointment.id))
        self.assertIsNone(again)
        self.assertEqual(reminders.filter(notification_type="APPOINTMENT_REMINDER_24H").count(), 1)
        status_payload = self.client.get(
            reverse("business-whatsapp", kwargs={"business_id": ctx["business"]["id"]})
        )
        self.assertEqual(status_payload.data["reminder_24h"]["status"], "ENABLED")
        self.assertEqual(status_payload.data["reminder_24h"]["upcoming_count"], 1)

    def test_pending_appointment_has_no_reminder(self):
        ctx = self._ready("wa-rem-pending@example.com", "+919811110002")
        user = User.objects.get(email="wa-rem-pending@example.com")
        with self.captureOnCommitCallbacks(execute=True):
            appointment = self._pending(ctx, user)
        self.assertEqual(appointment.status, AppointmentStatus.PENDING)
        self.assertFalse(AppointmentReminder.objects.filter(appointment=appointment).exists())

    def test_local_time_and_dst_snapshot(self):
        ctx = self._ready("wa-rem-tz@example.com", "+919811110003")
        created = self._book(ctx, hhmm="10:00")
        appointment = Appointment.objects.select_related("location", "customer").get(
            pk=created.data["id"]
        )
        _, text = render_template_snapshot(
            appointment,
            body="{{appointment_time}}",
            names=["appointment_time"],
        )
        self.assertIn("10:00 AM", text)
        self.assertNotIn("04:30", text)
        appointment.location.timezone = "America/New_York"
        appointment.starts_at = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
        _, summer = render_template_snapshot(
            appointment, body="{{appointment_time}}", names=["appointment_time"]
        )
        appointment.starts_at = datetime(2026, 1, 15, 15, 0, tzinfo=UTC)
        _, winter = render_template_snapshot(
            appointment, body="{{appointment_time}}", names=["appointment_time"]
        )
        self.assertIn("10:00 AM", summer)
        self.assertIn("10:00 AM", winter)

    def test_past_due_is_skipped_and_not_sent(self):
        ctx = self._ready("wa-rem-past@example.com", "+919811110004")
        created = self._book(ctx)
        appointment = Appointment.objects.get(pk=created.data["id"])
        AppointmentReminder.objects.filter(appointment=appointment).delete()
        reminder = _create_reminder(
            appointment,
            now=appointment.starts_at,
        )
        self.assertEqual(reminder.status, AppointmentReminderStatus.SKIPPED)
        self.assertFalse(
            WhatsAppMessage.objects.filter(
                purpose="APPOINTMENT_REMINDER", appointment=appointment
            ).exists()
        )

    def test_reschedule_cancels_old_reminder_and_blocks_old_send(self):
        ctx = self._ready("wa-rem-move@example.com", "+919811110005")
        created = self._book(ctx, hhmm="10:00")
        appointment = Appointment.objects.get(pk=created.data["id"])
        old = AppointmentReminder.objects.get(
            appointment=appointment, notification_type="APPOINTMENT_REMINDER_24H"
        )
        user = User.objects.get(email="wa-rem-move@example.com")
        with self.captureOnCommitCallbacks(execute=True):
            reschedule_appointment(
                appointment=appointment,
                actor=user,
                starts_at=parse_datetime(self._local_iso(ctx["monday"], "14:00")),
            )
        old.refresh_from_db()
        appointment.refresh_from_db()
        self.assertEqual(old.status, AppointmentReminderStatus.CANCELLED)
        self.assertEqual(appointment.schedule_version, 2)
        new = AppointmentReminder.objects.get(
            appointment=appointment,
            schedule_version=2,
            notification_type="APPOINTMENT_REMINDER_24H",
            status=AppointmentReminderStatus.PENDING,
        )
        message = queue_whatsapp_message(
            organization=appointment.organization,
            business_id=appointment.business_id,
            phone_number="+919811110005",
            message_type="TEMPLATE",
            template_name="appt_reminder",
            template_language="en",
            variables=["A", "10:00 AM", "REF"],
            customer_id=appointment.customer_id,
            appointment_id=appointment.id,
            idempotency_key="old-reminder-message",
            purpose="APPOINTMENT_REMINDER",
        )
        old.whatsapp_message = message
        old.status = AppointmentReminderStatus.QUEUED
        old.save(update_fields=["whatsapp_message", "status", "updated_at"])
        deliver_queued_message(message_id=str(message.id))
        message.refresh_from_db()
        self.assertEqual(message.status, WhatsAppMessageStatus.CANCELLED)
        self.assertEqual(new.status, AppointmentReminderStatus.PENDING)

    def test_cancel_stops_pending_and_queued_send(self):
        ctx = self._ready("wa-rem-cancel@example.com", "+919811110006")
        created = self._book(ctx)
        appointment = Appointment.objects.select_related("organization").get(pk=created.data["id"])
        due = appointment.starts_at - timedelta(hours=23)
        process_due_appointment_reminders(now=due)
        reminder = AppointmentReminder.objects.get(
            appointment=appointment, status=AppointmentReminderStatus.QUEUED
        )
        self.assertEqual(reminder.status, AppointmentReminderStatus.QUEUED)
        message = reminder.whatsapp_message
        self.assertEqual(message.status, WhatsAppMessageStatus.QUEUED)
        user = User.objects.get(email="wa-rem-cancel@example.com")
        with self.captureOnCommitCallbacks(execute=True):
            cancel_appointment(appointment=appointment, actor=user, reason="changed plans")
        reminder.refresh_from_db()
        message.refresh_from_db()
        self.assertEqual(reminder.status, AppointmentReminderStatus.CANCELLED)
        self.assertEqual(message.status, WhatsAppMessageStatus.CANCELLED)
        deliver_queued_message(message_id=str(message.id))
        message.refresh_from_db()
        self.assertEqual(message.status, WhatsAppMessageStatus.CANCELLED)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, AppointmentStatus.CANCELLED)

    def test_processor_sends_once_and_keeps_snapshot(self):
        ctx = self._ready("wa-rem-send@example.com", "+919811110007")
        created = self._book(ctx)
        appointment = Appointment.objects.get(pk=created.data["id"])
        due = appointment.starts_at - timedelta(hours=23)
        with self.captureOnCommitCallbacks(execute=True):
            first = process_due_appointment_reminders(now=due)
            second = process_due_appointment_reminders(now=due)
        self.assertEqual(first["queued"], 1)
        self.assertEqual(second["seen"], 0)
        messages = WhatsAppMessage.objects.filter(
            appointment=appointment, purpose="APPOINTMENT_REMINDER"
        )
        self.assertEqual(messages.count(), 1)
        message = messages.get()
        self.assertEqual(message.status, WhatsAppMessageStatus.SENT)
        self.assertTrue(message.provider_message_id.startswith("wamid."))
        self.assertIn("10:00 AM", message.payload["rendered_text"])
        self.assertNotIn("rendered_text", str(self._history(ctx, appointment.id)))
        template = self.client.get(
            reverse("business-whatsapp-templates", kwargs={"business_id": ctx["business"]["id"]})
        )
        body_id = template.data["results"][0]["id"]
        self.client.patch(
            reverse(
                "business-whatsapp-template-detail",
                kwargs={"business_id": ctx["business"]["id"], "template_id": body_id},
            ),
            {"body": "Edited {{customer_name}}"},
            format="json",
        )
        message.refresh_from_db()
        self.assertIn("10:00 AM", message.payload["rendered_text"])
        self.assertNotIn("Edited", message.payload["rendered_text"])

    def test_missing_or_inactive_template_skips_without_failing_booking(self):
        missing = self._ready("wa-rem-notpl@example.com", "+919811110008", template_status=None)
        created = self._book(missing)
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        appointment = Appointment.objects.get(pk=created.data["id"])
        self.assertEqual(appointment.status, AppointmentStatus.CONFIRMED)
        process_due_appointment_reminders(now=appointment.starts_at - timedelta(hours=23))
        reminder = AppointmentReminder.objects.get(
            appointment=appointment, notification_type="APPOINTMENT_REMINDER_24H"
        )
        self.assertEqual(reminder.status, AppointmentReminderStatus.SKIPPED)
        self.assertEqual(reminder.last_error_code, "no_template")

        inactive = self._ready(
            "wa-rem-off@example.com", "+919811110009", template_status="DISABLED"
        )
        booked = self._book(inactive)
        self.assertEqual(booked.status_code, status.HTTP_201_CREATED)
        other = Appointment.objects.get(pk=booked.data["id"])
        process_due_appointment_reminders(now=other.starts_at - timedelta(hours=23))
        skipped = AppointmentReminder.objects.get(
            appointment=other, notification_type="APPOINTMENT_REMINDER_24H"
        )
        self.assertEqual(skipped.status, AppointmentReminderStatus.SKIPPED)

    def test_connected_skips_platform_sender_and_unconnected_has_no_row(self):
        ctx = self._ready("wa-rem-own@example.com", "+919811110010")
        created = self._book(ctx)
        appointment = Appointment.objects.get(pk=created.data["id"])
        result = process_due_reminders(now=appointment.starts_at - timedelta(hours=24, minutes=-5))
        self.assertEqual(result.sent, 0)
        self.assertFalse(
            NotificationDelivery.objects.filter(
                appointment=appointment, notification_type=NotificationType.REMINDER_24H
            ).exists()
        )
        plain = self._seed_bookable_monday(
            owner_email="wa-rem-plain@example.com",
            org_name="plain",
            phone="+919811110011",
        )
        booked = self._book(plain)
        self.assertEqual(booked.status_code, status.HTTP_201_CREATED)
        self.assertFalse(
            AppointmentReminder.objects.filter(appointment_id=booked.data["id"]).exists()
        )

    def test_webhooks_and_provider_retries(self):
        ctx = self._ready("wa-rem-hook@example.com", "+919811110012")
        created = self._book(ctx)
        appointment = Appointment.objects.select_related("organization").get(pk=created.data["id"])
        with self.captureOnCommitCallbacks(execute=True):
            process_due_appointment_reminders(now=appointment.starts_at - timedelta(hours=23))
        message = WhatsAppMessage.objects.get(
            appointment=appointment, purpose="APPOINTMENT_REMINDER"
        )
        self.assertEqual(message.status, WhatsAppMessageStatus.SENT)
        stamp = int(datetime(2026, 10, 4, 4, 30, tzinfo=UTC).timestamp())
        body = self._payload(message.provider_message_id, "delivered", stamp, "pn-reminder")
        first = self._post(body)
        second = self._post(body)
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        message.refresh_from_db()
        self.assertEqual(message.status, WhatsAppMessageStatus.DELIVERED)
        self.assertEqual(message.delivered_at, datetime.fromtimestamp(stamp, tz=UTC))
        read_body = self._payload(message.provider_message_id, "read", stamp + 60, "pn-reminder")
        self._post(read_body)
        message.refresh_from_db()
        self.assertEqual(message.status, WhatsAppMessageStatus.READ)
        unknown = self._payload(message.provider_message_id, "delivered", stamp, "someone-else")
        self.assertEqual(self._post(unknown).status_code, status.HTTP_200_OK)
        message.refresh_from_db()
        self.assertEqual(message.status, WhatsAppMessageStatus.READ)
        bad = self.client.post(
            reverse("webhook-whatsapp-meta"),
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256="sha256=deadbeef",
        )
        self.assertEqual(bad.status_code, status.HTTP_403_FORBIDDEN)

        failed = WhatsAppMessage.objects.create(
            organization=appointment.organization,
            business_id=appointment.business_id,
            phone_number="+919811110012",
            message_type="TEMPLATE",
            status=WhatsAppMessageStatus.FAILED,
            provider_message_id="wamid.failed.stale",
            purpose="APPOINTMENT_REMINDER",
            failed_at=timezone.now(),
        )
        stale = self._payload("wamid.failed.stale", "delivered", stamp, "pn-reminder")
        self._post(stale)
        failed.refresh_from_db()
        self.assertEqual(failed.status, WhatsAppMessageStatus.FAILED)

        provider = get_whatsapp_business_provider()
        provider.fail_transient = True
        transient = queue_whatsapp_message(
            organization=appointment.organization,
            business_id=appointment.business_id,
            phone_number="+919811110012",
            message_type="TEXT",
            body="ping",
            idempotency_key="transient-ping",
        )
        self.assertEqual(deliver_queued_message(message_id=str(transient.id)), "retry")
        transient.refresh_from_db()
        self.assertEqual(transient.status, WhatsAppMessageStatus.QUEUED)
        self.assertEqual(transient.delivery_attempts, 1)
        deliver_queued_message(message_id=str(transient.id))
        deliver_queued_message(message_id=str(transient.id))
        transient.refresh_from_db()
        self.assertEqual(transient.status, WhatsAppMessageStatus.FAILED)
        self.assertEqual(
            WhatsAppMessage.objects.filter(idempotency_key="transient-ping").count(), 1
        )

        provider.fail_transient = False
        provider.fail_send = True
        permanent = queue_whatsapp_message(
            organization=appointment.organization,
            business_id=appointment.business_id,
            phone_number="+919811110012",
            message_type="TEXT",
            body="nope",
            idempotency_key="permanent-ping",
        )
        deliver_queued_message(message_id=str(permanent.id))
        permanent.refresh_from_db()
        self.assertEqual(permanent.status, WhatsAppMessageStatus.FAILED)
        self.assertEqual(permanent.failure_code, "PROVIDER_ERROR")

    def test_message_permissions_and_filters(self):
        ctx = self._ready("wa-rem-perm@example.com", "+919811110013")
        created = self._book(ctx)
        owner = User.objects.get(email="wa-rem-perm@example.com")
        manager_client = self._member(owner, "wa-rem-manager@example.com", Role.MANAGER)
        staff_client = self._member(owner, "wa-rem-staff@example.com", Role.STAFF)
        url = reverse("business-whatsapp-messages", kwargs={"business_id": ctx["business"]["id"]})
        staff_response = staff_client.get(url)
        self.assertEqual(staff_response.status_code, status.HTTP_403_FORBIDDEN)
        filtered = manager_client.get(
            url, {"appointment": created.data["id"], "purpose": "BOOKING_CONFIRMED"}
        )
        self.assertEqual(filtered.status_code, status.HTTP_200_OK)
        self.assertNotIn("access_token", str(filtered.data))
        other = self._register("wa-rem-other@example.com", "Other Org")
        self._auth(other.data["access"])
        hidden = self.client.get(url)
        self.assertEqual(hidden.status_code, status.HTTP_404_NOT_FOUND)

    def _pending(self, ctx, user):
        from booking.services import create_appointment

        return create_appointment(
            organization=user.active_organization,
            business_id=ctx["business"]["id"],
            actor=user,
            location_id=ctx["location"]["id"],
            customer_id=ctx["customer"]["id"],
            service_id=ctx["service"]["id"],
            staff_id=ctx["staff"]["id"],
            starts_at=parse_datetime(self._local_iso(ctx["monday"], "11:00")),
            status=AppointmentStatus.PENDING,
        )

    def _history(self, ctx, appointment_id):
        return self.client.get(
            reverse("business-whatsapp-messages", kwargs={"business_id": ctx["business"]["id"]}),
            {"appointment": str(appointment_id), "purpose": "APPOINTMENT_REMINDER"},
        ).data

    def _member(self, owner, email, role):
        user = User.objects.create_user(
            email=email,
            password="StrongPass123",
            active_organization=owner.active_organization,
        )
        OrganizationMember.objects.create(
            organization=owner.active_organization,
            user=user,
            role=role,
        )
        login = self.client.post(
            reverse("auth-login"),
            {"email": email, "password": "StrongPass123"},
            format="json",
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        return client

    def _payload(self, wamid, provider_status, stamp, phone_number_id):
        return json.dumps(
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "metadata": {"phone_number_id": phone_number_id},
                                    "statuses": [
                                        {
                                            "id": wamid,
                                            "status": provider_status,
                                            "timestamp": str(stamp),
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                ]
            }
        ).encode()

    def _post(self, body: bytes):
        return self.client.post(
            reverse("webhook-whatsapp-meta"),
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=_sign(body),
        )
