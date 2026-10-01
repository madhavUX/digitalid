"""WhatsApp webhook verification, signature, and status update tests."""

from __future__ import annotations

import hashlib
import hmac
import json

from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from booking.models import (
    NotificationChannel,
    NotificationDelivery,
    NotificationStatus,
    NotificationType,
    WhatsAppWebhookEvent,
)
from booking.tests.test_public_booking_api import PublicBookingAPITestCase
from booking.whatsapp_webhooks import apply_whatsapp_status_update


@override_settings(
    META_WHATSAPP_VERIFY_TOKEN="verify-secret",
    META_WHATSAPP_APP_SECRET="app-secret-value",
    WHATSAPP_ENABLED=True,
    WHATSAPP_PROVIDER="mock",
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
class WhatsAppWebhookTests(PublicBookingAPITestCase):
    def setUp(self):
        super().setUp()
        self.client_public = APIClient()

    def _sign(self, body: bytes) -> str:
        digest = hmac.new(
            b"app-secret-value",
            body,
            hashlib.sha256,
        ).hexdigest()
        return f"sha256={digest}"

    def test_get_verification_success(self):
        response = self.client_public.get(
            reverse("webhook-whatsapp"),
            {
                "hub.mode": "subscribe",
                "hub.verify_token": "verify-secret",
                "hub.challenge": "12345",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content.decode(), "12345")

    def test_get_verification_invalid_token(self):
        response = self.client_public.get(
            reverse("webhook-whatsapp"),
            {
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong",
                "hub.challenge": "12345",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_verification_missing_params(self):
        response = self.client_public.get(reverse("webhook-whatsapp"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def _seed_delivery(self, wamid="wamid.abc"):
        ctx = self._seed_bookable_monday(phone="+919800009901")
        with self.captureOnCommitCallbacks(execute=True):
            created = self._public_create(
                self._book_payload(ctx, "10:00", staff_id=ctx["staff"]["id"], phone="9844499001")
            )
        from booking.models import Appointment

        appointment = Appointment.objects.get(public_reference=created.data["public_reference"])
        delivery = NotificationDelivery.objects.get(appointment=appointment)
        delivery.provider_message_id = wamid
        delivery.provider_status = "sent"
        delivery.status = NotificationStatus.SENT
        delivery.save(
            update_fields=["provider_message_id", "provider_status", "status", "updated_at"]
        )
        return delivery

    def test_post_requires_valid_signature(self):
        body = json.dumps({"object": "whatsapp_business_account", "entry": []}).encode()
        bad = self.client_public.post(
            reverse("webhook-whatsapp"),
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256="sha256=deadbeef",
        )
        self.assertEqual(bad.status_code, status.HTTP_403_FORBIDDEN)

        missing = self.client_public.post(
            reverse("webhook-whatsapp"),
            data=body,
            content_type="application/json",
        )
        self.assertEqual(missing.status_code, status.HTTP_403_FORBIDDEN)

    def test_status_updates_and_idempotency(self):
        delivery = self._seed_delivery("wamid.status1")
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {
                                        "id": "wamid.status1",
                                        "status": "delivered",
                                        "timestamp": "1700000000",
                                    }
                                ]
                            }
                        }
                    ]
                }
            ],
        }
        body = json.dumps(payload).encode()
        response = self.client_public.post(
            reverse("webhook-whatsapp"),
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=self._sign(body),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        delivery.refresh_from_db()
        self.assertEqual(delivery.provider_status, "delivered")
        self.assertIsNotNone(delivery.delivered_at)

        # Duplicate webhook
        again = self.client_public.post(
            reverse("webhook-whatsapp"),
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=self._sign(body),
        )
        self.assertEqual(again.status_code, status.HTTP_200_OK)
        self.assertEqual(
            WhatsAppWebhookEvent.objects.filter(
                provider_message_id="wamid.status1",
                provider_status="delivered",
            ).count(),
            1,
        )

        # Read then ignore regress
        read_payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {
                                        "id": "wamid.status1",
                                        "status": "read",
                                        "timestamp": "1700000001",
                                    }
                                ]
                            }
                        }
                    ]
                }
            ],
        }
        read_body = json.dumps(read_payload).encode()
        self.client_public.post(
            reverse("webhook-whatsapp"),
            data=read_body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=self._sign(read_body),
        )
        delivery.refresh_from_db()
        self.assertEqual(delivery.provider_status, "read")
        self.assertIsNotNone(delivery.read_at)

    def test_failed_status(self):
        delivery = self._seed_delivery("wamid.fail1")
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {
                                        "id": "wamid.fail1",
                                        "status": "failed",
                                        "timestamp": "1700000002",
                                        "errors": [{"title": "Undeliverable"}],
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        body = json.dumps(payload).encode()
        self.client_public.post(
            reverse("webhook-whatsapp"),
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=self._sign(body),
        )
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, NotificationStatus.FAILED)
        self.assertEqual(delivery.provider_status, "failed")
        self.assertIn("Undeliverable", delivery.last_error)

    def test_unknown_message_id_is_safe(self):
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {
                                        "id": "wamid.unknown",
                                        "status": "delivered",
                                        "timestamp": "1",
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        body = json.dumps(payload).encode()
        response = self.client_public.post(
            reverse("webhook-whatsapp"),
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=self._sign(body),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(
            NotificationDelivery.objects.filter(provider_message_id="wamid.unknown").exists()
        )

    def test_unknown_event_shape_is_safe(self):
        body = json.dumps({"entry": [{"changes": [{"value": {"messages": []}}]}]}).encode()
        response = self.client_public.post(
            reverse("webhook-whatsapp"),
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=self._sign(body),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_webhook_cannot_modify_appointment(self):
        delivery = self._seed_delivery("wamid.appt")
        appointment_status = delivery.appointment.status
        apply_whatsapp_status_update(
            provider_message_id="wamid.appt",
            provider_status="delivered",
            meta_timestamp=1,
        )
        delivery.appointment.refresh_from_db()
        self.assertEqual(delivery.appointment.status, appointment_status)
        self.assertEqual(delivery.channel, NotificationChannel.WHATSAPP)
        self.assertEqual(delivery.notification_type, NotificationType.BOOKING_CONFIRMATION)
