"""Transactional WhatsApp automation tests. No live Meta calls."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, time

from django.db import transaction
from django.test import override_settings
from django.urls import reverse
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
from booking.models import Appointment, AppointmentStatus, NotificationDelivery
from booking.notifications import handle_appointment_booked, handle_appointment_cancelled
from booking.services import (
    cancel_appointment,
    create_appointment,
    reschedule_appointment,
    transition_appointment_status,
)
from booking.tests.test_booking_api import KOLKATA, BookingAPITestCase
from businesses.models import Business
from config.celery import app as celery_app
from messaging.lifecycle import observe_appointment_lifecycle
from messaging.models import (
    AppointmentReminder,
    WhatsAppMessage,
    WhatsAppMessageStatus,
    WhatsAppTemplatePurpose,
)
from messaging.services import sync_template_provider_status
from messaging.variables import resolve_template_variables
from messaging.whatsapp_provider import reset_mock_whatsapp_business_provider


def _ensure(event_type, handler) -> None:
    bucket = _HANDLERS.setdefault(event_type, [])
    if handler not in bucket:
        bucket.append(handler)


@override_settings(
    WHATSAPP_BUSINESS_PROVIDER="mock",
    WHATSAPP_TOKEN_ENCRYPTION_KEY="test-whatsapp-token-key",
    WHATSAPP_ENABLED=True,
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    PUBLIC_APP_URL="https://book.example.com",
    META_WHATSAPP_APP_SECRET="app-secret-value",
    META_WHATSAPP_VERIFY_TOKEN="verify-secret",
)
class WhatsAppAutomationTests(BookingAPITestCase):
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
        self.public = APIClient()

    def _connect(self, business_id, phone_number_id="pn-automation"):
        return self.client.post(
            reverse("business-whatsapp-connect", kwargs={"business_id": business_id}),
            {
                "access_token": "automation-token",
                "phone_number_id": phone_number_id,
                "business_account_id": "waba-automation",
                "display_phone_number": "+919876543210",
            },
            format="json",
        )

    def _template(self, business_id, *, purpose, name, template_status="APPROVED", category=None):
        resolved_category = category or (
            "REVIEW_REQUEST" if purpose == "REVIEW_REQUEST" else "CONFIRMATION"
        )
        return self.client.post(
            reverse("business-whatsapp-templates", kwargs={"business_id": business_id}),
            {
                "name": name,
                "language": "en",
                "purpose": purpose,
                "category": resolved_category,
                "status": template_status,
                "body": "Hello {{customer_name}}",
                "variables": ["customer_name", "appointment_reference", "booking_url"],
            },
            format="json",
        )

    def _book(self, ctx, hhmm="11:00"):
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

    def test_created_and_confirmed_queue_without_platform_duplicate(self):
        ctx = self._seed_bookable_monday(owner_email="wa-auto@example.com", org_name="WA Auto")
        business_id = ctx["business"]["id"]
        connected = self._connect(business_id)
        self.assertEqual(connected.status_code, status.HTTP_200_OK)
        self.assertEqual(
            self._template(
                business_id,
                purpose="BOOKING_CONFIRMATION",
                name="booking_confirmation",
            ).status_code,
            status.HTTP_201_CREATED,
        )
        self.assertEqual(
            self._template(
                business_id,
                purpose="BOOKING_CONFIRMED",
                name="booking_confirmed",
            ).status_code,
            status.HTTP_201_CREATED,
        )
        created = self._book(ctx)
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        appointment = Appointment.objects.get(customer_id=ctx["customer"]["id"])
        messages = WhatsAppMessage.objects.filter(appointment=appointment).order_by("purpose")
        purposes = set(messages.values_list("purpose", flat=True))
        self.assertEqual(
            purposes,
            {
                WhatsAppTemplatePurpose.BOOKING_CONFIRMATION,
                WhatsAppTemplatePurpose.BOOKING_CONFIRMED,
            },
        )
        self.assertEqual(messages.count(), 2)
        self.assertFalse(NotificationDelivery.objects.filter(appointment=appointment).exists())
        confirmation = messages.get(purpose=WhatsAppTemplatePurpose.BOOKING_CONFIRMATION)
        self.assertEqual(confirmation.phone_number, "+919876543210")
        self.assertEqual(confirmation.status, WhatsAppMessageStatus.SENT)
        self.assertTrue(confirmation.provider_message_id.startswith("wamid.mock."))
        self.assertNotIn(str(appointment.organization_id), json.dumps(confirmation.payload))
        self.assertNotIn(str(appointment.id), confirmation.payload["variables"])
        self.assertIn(appointment.public_reference, confirmation.payload["variables"])
        self.assertTrue(
            any(
                value.startswith("https://book.example.com/book/")
                for value in confirmation.payload["variables"]
            )
        )
        again = messages.count()
        from messaging.automation import handle_appointment_event

        handle_appointment_event(AppointmentCreated(appointment_id=appointment.id))
        self.assertEqual(WhatsAppMessage.objects.filter(appointment=appointment).count(), again)

    def test_missing_inactive_and_disconnected_skip_without_a_message(self):
        ctx = self._seed_bookable_monday(owner_email="wa-skip@example.com", org_name="WA Skip")
        business_id = ctx["business"]["id"]
        self._connect(business_id)
        self._template(
            business_id,
            purpose="BOOKING_CONFIRMATION",
            name="draft_confirm",
            template_status="DRAFT",
        )
        created = self._book(ctx)
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertFalse(WhatsAppMessage.objects.filter(business_id=business_id).exists())
        self._template(
            business_id,
            purpose="BOOKING_CONFIRMATION",
            name="disabled_confirm",
            template_status="DISABLED",
        )
        again = self._book(ctx, "14:00")
        self.assertEqual(again.status_code, status.HTTP_201_CREATED)
        self.assertFalse(
            WhatsAppMessage.objects.filter(
                business_id=business_id,
                purpose=WhatsAppTemplatePurpose.BOOKING_CONFIRMATION,
            ).exists()
        )

    def test_disconnected_account_does_not_queue(self):
        ctx = self._seed_bookable_monday(owner_email="wa-off@example.com", org_name="WA Off")
        self._template(
            ctx["business"]["id"],
            purpose="BOOKING_CONFIRMATION",
            name="confirm_off",
        )
        created = self._book(ctx)
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertFalse(WhatsAppMessage.objects.filter(business_id=ctx["business"]["id"]).exists())

    def test_provider_failure_does_not_fail_booking(self):
        ctx = self._seed_bookable_monday(owner_email="wa-fail@example.com", org_name="WA Fail")
        business_id = ctx["business"]["id"]
        self._connect(business_id)
        self._template(business_id, purpose="BOOKING_CONFIRMATION", name="confirm_fail")
        self._template(business_id, purpose="BOOKING_CONFIRMED", name="confirmed_fail")
        provider = reset_mock_whatsapp_business_provider()
        self._connect(business_id, phone_number_id="pn-fail")
        provider.fail_send = True
        created = self._book(ctx, "11:15")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        appointment = Appointment.objects.get(pk=created.data["id"])
        self.assertEqual(appointment.status, AppointmentStatus.CONFIRMED)
        failed = WhatsAppMessage.objects.filter(appointment=appointment)
        self.assertGreaterEqual(failed.count(), 1)
        self.assertTrue(all(item.status == WhatsAppMessageStatus.FAILED for item in failed))
        self.assertTrue(all("token" not in (item.failure_message or "").lower() for item in failed))

    def test_rollback_does_not_queue(self):
        ctx = self._seed_bookable_monday(owner_email="wa-roll@example.com", org_name="WA Roll")
        business_id = ctx["business"]["id"]
        self._connect(business_id)
        self._template(business_id, purpose="BOOKING_CONFIRMATION", name="confirm_roll")
        business = Business.objects.get(pk=business_id)
        actor = User.objects.get(email="wa-roll@example.com")
        starts = datetime.combine(ctx["monday"], time(12, 0), tzinfo=KOLKATA).astimezone(UTC)
        with self.assertRaises(RuntimeError):
            with self.captureOnCommitCallbacks(execute=True):
                with transaction.atomic():
                    create_appointment(
                        organization=business.organization,
                        business_id=business.id,
                        actor=actor,
                        location_id=ctx["location"]["id"],
                        customer_id=ctx["customer"]["id"],
                        service_id=ctx["service"]["id"],
                        staff_id=ctx["staff"]["id"],
                        starts_at=starts,
                    )
                    raise RuntimeError("rollback booking")
        self.assertFalse(WhatsAppMessage.objects.filter(business_id=business_id).exists())
        self.assertFalse(Appointment.objects.filter(business_id=business_id).exists())

    def test_reschedule_cancel_and_review(self):
        ctx = self._seed_bookable_monday(owner_email="wa-life@example.com", org_name="WA Life2")
        business_id = ctx["business"]["id"]
        self._connect(business_id)
        for purpose, name in (
            ("BOOKING_CONFIRMATION", "c1"),
            ("BOOKING_CONFIRMED", "c2"),
            ("BOOKING_RESCHEDULED", "c3"),
            ("BOOKING_CANCELLED", "c4"),
            ("REVIEW_REQUEST", "c5"),
        ):
            self.assertEqual(
                self._template(business_id, purpose=purpose, name=name).status_code,
                status.HTTP_201_CREATED,
            )
        created = self._book(ctx, "13:00")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        appointment = Appointment.objects.get(pk=created.data["id"])
        actor = User.objects.get(email="wa-life@example.com")
        later = datetime.combine(ctx["monday"], time(15, 0), tzinfo=KOLKATA).astimezone(UTC)
        with self.captureOnCommitCallbacks(execute=True):
            reschedule_appointment(appointment=appointment, actor=actor, starts_at=later)
        self.assertTrue(
            WhatsAppMessage.objects.filter(
                appointment_id=appointment.id,
                purpose=WhatsAppTemplatePurpose.BOOKING_RESCHEDULED,
                status=WhatsAppMessageStatus.SENT,
            ).exists()
        )
        appointment.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            cancel_appointment(appointment=appointment, actor=actor, reason="guest")
        cancelled = WhatsAppMessage.objects.get(
            appointment_id=appointment.id,
            purpose=WhatsAppTemplatePurpose.BOOKING_CANCELLED,
        )
        self.assertEqual(cancelled.status, WhatsAppMessageStatus.SENT)
        self.assertTrue(
            cancelled.idempotency_key.startswith(f"booking-cancelled:{appointment.id}:")
        )
        self.assertFalse(
            NotificationDelivery.objects.filter(appointment_id=appointment.id).exists()
        )

        ctx_done = self._seed_bookable_monday(
            owner_email="wa-done@example.com",
            org_name="WA Done",
        )
        done_business = ctx_done["business"]["id"]
        self._auth(ctx_done["token"])
        self._connect(done_business, phone_number_id="pn-done")
        self._template(done_business, purpose="BOOKING_CONFIRMATION", name="d1")
        self._template(done_business, purpose="BOOKING_CONFIRMED", name="d2")
        self._template(done_business, purpose="REVIEW_REQUEST", name="d3")
        booked = self._book(ctx_done, "14:00")
        completed = Appointment.objects.get(pk=booked.data["id"])
        with self.captureOnCommitCallbacks(execute=True):
            transition_appointment_status(
                appointment=completed,
                actor=User.objects.get(email="wa-done@example.com"),
                new_status=AppointmentStatus.COMPLETED,
            )
        self.assertTrue(
            AppointmentReminder.objects.filter(
                appointment_id=completed.id,
                notification_type="REVIEW_REQUEST",
                status="PENDING",
            ).exists()
        )
        self.assertFalse(
            WhatsAppMessage.objects.filter(
                appointment_id=completed.id,
                purpose=WhatsAppTemplatePurpose.REVIEW_REQUEST,
            ).exists()
        )

    def test_variable_resolver_is_allowlisted(self):
        ctx = self._seed_bookable_monday(owner_email="wa-vars@example.com", org_name="WA Vars")
        created = self._book(ctx, "10:00")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        appointment = (
            Appointment.objects.select_related(
                "customer", "location", "business", "staff_profile", "organization"
            )
            .prefetch_related("items")
            .get(pk=created.data["id"])
        )
        values = resolve_template_variables(
            appointment,
            ["customer_name", "organization_id", "booking_url", "review_url"],
        )
        self.assertEqual(values[1], "")
        self.assertNotIn(str(appointment.organization_id), values)
        self.assertTrue(values[2].startswith("https://book.example.com/book/"))
        rejected = self.client.post(
            reverse("business-whatsapp-templates", kwargs={"business_id": ctx["business"]["id"]}),
            {
                "name": "bad",
                "purpose": "BOOKING_CONFIRMATION",
                "category": "CONFIRMATION",
                "status": "DRAFT",
                "variables": ["password"],
            },
            format="json",
        )
        self.assertEqual(rejected.status_code, status.HTTP_400_BAD_REQUEST)

    def test_webhook_signature_status_duplicate_and_cross_tenant(self):
        ctx = self._seed_bookable_monday(owner_email="wa-hook@example.com", org_name="WA Hook")
        business_id = ctx["business"]["id"]
        self._connect(business_id, phone_number_id="pn-hook")
        self._template(business_id, purpose="BOOKING_CONFIRMATION", name="hook_c")
        created = self._book(ctx, "11:30")
        message = WhatsAppMessage.objects.get(
            appointment_id=created.data["id"],
            purpose=WhatsAppTemplatePurpose.BOOKING_CONFIRMATION,
        )
        self.assertEqual(message.status, WhatsAppMessageStatus.SENT)
        wamid = message.provider_message_id

        def post(payload, signature):
            body = json.dumps(payload).encode()
            return self.public.post(
                reverse("webhook-whatsapp"),
                data=body,
                content_type="application/json",
                HTTP_X_HUB_SIGNATURE_256=signature or self._sign(body),
            )

        bad = post({"entry": []}, "sha256=deadbeef")
        self.assertEqual(bad.status_code, status.HTTP_403_FORBIDDEN)

        payload = self._status_payload(wamid, "delivered", "pn-other")
        other = post(payload, None)
        self.assertEqual(other.status_code, status.HTTP_200_OK)
        message.refresh_from_db()
        self.assertEqual(message.status, WhatsAppMessageStatus.SENT)

        delivered = self._status_payload(wamid, "delivered", "pn-hook")
        ok = post(delivered, None)
        self.assertEqual(ok.status_code, status.HTTP_200_OK)
        message.refresh_from_db()
        self.assertEqual(message.status, WhatsAppMessageStatus.DELIVERED)
        delivered_at = message.delivered_at
        again = post(delivered, None)
        self.assertEqual(again.status_code, status.HTTP_200_OK)
        message.refresh_from_db()
        self.assertEqual(message.delivered_at, delivered_at)

        read = post(self._status_payload(wamid, "read", "pn-hook"), None)
        self.assertEqual(read.status_code, status.HTTP_200_OK)
        message.refresh_from_db()
        self.assertEqual(message.status, WhatsAppMessageStatus.READ)

    def test_template_status_sync_uses_provider_boundary(self):
        ctx = self._seed_bookable_monday(owner_email="wa-sync@example.com", org_name="WA Sync")
        business_id = ctx["business"]["id"]
        self._connect(business_id)
        created = self._template(
            business_id,
            purpose="BOOKING_CONFIRMATION",
            name="sync_me",
            template_status="PENDING",
        )
        business = Business.objects.get(pk=business_id)
        payload = sync_template_provider_status(
            organization=business.organization,
            business_id=business.id,
            template_id=created.data["id"],
        )
        self.assertEqual(payload["provider_status"], "APPROVED")
        self.assertEqual(payload["status"], "PENDING")
        self.assertTrue(payload["provider_template_id"])
        self.assertNotIn("access_token", payload)

    def _sign(self, body: bytes) -> str:
        digest = hmac.new(b"app-secret-value", body, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    def _status_payload(self, wamid, provider_status, phone_number_id):
        return {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "ignored-business-id",
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": phone_number_id},
                                "statuses": [
                                    {
                                        "id": wamid,
                                        "status": provider_status,
                                        "timestamp": "1700000000",
                                    }
                                ],
                            }
                        }
                    ],
                }
            ],
        }
