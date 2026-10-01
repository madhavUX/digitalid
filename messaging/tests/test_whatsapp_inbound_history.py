"""Read-only inbound history and explicit Google review URL. No live Meta or Google calls."""

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
    AppointmentCompleted,
    AppointmentConfirmed,
    AppointmentCreated,
)
from booking.models import Appointment, AppointmentStatus
from booking.services import transition_appointment_status
from booking.tests.test_booking_api import BookingAPITestCase
from businesses.models import BusinessLaunchProfile
from config.celery import app as celery_app
from customers.models import Customer
from messaging.lifecycle import observe_appointment_lifecycle
from messaging.models import AppointmentReminder, WhatsAppMessage
from messaging.reminders import process_due_appointment_reminders
from messaging.whatsapp_provider import reset_mock_whatsapp_business_provider
from organizations.models import OrganizationMember, Role


def _ensure(event_type, handler) -> None:
    bucket = _HANDLERS.setdefault(event_type, [])
    if handler not in bucket:
        bucket.append(handler)


@override_settings(
    WHATSAPP_BUSINESS_PROVIDER="mock",
    WHATSAPP_TOKEN_ENCRYPTION_KEY="test-whatsapp-token-key",
    CELERY_TASK_ALWAYS_EAGER=True,
    META_WHATSAPP_APP_SECRET="app-secret-value",
    PUBLIC_APP_URL="https://book.example.com",
)
class InboundHistoryAndReviewUrlTests(BookingAPITestCase):
    def setUp(self):
        super().setUp()
        celery_app.conf.task_always_eager = True
        celery_app.conf.task_eager_propagates = True
        reset_mock_whatsapp_business_provider()
        for event_type in (AppointmentCreated, AppointmentConfirmed, AppointmentCompleted):
            _ensure(event_type, observe_appointment_lifecycle)

    def test_inbound_history_permissions_filters_and_order(self):
        ctx = self._seed_bookable_monday(
            owner_email="p45-in@example.com", org_name="P45 in", phone="+919844440001"
        )
        business_id = ctx["business"]["id"]
        self.client.post(
            reverse("business-whatsapp-connect", kwargs={"business_id": business_id}),
            {
                "access_token": "phase45-token",
                "phone_number_id": "pn-45",
                "business_account_id": "waba-45",
                "display_phone_number": "+919876543210",
            },
            format="json",
        )
        self._post_inbound("wamid.45.old", "919800000111", "pn-45", "older")
        self._post_inbound("wamid.45.new", "919844440001", "pn-45", "newer")
        url = reverse("business-whatsapp-inbound", kwargs={"business_id": business_id})
        page = self.client.get(url, {"limit": 1})
        self.assertEqual(page.status_code, status.HTTP_200_OK)
        self.assertEqual(page.data["count"], 2)
        self.assertEqual(page.data["results"][0]["text"], "newer")
        self.assertEqual(page.data["results"][0]["customer_name"] is not None, True)
        self.assertNotIn("access_token", str(page.data))
        self.assertNotIn("authorization", str(page.data).lower())
        self.assertNotIn("payload", page.data["results"][0])
        self.assertTrue(page.data["results"][0]["phone_number"].endswith("0001"))
        self.assertIn("******", page.data["results"][0]["phone_number"])

        unknown = self.client.get(url, {"phone": "+919800000111"})
        self.assertIsNone(unknown.data["results"][0]["customer_name"])
        matched = self.client.get(url, {"customer": ctx["customer"]["id"]})
        self.assertEqual(matched.data["results"][0]["text"], "newer")
        empty_day = (timezone.now() + timedelta(days=2)).date().isoformat()
        future = self.client.get(url, {"date_from": empty_day})
        self.assertEqual(future.data["count"], 0)

        owner = User.objects.get(email="p45-in@example.com")
        manager = self._member(owner, "p45-mgr@example.com", Role.MANAGER)
        staff = self._member(owner, "p45-staff@example.com", Role.STAFF)
        self.assertEqual(manager.get(url).status_code, status.HTTP_200_OK)
        self.assertEqual(staff.get(url).status_code, status.HTTP_403_FORBIDDEN)
        other = self._register("p45-other@example.com", "Other 45")
        self._auth(other.data["access"])
        self.assertEqual(self.client.get(url).status_code, status.HTTP_404_NOT_FOUND)
        bad = self.client.post(
            reverse("webhook-whatsapp-meta"),
            data=b"{}",
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256="sha256=nope",
        )
        self.assertEqual(bad.status_code, status.HTTP_403_FORBIDDEN)

    def test_review_url_is_explicit_and_not_the_business_url(self):
        ctx = self._seed_bookable_monday(owner_email="p45-rev@example.com", org_name="P45 rev")
        business_id = ctx["business"]["id"]
        self.client.post(
            reverse("business-whatsapp-connect", kwargs={"business_id": business_id}),
            {
                "access_token": "phase45-token",
                "phone_number_id": "pn-rev45",
                "business_account_id": "waba-rev",
                "display_phone_number": "+919876543210",
            },
            format="json",
        )
        self.client.post(
            reverse("business-whatsapp-templates", kwargs={"business_id": business_id}),
            {
                "name": "review_en",
                "language": "en",
                "purpose": "REVIEW_REQUEST",
                "category": "REVIEW_REQUEST",
                "status": "APPROVED",
                "body": "Please review {{review_url}}",
                "variables": ["review_url"],
            },
            format="json",
        )
        customer = Customer.objects.get(pk=ctx["customer"]["id"])
        customer.whatsapp_opt_in = True
        customer.save(update_fields=["whatsapp_opt_in", "updated_at"])
        created = self.client.post(
            reverse("appointment-list", kwargs={"business_id": business_id}),
            {
                "location_id": ctx["location"]["id"],
                "customer_id": ctx["customer"]["id"],
                "service_id": ctx["service"]["id"],
                "staff_id": ctx["staff"]["id"],
                "starts_at": self._local_iso(ctx["monday"], "11:00"),
            },
            format="json",
        )
        appointment = Appointment.objects.get(pk=created.data["id"])
        launch = reverse("business-launch-profile", kwargs={"business_id": business_id})
        website = self.client.patch(
            launch,
            {
                "location_id": ctx["location"]["id"],
                "google_business_url": "https://salon.example.com",
            },
            format="json",
        )
        self.assertEqual(website.status_code, status.HTTP_200_OK)
        unsafe = self.client.patch(
            launch,
            {
                "location_id": ctx["location"]["id"],
                "google_review_url": "http://example.com/review",
            },
            format="json",
        )
        self.assertEqual(unsafe.status_code, status.HTTP_400_BAD_REQUEST)
        actor = User.objects.get(email="p45-rev@example.com")
        with self.captureOnCommitCallbacks(execute=True):
            transition_appointment_status(
                appointment=appointment,
                actor=actor,
                new_status=AppointmentStatus.COMPLETED,
            )
        review = AppointmentReminder.objects.get(
            appointment=appointment, notification_type="REVIEW_REQUEST"
        )
        review.scheduled_for = timezone.now() - timedelta(minutes=1)
        review.save(update_fields=["scheduled_for", "updated_at"])
        process_due_appointment_reminders(now=timezone.now())
        review.refresh_from_db()
        self.assertEqual(review.last_error_code, "no_review_url")

        saved = self.client.patch(
            launch,
            {
                "location_id": ctx["location"]["id"],
                "google_review_url": "https://search.google.com/local/writereview?placeid=abc",
            },
            format="json",
        )
        self.assertEqual(saved.status_code, status.HTTP_200_OK)
        self.assertEqual(
            saved.data["profile"]["google_review_url"],
            "https://search.google.com/local/writereview?placeid=abc",
        )
        review.status = "PENDING"
        review.last_error_code = ""
        review.save(update_fields=["status", "last_error_code", "updated_at"])
        with self.captureOnCommitCallbacks(execute=True):
            process_due_appointment_reminders(now=timezone.now())
        review.refresh_from_db()
        self.assertEqual(review.status, "SENT")
        message = WhatsAppMessage.objects.get(pk=review.whatsapp_message_id)
        self.assertIn("placeid=abc", message.payload["rendered_text"])
        self.client.patch(
            launch,
            {
                "location_id": ctx["location"]["id"],
                "google_review_url": "https://search.google.com/local/writereview?placeid=new",
            },
            format="json",
        )
        message.refresh_from_db()
        self.assertIn("placeid=abc", message.payload["rendered_text"])
        self.assertNotIn("placeid=new", message.payload["rendered_text"])

        other_location = self._create_location(business_id, name="Uptown")
        other_profile = BusinessLaunchProfile.objects.create(
            organization_id=appointment.organization_id,
            business_id=business_id,
            location_id=other_location["id"],
            google_review_url="https://search.google.com/local/writereview?placeid=other",
        )
        self.assertNotEqual(other_profile.location_id, appointment.location_id)

        manager = self._member(actor, "p45-rev-mgr@example.com", Role.MANAGER)
        denied = manager.patch(
            launch,
            {
                "location_id": ctx["location"]["id"],
                "google_review_url": "https://search.google.com/local/writereview?placeid=mgr",
            },
            format="json",
        )
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)
        other = self._register("p45-rev-other@example.com", "Other Rev")
        self._auth(other.data["access"])
        hidden = self.client.patch(
            launch,
            {
                "location_id": ctx["location"]["id"],
                "google_review_url": "https://search.google.com/local/writereview?placeid=x",
            },
            format="json",
        )
        self.assertEqual(hidden.status_code, status.HTTP_404_NOT_FOUND)

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

    def _post_inbound(self, provider_id, sender, phone_number_id, text):
        body = json.dumps(
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
        digest = hmac.new(b"app-secret-value", body, hashlib.sha256).hexdigest()
        return self.client.post(
            reverse("webhook-whatsapp-meta"),
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=f"sha256={digest}",
        )
