"""1-hour reminders, delayed reviews, template sync, and inbound texts. No live Meta calls."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
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
from booking.services import (
    cancel_appointment,
    reschedule_appointment,
    transition_appointment_status,
)
from booking.tests.test_booking_api import BookingAPITestCase
from businesses.models import BusinessLaunchProfile
from config.celery import app as celery_app
from customers.models import Customer
from messaging.lifecycle import observe_appointment_lifecycle
from messaging.models import (
    AppointmentReminder,
    AppointmentReminderStatus,
    MessageTemplate,
    WhatsAppInboundMessage,
    WhatsAppMessage,
    WhatsAppMessageStatus,
)
from messaging.reminders import process_due_appointment_reminders
from messaging.services import deliver_queued_message
from messaging.whatsapp_provider import (
    WhatsAppRemoteTemplate,
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
    WHATSAPP_REVIEW_REQUEST_DELAY_HOURS=3,
    CELERY_TASK_ALWAYS_EAGER=True,
    PUBLIC_APP_URL="https://book.example.com",
    META_WHATSAPP_APP_SECRET="app-secret-value",
    META_WHATSAPP_VERIFY_TOKEN="verify-secret",
)
class WhatsAppPhase44Tests(BookingAPITestCase):
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

    def _connect(self, business_id, phone_number_id="pn-44"):
        return self.client.post(
            reverse("business-whatsapp-connect", kwargs={"business_id": business_id}),
            {
                "access_token": "phase44-token",
                "phone_number_id": phone_number_id,
                "business_account_id": "waba-44",
                "display_phone_number": "+919876543210",
            },
            format="json",
        )

    def _template(self, business_id, *, purpose, name, category, template_status="APPROVED"):
        return self.client.post(
            reverse("business-whatsapp-templates", kwargs={"business_id": business_id}),
            {
                "name": name,
                "language": "en",
                "purpose": purpose,
                "category": category,
                "status": template_status,
                "body": "Hi {{customer_name}} {{review_url}}",
                "variables": ["customer_name", "review_url"],
            },
            format="json",
        )

    def _book(self, ctx, hhmm="10:00"):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
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

    def test_one_hour_reminder_schedule_reschedule_and_cancel(self):
        ctx = self._seed_bookable_monday(owner_email="p44-1h@example.com", org_name="P44 1h")
        business_id = ctx["business"]["id"]
        self.assertEqual(self._connect(business_id).status_code, status.HTTP_200_OK)
        self.assertEqual(
            self._template(
                business_id,
                purpose="APPOINTMENT_REMINDER",
                name="reminder_en",
                category="REMINDER",
            ).status_code,
            status.HTTP_201_CREATED,
        )
        created = self._book(ctx)
        appointment = Appointment.objects.get(pk=created.data["id"])
        hour = AppointmentReminder.objects.get(
            appointment=appointment, notification_type="APPOINTMENT_REMINDER_1H"
        )
        self.assertEqual(hour.scheduled_for, appointment.starts_at - timedelta(hours=1))
        self.assertEqual(hour.scheduled_for.utcoffset(), timedelta(0))
        observe_appointment_lifecycle(AppointmentConfirmed(appointment_id=appointment.id))
        self.assertEqual(
            AppointmentReminder.objects.filter(
                appointment=appointment, notification_type="APPOINTMENT_REMINDER_1H"
            ).count(),
            1,
        )
        due = appointment.starts_at - timedelta(minutes=50)
        with self.captureOnCommitCallbacks(execute=True):
            result = process_due_appointment_reminders(now=due)
        self.assertGreaterEqual(result["queued"], 1)
        hour.refresh_from_db()
        self.assertEqual(hour.status, AppointmentReminderStatus.SENT)
        self.assertFalse(
            NotificationDelivery.objects.filter(
                appointment=appointment, notification_type=NotificationType.REMINDER_1H
            ).exists()
        )

        moved = self._seed_bookable_monday(
            owner_email="p44-move@example.com", org_name="P44 move", phone="+919822220002"
        )
        self._connect(moved["business"]["id"], phone_number_id="pn-move")
        self._template(
            moved["business"]["id"],
            purpose="APPOINTMENT_REMINDER",
            name="reminder_move",
            category="REMINDER",
        )
        booked = self._book(moved, "11:00")
        target = Appointment.objects.get(pk=booked.data["id"])
        stale = AppointmentReminder.objects.get(
            appointment=target, notification_type="APPOINTMENT_REMINDER_1H"
        )
        actor = User.objects.get(email="p44-move@example.com")
        from django.utils.dateparse import parse_datetime

        with self.captureOnCommitCallbacks(execute=True):
            reschedule_appointment(
                appointment=target,
                actor=actor,
                starts_at=parse_datetime(self._local_iso(moved["monday"], "15:00")),
            )
        stale.refresh_from_db()
        self.assertEqual(stale.status, AppointmentReminderStatus.CANCELLED)
        fresh = AppointmentReminder.objects.get(
            appointment=target,
            notification_type="APPOINTMENT_REMINDER_1H",
            status=AppointmentReminderStatus.PENDING,
        )
        self.assertEqual(fresh.schedule_version, 2)
        queued = WhatsAppMessage.objects.create(
            organization_id=target.organization_id,
            business_id=target.business_id,
            phone_number="+919822220002",
            message_type="TEMPLATE",
            status=WhatsAppMessageStatus.QUEUED,
            purpose="APPOINTMENT_REMINDER",
        )
        stale.whatsapp_message = queued
        stale.status = AppointmentReminderStatus.QUEUED
        stale.save(update_fields=["whatsapp_message", "status", "updated_at"])
        deliver_queued_message(message_id=str(queued.id))
        queued.refresh_from_db()
        self.assertEqual(queued.status, WhatsAppMessageStatus.CANCELLED)

        with self.captureOnCommitCallbacks(execute=True):
            cancel_appointment(appointment=target, actor=actor, reason="gone")
        fresh.refresh_from_db()
        self.assertEqual(fresh.status, AppointmentReminderStatus.CANCELLED)
        plain = self._seed_bookable_monday(
            owner_email="p44-plain@example.com", org_name="plain", phone="+919822220003"
        )
        unconnected = self._book(plain)
        self.assertFalse(
            AppointmentReminder.objects.filter(appointment_id=unconnected.data["id"]).exists()
        )
        platform = Appointment.objects.get(pk=unconnected.data["id"])
        process_due_reminders(now=platform.starts_at - timedelta(minutes=50))

    def test_delayed_review_request_rules(self):
        ctx = self._seed_bookable_monday(owner_email="p44-rev@example.com", org_name="P44 rev")
        business_id = ctx["business"]["id"]
        self._connect(business_id, phone_number_id="pn-rev")
        self._template(
            business_id, purpose="REVIEW_REQUEST", name="review_en", category="REVIEW_REQUEST"
        )
        customer = Customer.objects.get(pk=ctx["customer"]["id"])
        customer.whatsapp_opt_in = True
        customer.save(update_fields=["whatsapp_opt_in", "updated_at"])
        created = self._book(ctx, "12:00")
        appointment = Appointment.objects.select_related("organization").get(pk=created.data["id"])
        before = timezone.now()
        with self.captureOnCommitCallbacks(execute=True):
            transition_appointment_status(
                appointment=appointment,
                actor=User.objects.get(email="p44-rev@example.com"),
                new_status=AppointmentStatus.COMPLETED,
            )
        observe_appointment_lifecycle(AppointmentCompleted(appointment_id=appointment.id))
        reviews = AppointmentReminder.objects.filter(
            appointment=appointment, notification_type="REVIEW_REQUEST"
        )
        self.assertEqual(reviews.count(), 1)
        review = reviews.get()
        self.assertEqual(review.status, AppointmentReminderStatus.PENDING)
        self.assertGreaterEqual(
            review.scheduled_for, before + timedelta(hours=3) - timedelta(seconds=5)
        )
        self.assertFalse(
            WhatsAppMessage.objects.filter(
                appointment=appointment, purpose="REVIEW_REQUEST"
            ).exists()
        )
        review.scheduled_for = timezone.now() - timedelta(minutes=1)
        review.save(update_fields=["scheduled_for", "updated_at"])
        process_due_appointment_reminders(now=timezone.now())
        review.refresh_from_db()
        self.assertEqual(review.status, AppointmentReminderStatus.SKIPPED)
        self.assertEqual(review.last_error_code, "no_review_url")

        BusinessLaunchProfile.objects.create(
            organization_id=appointment.organization_id,
            business_id=appointment.business_id,
            location_id=appointment.location_id,
            google_review_url="https://maps.google.com/?cid=123",
        )
        review.status = AppointmentReminderStatus.PENDING
        review.scheduled_for = timezone.now() - timedelta(minutes=1)
        review.last_error_code = ""
        review.save()
        with self.captureOnCommitCallbacks(execute=True):
            process_due_appointment_reminders(now=timezone.now())
        review.refresh_from_db()
        self.assertEqual(review.status, AppointmentReminderStatus.SENT)

        customer.whatsapp_opt_in = False
        customer.save(update_fields=["whatsapp_opt_in", "updated_at"])
        review.status = AppointmentReminderStatus.PENDING
        review.whatsapp_message = None
        review.save()
        WhatsAppMessage.objects.filter(idempotency_key=review.idempotency_key).delete()
        process_due_appointment_reminders(now=timezone.now())
        review.refresh_from_db()
        self.assertEqual(review.last_error_code, "opt_out")

    def test_template_sync_submit_and_permissions(self):
        ctx = self._seed_bookable_monday(owner_email="p44-tpl@example.com", org_name="P44 tpl")
        business_id = ctx["business"]["id"]
        self._connect(business_id)
        created = self._template(
            business_id,
            purpose="BOOKING_CONFIRMATION",
            name="booking_ok",
            category="CONFIRMATION",
            template_status="DRAFT",
        )
        provider = get_whatsapp_business_provider()
        provider.remote_templates = [
            WhatsAppRemoteTemplate(
                name="from_meta",
                language="en",
                status="APPROVED",
                provider_template_id="meta-1",
                category="UTILITY",
                body="Hello there",
            ),
            WhatsAppRemoteTemplate(
                name="booking_ok",
                language="en",
                status="REJECTED",
                provider_template_id="meta-2",
                category="UTILITY",
                body="should not replace",
            ),
        ]
        synced = self.client.post(
            reverse("business-whatsapp-templates-sync", kwargs={"business_id": business_id})
        )
        self.assertEqual(synced.status_code, status.HTTP_200_OK)
        self.assertEqual(synced.data["created"], 1)
        local = MessageTemplate.objects.get(business_id=business_id, name="booking_ok")
        self.assertEqual(local.status, "DRAFT")
        self.assertEqual(local.provider_status, "REJECTED")
        self.assertNotIn("should not replace", local.body)
        imported = MessageTemplate.objects.get(business_id=business_id, name="from_meta")
        self.assertEqual(imported.status, "DRAFT")
        self.assertEqual(imported.provider_status, "APPROVED")
        submitted = self.client.post(
            reverse(
                "business-whatsapp-template-submit",
                kwargs={"business_id": business_id, "template_id": created.data["id"]},
            )
        )
        self.assertEqual(submitted.status_code, status.HTTP_200_OK)
        self.assertEqual(submitted.data["provider_status"], "PENDING")
        self.assertEqual(submitted.data["status"], "DRAFT")
        owner = User.objects.get(email="p44-tpl@example.com")
        staff = self._member(owner, "p44-staff@example.com", Role.STAFF)
        denied = staff.post(
            reverse("business-whatsapp-templates-sync", kwargs={"business_id": business_id})
        )
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)
        other = self._register("p44-other@example.com", "Other")
        self._auth(other.data["access"])
        hidden = self.client.get(
            reverse("business-whatsapp-messages", kwargs={"business_id": business_id})
        )
        self.assertEqual(hidden.status_code, status.HTTP_404_NOT_FOUND)

    def test_inbound_text_dedupe_and_customer_scope(self):
        ctx = self._seed_bookable_monday(
            owner_email="p44-in@example.com", org_name="P44 in", phone="+919833330001"
        )
        self._connect(ctx["business"]["id"], phone_number_id="pn-in")
        body = self._inbound("wamid.in.1", "919833330001", "pn-in", "Hello")
        first = self._post(body)
        second = self._post(body)
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        rows = WhatsAppInboundMessage.objects.filter(provider_message_id="wamid.in.1")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(str(rows.get().customer_id), ctx["customer"]["id"])
        unknown_customer = self._inbound("wamid.in.2", "919800000099", "pn-in", "Who")
        self._post(unknown_customer)
        stranger = WhatsAppInboundMessage.objects.get(provider_message_id="wamid.in.2")
        self.assertIsNone(stranger.customer_id)
        self.assertEqual(stranger.phone_number, "+919800000099")
        image = json.dumps(
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "metadata": {"phone_number_id": "pn-in"},
                                    "messages": [
                                        {"id": "wamid.img", "from": "919833330001", "type": "image"}
                                    ],
                                }
                            }
                        ]
                    }
                ]
            }
        ).encode()
        self._post(image)
        self.assertFalse(
            WhatsAppInboundMessage.objects.filter(provider_message_id="wamid.img").exists()
        )
        wrong_phone = self._inbound("wamid.in.3", "919833330001", "pn-other", "nope")
        self._post(wrong_phone)
        self.assertFalse(
            WhatsAppInboundMessage.objects.filter(provider_message_id="wamid.in.3").exists()
        )
        bad = self.client.post(
            reverse("webhook-whatsapp-meta"),
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256="sha256=nope",
        )
        self.assertEqual(bad.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            WhatsAppInboundMessage.objects.filter(business_id=ctx["business"]["id"]).count(), 2
        )

    def _member(self, owner, email, role):
        user = User.objects.create_user(
            email=email,
            password="StrongPass123",
            active_organization=owner.active_organization,
        )
        OrganizationMember.objects.create(
            organization=owner.active_organization, user=user, role=role
        )
        login = self.client.post(
            reverse("auth-login"), {"email": email, "password": "StrongPass123"}, format="json"
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        return client

    def _inbound(self, provider_id, sender, phone_number_id, text):
        return json.dumps(
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "metadata": {"phone_number_id": phone_number_id},
                                    "messages": [
                                        {
                                            "id": provider_id,
                                            "from": sender,
                                            "type": "text",
                                            "timestamp": "1760000000",
                                            "text": {"body": text},
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
