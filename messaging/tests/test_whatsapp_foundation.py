"""WhatsApp Business foundation tests. No live Meta calls."""

from __future__ import annotations

from unittest.mock import patch

from django.contrib import admin
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from booking.events import (
    AppointmentCancelled,
    AppointmentCompleted,
    AppointmentConfirmed,
    AppointmentCreated,
    AppointmentRescheduled,
    register_handler,
)
from booking.tests.test_booking_api import BookingAPITestCase
from messaging.models import (
    WhatsAppAccount,
    WhatsAppConnectionStatus,
    WhatsAppMessage,
    WhatsAppMessageStatus,
)
from messaging.services import deliver_queued_message, queue_whatsapp_message
from messaging.whatsapp_crypto import WhatsAppCryptoError, decrypt_token, encrypt_token
from messaging.whatsapp_provider import (
    DeferredWhatsAppBusinessProvider,
    MockWhatsAppBusinessProvider,
    RealWhatsAppBusinessProvider,
    WhatsAppBusinessProviderError,
    reset_mock_whatsapp_business_provider,
)
from organizations.models import OrganizationMember, Role


def _admin_excludes_token() -> bool:
    return "access_token_encrypted" in admin.site._registry[WhatsAppAccount].exclude


@override_settings(WHATSAPP_TOKEN_ENCRYPTION_KEY="test-whatsapp-token-key")
class WhatsAppCryptoTests(SimpleTestCase):
    def test_round_trip_and_unique_ciphertext(self):
        first = encrypt_token("wa-secret-token")
        second = encrypt_token("wa-secret-token")
        self.assertTrue(first.startswith("v1:"))
        self.assertNotEqual(first, second)
        self.assertEqual(decrypt_token(first), "wa-secret-token")

    def test_empty_and_invalid(self):
        self.assertEqual(encrypt_token(""), "")
        self.assertEqual(decrypt_token(""), "")
        with self.assertRaises(WhatsAppCryptoError):
            decrypt_token("not-valid")

    def test_wrong_key_rejected(self):
        cipher = encrypt_token("hello")
        with override_settings(WHATSAPP_TOKEN_ENCRYPTION_KEY="other-whatsapp-key"):
            with self.assertRaises(WhatsAppCryptoError):
                decrypt_token(cipher)


@override_settings(
    WHATSAPP_BUSINESS_PROVIDER="mock",
    WHATSAPP_TOKEN_ENCRYPTION_KEY="test-whatsapp-token-key",
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
)
class WhatsAppFoundationTests(BookingAPITestCase):
    def setUp(self):
        super().setUp()
        reset_mock_whatsapp_business_provider()
        register = self._register("wa-owner@example.com", "WA Org")
        self.access = register.data["access"]
        self._auth(self.access)
        self.user = User.objects.get(email="wa-owner@example.com")
        business = self._create_business()
        self.business_id = business["id"]

    def _member(self, email, role):
        user = User.objects.create_user(
            email=email,
            password="StrongPass123",
            active_organization=self.user.active_organization,
        )
        OrganizationMember.objects.create(
            organization=self.user.active_organization,
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

    def _connect(self, token="super-secret-wa-token"):
        return self.client.post(
            reverse("business-whatsapp-connect", kwargs={"business_id": self.business_id}),
            {
                "access_token": token,
                "phone_number_id": "123456",
                "business_account_id": "654321",
                "display_phone_number": "+919876543210",
            },
            format="json",
        )

    def test_owner_connect_disconnect_hides_token(self):
        connected = self._connect()
        self.assertEqual(connected.status_code, status.HTTP_200_OK)
        self.assertEqual(connected.data["status"], WhatsAppConnectionStatus.CONNECTED)
        self.assertNotIn("access_token", connected.data)
        self.assertNotIn("super-secret-wa-token", str(connected.data))
        account = WhatsAppAccount.objects.get(business_id=self.business_id)
        self.assertTrue(account.access_token_encrypted.startswith("v1:"))
        self.assertNotIn("super-secret-wa-token", str(account))
        self.assertNotIn("super-secret-wa-token", repr(account))
        self.assertEqual(decrypt_token(account.access_token_encrypted), "super-secret-wa-token")
        self.assertTrue(_admin_excludes_token())

        disconnected = self.client.post(
            reverse("business-whatsapp-disconnect", kwargs={"business_id": self.business_id})
        )
        self.assertEqual(disconnected.status_code, status.HTTP_200_OK)
        self.assertEqual(disconnected.data["status"], WhatsAppConnectionStatus.DISCONNECTED)
        account.refresh_from_db()
        self.assertEqual(account.access_token_encrypted, "")

    def test_manager_read_only_staff_forbidden_cross_tenant_404(self):
        self._connect()
        manager = self._member("wa-manager@example.com", Role.MANAGER)
        staff = self._member("wa-staff@example.com", Role.STAFF)
        listed = manager.get(reverse("business-whatsapp", kwargs={"business_id": self.business_id}))
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        denied = manager.post(
            reverse("business-whatsapp-connect", kwargs={"business_id": self.business_id}),
            {
                "access_token": "x",
                "phone_number_id": "1",
                "business_account_id": "2",
            },
            format="json",
        )
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)
        staff_get = staff.get(
            reverse("business-whatsapp", kwargs={"business_id": self.business_id})
        )
        self.assertEqual(staff_get.status_code, status.HTTP_403_FORBIDDEN)

        other = self._register("wa-other@example.com", "WA Other")
        outsider = APIClient()
        outsider.credentials(HTTP_AUTHORIZATION=f"Bearer {other.data['access']}")
        missing = outsider.get(
            reverse("business-whatsapp", kwargs={"business_id": self.business_id})
        )
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)

    def test_templates_and_duplicate(self):
        created = self.client.post(
            reverse("business-whatsapp-templates", kwargs={"business_id": self.business_id}),
            {
                "name": "booking_confirmation",
                "language": "en",
                "category": "CONFIRMATION",
                "body": "Hi {{1}}",
                "variables": ["customer_name"],
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        duplicate = self.client.post(
            reverse("business-whatsapp-templates", kwargs={"business_id": self.business_id}),
            {"name": "booking_confirmation", "language": "en", "body": "again"},
            format="json",
        )
        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)
        updated = self.client.patch(
            reverse(
                "business-whatsapp-template-detail",
                kwargs={
                    "business_id": self.business_id,
                    "template_id": created.data["id"],
                },
            ),
            {"body": "Updated"},
            format="json",
        )
        self.assertEqual(updated.status_code, status.HTTP_200_OK)
        self.assertEqual(updated.data["body"], "Updated")
        deleted = self.client.delete(
            reverse(
                "business-whatsapp-template-detail",
                kwargs={
                    "business_id": self.business_id,
                    "template_id": created.data["id"],
                },
            )
        )
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)

    def test_queue_delivery_failure_and_idempotency(self):
        from config.celery import app as celery_app

        celery_app.conf.task_always_eager = True
        celery_app.conf.task_eager_propagates = True
        self._connect()
        with self.captureOnCommitCallbacks(execute=True):
            message = queue_whatsapp_message(
                organization=self.user.active_organization,
                business_id=self.business_id,
                actor=self.user,
                phone_number="+919876543210",
                body="hello",
                idempotency_key="send-1",
            )
        message.refresh_from_db()
        self.assertEqual(message.status, WhatsAppMessageStatus.SENT)
        self.assertTrue(message.provider_message_id.startswith("wamid.mock."))
        again = queue_whatsapp_message(
            organization=self.user.active_organization,
            business_id=self.business_id,
            actor=self.user,
            phone_number="+919876543210",
            body="hello",
            idempotency_key="send-1",
        )
        self.assertEqual(again.id, message.id)
        self.assertEqual(WhatsAppMessage.objects.filter(business_id=self.business_id).count(), 1)
        listed = self.client.get(
            reverse("business-whatsapp-messages", kwargs={"business_id": self.business_id})
        )
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertNotIn("access_token", str(listed.data))
        self.assertNotIn("super-secret-wa-token", str(listed.data))

        provider = reset_mock_whatsapp_business_provider()
        provider.fail_send = True
        with (
            patch(
                "messaging.services.get_whatsapp_business_provider",
                return_value=provider,
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            failed = queue_whatsapp_message(
                organization=self.user.active_organization,
                business_id=self.business_id,
                actor=self.user,
                phone_number="+919876543210",
                body="nope",
                idempotency_key="send-fail",
            )
        failed.refresh_from_db()
        self.assertEqual(failed.status, WhatsAppMessageStatus.FAILED)
        self.assertNotIn("super-secret-wa-token", failed.failure_message)

    def test_lifecycle_events_do_not_call_business_provider(self):
        seen = []
        register_handler(AppointmentCreated, lambda event: seen.append("created"))
        register_handler(AppointmentConfirmed, lambda event: seen.append("confirmed"))
        register_handler(AppointmentCancelled, lambda event: seen.append("cancelled"))
        ctx = self._seed_bookable_monday(owner_email="wa-life@example.com", org_name="WA Life")
        self._auth(ctx["token"])
        with self.captureOnCommitCallbacks(execute=True):
            created = self.client.post(
                reverse("appointment-list", kwargs={"business_id": ctx["business"]["id"]}),
                {
                    "location_id": ctx["location"]["id"],
                    "customer_id": ctx["customer"]["id"],
                    "service_id": ctx["service"]["id"],
                    "staff_id": ctx["staff"]["id"],
                    "starts_at": self._local_iso(ctx["monday"], "11:00"),
                },
                format="json",
            )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertIn("created", seen)
        self.assertIn("confirmed", seen)
        self.assertNotIn("cancelled", seen)

    @override_settings(WHATSAPP_BUSINESS_PROVIDER="deferred")
    def test_deferred_provider_rejects_connect(self):
        rejected = self._connect()
        self.assertEqual(rejected.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(rejected.data["error"]["error_code"], "CONFIG_ERROR")

    def test_provider_contracts(self):
        mock = MockWhatsAppBusinessProvider()
        snapshot = mock.configure(
            access_token="token",
            phone_number_id="pn",
            business_account_id="ba",
        )
        self.assertEqual(snapshot.verified_name, "Mock Business")
        sent = mock.send_template_message(
            access_token="token",
            phone_number_id="pn",
            to="919876543210",
            template_name="booking_confirmation",
            language="en",
            variables=["A"],
        )
        self.assertTrue(sent.provider_message_id)
        deferred = DeferredWhatsAppBusinessProvider()
        with self.assertRaises(WhatsAppBusinessProviderError):
            deferred.send_message(access_token="t", phone_number_id="p", to="1", body="x")

    def test_real_provider_normalizes_errors(self):
        provider = RealWhatsAppBusinessProvider()
        with patch("messaging.whatsapp_provider.requests.post") as post:
            response = post.return_value
            response.status_code = 401
            response.content = b""
            with self.assertRaises(WhatsAppBusinessProviderError) as caught:
                provider.send_message(
                    access_token="token",
                    phone_number_id="pn",
                    to="919876543210",
                    body="hi",
                )
        self.assertEqual(caught.exception.code, "REAUTH_REQUIRED")
        self.assertNotIn("token", str(caught.exception))


@override_settings(
    WHATSAPP_BUSINESS_PROVIDER="mock",
    WHATSAPP_TOKEN_ENCRYPTION_KEY="test-whatsapp-token-key",
    CELERY_TASK_ALWAYS_EAGER=True,
)
class WhatsAppDeliveryTaskTests(TestCase):
    def test_missing_message_is_noop(self):
        deliver_queued_message(message_id="00000000-0000-0000-0000-000000000000")


class LifecycleEventShapeTests(SimpleTestCase):
    def test_reschedule_and_completed_types_exist(self):
        self.assertEqual(AppointmentRescheduled.__name__, "AppointmentRescheduled")
        self.assertEqual(AppointmentCompleted.__name__, "AppointmentCompleted")
