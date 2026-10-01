"""Phase 5.4 Due-for-Return WhatsApp retention automation."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from accounts.models import User
from booking.models import AppointmentStatus
from booking.services import transition_appointment_status
from booking.tests.test_booking_api import BookingAPITestCase
from customers.models import (
    Customer,
    CustomerRetentionMessage,
    CustomerRetentionMessageStatus,
    RetentionSegment,
)
from customers.retention_automation import (
    process_due_retention_messages,
    retention_idempotency_key,
    schedule_due_retention_for_customer,
)
from customers.services import (
    get_or_create_retention_settings,
    refresh_customer_visit_totals,
    update_retention_settings,
)
from messaging.models import (
    MessageTemplate,
    WhatsAppAccount,
    WhatsAppConnectionStatus,
    WhatsAppMessage,
    WhatsAppTemplateCategory,
    WhatsAppTemplatePurpose,
    WhatsAppTemplateStatus,
)
from organizations.models import Role
from staff.models import Weekday


class RetentionAutomationTests(BookingAPITestCase):
    def _complete(self, appointment, actor):
        return transition_appointment_status(
            appointment=appointment,
            actor=actor,
            new_status=AppointmentStatus.COMPLETED,
        )

    def _book(self, ctx, customer_id, hhmm, day=None):
        created = self.client.post(
            reverse("appointment-list", kwargs={"business_id": ctx["business"]["id"]}),
            {
                "location_id": ctx["location"]["id"],
                "customer_id": customer_id,
                "service_id": ctx["service"]["id"],
                "staff_id": ctx["staff"]["id"],
                "starts_at": self._local_iso(day or ctx["monday"], hhmm),
                "status": AppointmentStatus.CONFIRMED,
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        from booking.models import Appointment

        return Appointment.objects.get(pk=created.data["id"])

    def _connect_whatsapp(self, ctx):
        customer = Customer.objects.get(pk=ctx["customer"]["id"])
        return WhatsAppAccount.objects.create(
            organization_id=customer.organization_id,
            business_id=ctx["business"]["id"],
            phone_number_id="phone-1",
            business_account_id="waba-1",
            display_phone_number="+919999999999",
            status=WhatsAppConnectionStatus.CONNECTED,
            access_token_encrypted="cipher",
        )

    def _retention_template(self, ctx, *, approved=True, provider_approved=True):
        customer = Customer.objects.get(pk=ctx["customer"]["id"])
        return MessageTemplate.objects.create(
            organization_id=customer.organization_id,
            business_id=ctx["business"]["id"],
            name="retention_due",
            purpose=WhatsAppTemplatePurpose.RETENTION_DUE_RETURN,
            category=WhatsAppTemplateCategory.RETENTION,
            language="en",
            status=(WhatsAppTemplateStatus.APPROVED if approved else WhatsAppTemplateStatus.DRAFT),
            provider_status=(WhatsAppTemplateStatus.APPROVED if provider_approved else "PENDING"),
            body="Hi {{customer_name}}, book again at {{business_name}}: {{booking_url}}",
            variables=["customer_name", "business_name", "booking_url"],
        )

    def _seed_returning_due(self, *, email, phone, days_since=40, opt_in=True):
        ctx = self._seed_bookable_monday(owner_email=email, org_name=f"Org {email}", phone=phone)
        owner = User.objects.get(email=email)
        self._create_availability(
            ctx["business"]["id"],
            ctx["staff"]["id"],
            ctx["location"]["id"],
            weekday=Weekday.TUESDAY,
        )
        tuesday = ctx["monday"] + timedelta(days=1)
        customer = Customer.objects.get(pk=ctx["customer"]["id"])
        a1 = self._complete(self._book(ctx, customer.id, "10:00"), owner)
        a2 = self._complete(self._book(ctx, customer.id, "10:00", day=tuesday), owner)
        a1.completed_at = timezone.now() - timedelta(days=days_since + 10)
        a2.completed_at = timezone.now() - timedelta(days=days_since)
        a1.save(update_fields=["completed_at"])
        a2.save(update_fields=["completed_at"])
        refresh_customer_visit_totals(customer_id=customer.id)
        customer.refresh_from_db()
        customer.whatsapp_opt_in = opt_in
        customer.save(update_fields=["whatsapp_opt_in", "updated_at"])
        settings = get_or_create_retention_settings(
            organization=customer.organization,
            business=customer.business,
        )
        update_retention_settings(
            settings=settings,
            actor=owner,
            enabled=True,
            return_after_days=30,
            inactive_after_days=90,
            due_message_delay_hours=24,
        )
        return ctx, owner, customer

    def test_settings_delay_and_enabled(self):
        ctx = self._seed_bookable_monday(
            owner_email="autset@example.com",
            org_name="Aut Set",
            phone="+919800003301",
        )
        path = reverse(
            "customer-retention-settings",
            kwargs={"business_id": ctx["business"]["id"]},
        )
        got = self.client.get(path)
        self.assertEqual(got.status_code, status.HTTP_200_OK)
        self.assertEqual(got.data["due_message_delay_hours"], 24)

        patched = self.client.patch(
            path,
            {"due_message_delay_hours": 12, "enabled": False},
            format="json",
        )
        self.assertEqual(patched.status_code, status.HTTP_200_OK)
        self.assertEqual(patched.data["due_message_delay_hours"], 12)
        self.assertFalse(patched.data["enabled"])

        bad = self.client.patch(path, {"due_message_delay_hours": 0}, format="json")
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)

        self._login_as_role("autset@example.com", Role.MANAGER, "autset-mgr@example.com")
        self.assertEqual(self.client.get(path).status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.client.patch(path, {"enabled": True}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_schedule_eligibility_idempotency_and_send(self):
        # Future schedule (still RETURNING): processor must not send early.
        ctx, owner, customer = self._seed_returning_due(
            email="aut1@example.com", phone="+919800003302", days_since=5
        )
        self._connect_whatsapp(ctx)
        self._retention_template(ctx)

        settings = get_or_create_retention_settings(
            organization=customer.organization, business=customer.business
        )
        update_retention_settings(settings=settings, actor=owner, enabled=False)
        self.assertIsNone(schedule_due_retention_for_customer(customer=customer))

        update_retention_settings(settings=settings, actor=owner, enabled=True)
        row = schedule_due_retention_for_customer(customer=customer)
        self.assertIsNotNone(row)
        self.assertEqual(row.status, CustomerRetentionMessageStatus.PENDING)
        expected = customer.last_visit_at + timedelta(days=30, hours=24)
        self.assertEqual(row.scheduled_for, expected)
        self.assertEqual(
            row.idempotency_key,
            retention_idempotency_key(
                customer_id=customer.id, last_visit_at=customer.last_visit_at
            ),
        )
        again = schedule_due_retention_for_customer(customer=customer)
        self.assertEqual(again.id, row.id)
        self.assertEqual(CustomerRetentionMessage.objects.filter(customer=customer).count(), 1)

        process_due_retention_messages(now=timezone.now())
        row.refresh_from_db()
        self.assertEqual(row.status, CustomerRetentionMessageStatus.PENDING)

        # Already-due cycle: opt-out skips send.
        ctx2, owner2, customer2 = self._seed_returning_due(
            email="aut1b@example.com", phone="+919800003312", days_since=40, opt_in=False
        )
        self._connect_whatsapp(ctx2)
        self._retention_template(ctx2)
        row2 = schedule_due_retention_for_customer(customer=customer2)
        self.assertIsNotNone(row2)
        process_due_retention_messages(now=timezone.now())
        row2.refresh_from_db()
        self.assertEqual(row2.status, CustomerRetentionMessageStatus.SKIPPED)
        self.assertEqual(row2.skip_reason, "opt_out")

        # New cycle after fresh visits → send
        customer2.whatsapp_opt_in = True
        customer2.save(update_fields=["whatsapp_opt_in"])
        self._create_availability(
            ctx2["business"]["id"],
            ctx2["staff"]["id"],
            ctx2["location"]["id"],
            weekday=Weekday.WEDNESDAY,
        )
        wednesday = ctx2["monday"] + timedelta(days=2)
        a3 = self._complete(self._book(ctx2, customer2.id, "10:00", day=wednesday), owner2)
        a3.completed_at = timezone.now() - timedelta(days=35)
        a3.save(update_fields=["completed_at"])
        refresh_customer_visit_totals(customer_id=customer2.id)
        customer2.refresh_from_db()
        cancel_stale = CustomerRetentionMessage.objects.filter(
            customer=customer2, status=CustomerRetentionMessageStatus.PENDING
        ).count()
        self.assertEqual(cancel_stale, 0)
        new_row = schedule_due_retention_for_customer(customer=customer2)
        self.assertIsNotNone(new_row)
        self.assertNotEqual(new_row.idempotency_key, row2.idempotency_key)

        with patch("messaging.services.get_whatsapp_business_provider") as provider_factory:
            provider = provider_factory.return_value
            provider.send_template_message.return_value = type(
                "R", (), {"provider_message_id": "wamid.ret1"}
            )()
            with patch("messaging.services._load_access_token", return_value="token"):
                process_due_retention_messages(now=timezone.now())
        new_row.refresh_from_db()
        self.assertIn(
            new_row.status,
            {
                CustomerRetentionMessageStatus.QUEUED,
                CustomerRetentionMessageStatus.SENT,
            },
        )
        self.assertIsNotNone(new_row.whatsapp_message_id)
        self.assertTrue(WhatsAppMessage.objects.filter(pk=new_row.whatsapp_message_id).exists())

    def test_ineligible_segments_and_missing_template(self):
        ctx, owner, customer = self._seed_returning_due(
            email="aut2@example.com", phone="+919800003303", days_since=5
        )
        # days_since=5 → RETURNING, not DUE
        self._connect_whatsapp(ctx)
        self._retention_template(ctx)
        row = schedule_due_retention_for_customer(customer=customer)
        self.assertIsNotNone(row)
        # Force due time but segment is RETURNING → skip
        row.scheduled_for = timezone.now() - timedelta(minutes=1)
        row.save(update_fields=["scheduled_for"])
        process_due_retention_messages(now=timezone.now())
        row.refresh_from_db()
        self.assertEqual(row.status, CustomerRetentionMessageStatus.SKIPPED)
        self.assertEqual(row.skip_reason, "segment_changed")

        ctx2, owner2, customer2 = self._seed_returning_due(
            email="aut3@example.com", phone="+919800003304", days_since=40
        )
        self._connect_whatsapp(ctx2)
        # no template
        row2 = schedule_due_retention_for_customer(customer=customer2)
        row2.scheduled_for = timezone.now() - timedelta(minutes=1)
        row2.save(update_fields=["scheduled_for"])
        process_due_retention_messages(now=timezone.now())
        row2.refresh_from_db()
        self.assertEqual(row2.status, CustomerRetentionMessageStatus.SKIPPED)
        self.assertEqual(row2.skip_reason, "no_template")

        # Unapproved template
        ctx3, owner3, customer3 = self._seed_returning_due(
            email="aut4@example.com", phone="+919800003305", days_since=40
        )
        self._connect_whatsapp(ctx3)
        self._retention_template(ctx3, approved=False)
        row3 = schedule_due_retention_for_customer(customer=customer3)
        row3.scheduled_for = timezone.now() - timedelta(minutes=1)
        row3.save(update_fields=["scheduled_for"])
        process_due_retention_messages(now=timezone.now())
        row3.refresh_from_db()
        self.assertEqual(row3.skip_reason, "no_template")

    def test_unique_idempotency_and_summary_automation(self):
        ctx, owner, customer = self._seed_returning_due(
            email="aut5@example.com", phone="+919800003306", days_since=40
        )
        key = retention_idempotency_key(
            customer_id=customer.id, last_visit_at=customer.last_visit_at
        )
        CustomerRetentionMessage.objects.create(
            organization_id=customer.organization_id,
            business_id=customer.business_id,
            customer=customer,
            segment=RetentionSegment.DUE_FOR_RETURN,
            trigger_visit_at=customer.last_visit_at,
            scheduled_for=timezone.now() + timedelta(hours=1),
            status=CustomerRetentionMessageStatus.PENDING,
            idempotency_key=key,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CustomerRetentionMessage.objects.create(
                    organization_id=customer.organization_id,
                    business_id=customer.business_id,
                    customer=customer,
                    segment=RetentionSegment.DUE_FOR_RETURN,
                    trigger_visit_at=customer.last_visit_at,
                    scheduled_for=timezone.now() + timedelta(hours=2),
                    status=CustomerRetentionMessageStatus.PENDING,
                    idempotency_key=key,
                )

        path = reverse(
            "customer-retention-summary",
            kwargs={
                "business_id": ctx["business"]["id"],
                "customer_id": customer.id,
            },
        )
        summary = self.client.get(path)
        self.assertEqual(summary.status_code, status.HTTP_200_OK)
        self.assertEqual(summary.data["segment"], RetentionSegment.DUE_FOR_RETURN)
        self.assertIsNotNone(summary.data["automation"])
        self.assertEqual(summary.data["automation"]["status"], "PENDING")
        self.assertNotIn("idempotency_key", summary.data["automation"])
        self.assertNotIn("whatsapp_message_id", summary.data["automation"])
        self.assertNotIn("id", summary.data["automation"])

        # Cross-business: Org B cannot read Org A retention summary / schedule for A customer.
        ctx_b = self._seed_bookable_monday(
            owner_email="aut5b@example.com",
            org_name="Org B Aut",
            phone="+919800003307",
        )
        foreign = self.client.get(
            reverse(
                "customer-retention-summary",
                kwargs={
                    "business_id": ctx_b["business"]["id"],
                    "customer_id": customer.id,
                },
            )
        )
        self.assertEqual(foreign.status_code, status.HTTP_404_NOT_FOUND)

        # Processor only touches tenant-owned rows (Business A message stays PENDING for B's clock).
        self.assertEqual(
            CustomerRetentionMessage.objects.filter(
                organization_id=customer.organization_id,
                business_id=customer.business_id,
                customer_id=customer.id,
            ).count(),
            1,
        )
