"""Meta WhatsApp Cloud API provider unit tests (no live network)."""

from __future__ import annotations

import io
import json
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase, override_settings

from booking.meta_whatsapp import MetaWhatsAppProvider
from booking.whatsapp import WhatsAppProviderError, normalize_whatsapp_recipient


@override_settings(
    META_WHATSAPP_ACCESS_TOKEN="test-access-token",
    META_WHATSAPP_PHONE_NUMBER_ID="1234567890",
    META_WHATSAPP_API_VERSION="v21.0",
    WHATSAPP_BOOKING_CONFIRMATION_TEMPLATE="booking_confirmation",
    WHATSAPP_BOOKING_CANCELLATION_TEMPLATE="booking_cancellation",
    WHATSAPP_TEMPLATE_LANGUAGE="en",
    WHATSAPP_CONFIRMATION_BODY_FIELDS=(
        "business_name,service_name,staff_name,date_label,time_label,public_reference"
    ),
    WHATSAPP_CONFIRMATION_URL_BUTTON_INDEX="0",
    WHATSAPP_CANCELLATION_BODY_FIELDS=(
        "business_name,service_name,date_label,time_label,public_reference"
    ),
    WHATSAPP_CANCELLATION_URL_BUTTON_INDEX="",
)
class MetaWhatsAppProviderTests(SimpleTestCase):
    def setUp(self):
        self.provider = MetaWhatsAppProvider()
        self.snapshot = {
            "business_name": "Example Salon",
            "service_name": "Haircut",
            "staff_name": "Rahul",
            "date_label": "10 September 2026",
            "time_label": "10:00 AM – 10:30 AM",
            "public_reference": "BA-ABC123",
            "manage_url": "https://book.example.com/book/manage/secure-token-value",
            "text": "Your booking is confirmed.",
        }

    def test_normalize_recipient(self):
        self.assertEqual(normalize_whatsapp_recipient("+919876543210"), "919876543210")
        with self.assertRaises(WhatsAppProviderError):
            normalize_whatsapp_recipient("not-a-phone")

    def test_success_posts_template_and_extracts_wamid(self):
        captured = {}

        class FakeResponse:
            status = 200

            def read(self):
                return json.dumps({"messages": [{"id": "wamid.test123"}]}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout=None, context=None):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["auth"] = request.get_header("Authorization")
            captured["body"] = json.loads(request.data.decode())
            return FakeResponse()

        with patch("booking.meta_whatsapp.urllib.request.urlopen", side_effect=fake_urlopen):
            result = self.provider.send(
                to="+919876543210",
                notification_type="BOOKING_CONFIRMATION",
                snapshot=self.snapshot,
                notification_id=uuid4(),
            )

        self.assertEqual(result.provider_message_id, "wamid.test123")
        self.assertEqual(
            captured["url"],
            "https://graph.facebook.com/v21.0/1234567890/messages",
        )
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["auth"], "Bearer test-access-token")
        self.assertNotIn("test-access-token", json.dumps(captured["body"]))
        template = captured["body"]["template"]
        self.assertEqual(template["name"], "booking_confirmation")
        self.assertEqual(template["language"]["code"], "en")
        body_params = template["components"][0]["parameters"]
        self.assertEqual(body_params[0]["text"], "Example Salon")
        self.assertEqual(body_params[5]["text"], "BA-ABC123")
        button = template["components"][1]
        self.assertEqual(button["type"], "button")
        self.assertEqual(button["parameters"][0]["text"], "secure-token-value")
        self.assertEqual(captured["body"]["to"], "919876543210")

    def test_reminder_24h_template(self):
        captured = {}

        class FakeResponse:
            status = 200

            def read(self):
                return json.dumps({"messages": [{"id": "wamid.reminder24"}]}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout=None, context=None):
            captured["body"] = json.loads(request.data.decode())
            return FakeResponse()

        with override_settings(
            WHATSAPP_REMINDER_24H_TEMPLATE="appointment_reminder_24h",
            WHATSAPP_REMINDER_TEMPLATE_LANGUAGE="en",
            WHATSAPP_REMINDER_24H_BODY_FIELDS=(
                "business_name,service_name,staff_name,date_label,time_label,public_reference"
            ),
            WHATSAPP_REMINDER_24H_URL_BUTTON_INDEX="0",
        ):
            with patch("booking.meta_whatsapp.urllib.request.urlopen", side_effect=fake_urlopen):
                result = self.provider.send(
                    to="+919876543210",
                    notification_type="REMINDER_24H",
                    snapshot=self.snapshot,
                    notification_id=uuid4(),
                )
        self.assertEqual(result.provider_message_id, "wamid.reminder24")
        self.assertEqual(captured["body"]["template"]["name"], "appointment_reminder_24h")

    def test_meta_429_is_transient(self):
        err = urllib_http_error(429, {"error": {"message": "rate limit"}})
        with patch("booking.meta_whatsapp.urllib.request.urlopen", side_effect=err):
            with self.assertRaises(WhatsAppProviderError) as ctx:
                self.provider.send(
                    to="+919876543210",
                    notification_type="BOOKING_CONFIRMATION",
                    snapshot=self.snapshot,
                    notification_id=uuid4(),
                )
        self.assertFalse(ctx.exception.permanent)

    def test_meta_500_is_transient(self):
        err = urllib_http_error(500, {"error": {"message": "server error"}})
        with patch("booking.meta_whatsapp.urllib.request.urlopen", side_effect=err):
            with self.assertRaises(WhatsAppProviderError) as ctx:
                self.provider.send(
                    to="+919876543210",
                    notification_type="BOOKING_CONFIRMATION",
                    snapshot=self.snapshot,
                    notification_id=uuid4(),
                )
        self.assertFalse(ctx.exception.permanent)

    def test_timeout(self):
        with patch(
            "booking.meta_whatsapp.urllib.request.urlopen",
            side_effect=TimeoutError(),
        ):
            with self.assertRaises(WhatsAppProviderError) as ctx:
                self.provider.send(
                    to="+919876543210",
                    notification_type="BOOKING_CONFIRMATION",
                    snapshot=self.snapshot,
                    notification_id=uuid4(),
                )
        self.assertFalse(ctx.exception.permanent)

    def test_malformed_response(self):
        class FakeResponse:
            status = 200

            def read(self):
                return b"not-json"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch(
            "booking.meta_whatsapp.urllib.request.urlopen",
            return_value=FakeResponse(),
        ):
            with self.assertRaises(WhatsAppProviderError):
                self.provider.send(
                    to="+919876543210",
                    notification_type="BOOKING_CONFIRMATION",
                    snapshot=self.snapshot,
                    notification_id=uuid4(),
                )

    def test_missing_message_id(self):
        class FakeResponse:
            status = 200

            def read(self):
                return b'{"messages":[]}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch(
            "booking.meta_whatsapp.urllib.request.urlopen",
            return_value=FakeResponse(),
        ):
            with self.assertRaises(WhatsAppProviderError):
                self.provider.send(
                    to="+919876543210",
                    notification_type="BOOKING_CONFIRMATION",
                    snapshot=self.snapshot,
                    notification_id=uuid4(),
                )

    def test_does_not_log_access_token(self):
        class FakeResponse:
            status = 200

            def read(self):
                return json.dumps({"messages": [{"id": "wamid.x"}]}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch(
            "booking.meta_whatsapp.urllib.request.urlopen",
            return_value=FakeResponse(),
        ):
            with self.assertLogs("booking.meta_whatsapp", level="INFO") as captured:
                self.provider.send(
                    to="+919876543210",
                    notification_type="BOOKING_CONFIRMATION",
                    snapshot=self.snapshot,
                    notification_id=uuid4(),
                )
        joined = "\n".join(captured.output)
        self.assertNotIn("test-access-token", joined)
        self.assertNotIn("secure-token-value", joined)


def urllib_http_error(code: int, payload: dict):
    import urllib.error

    body = json.dumps(payload).encode()
    return urllib.error.HTTPError(
        url="https://graph.facebook.com",
        code=code,
        msg="error",
        hdrs=None,
        fp=io.BytesIO(body),
    )
