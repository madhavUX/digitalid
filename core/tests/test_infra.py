"""Health and production infrastructure tests (Phase 6.0.2)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.core.checks import Error
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from config.celery import app as celery_app
from config.checks import check_production_infrastructure


class HealthEndpointTests(TestCase):
    def test_live_always_ok(self):
        response = self.client.get(reverse("health-live"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_ready_ok_with_database(self):
        # Without REDIS_URL, redis check is skipped in non-production.
        response = self.client.get(reverse("health-ready"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["checks"]["database"], "ok")
        self.assertEqual(body["checks"]["redis"], "skipped")

    @override_settings(REDIS_URL="redis://127.0.0.1:6399/15", DJANGO_ENV="development")
    def test_ready_503_when_redis_required_and_down(self):
        with patch("redis.from_url") as from_url:
            client = MagicMock()
            client.ping.side_effect = ConnectionError("down")
            from_url.return_value = client
            response = self.client.get(reverse("health-ready"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "unavailable")
        self.assertEqual(response.json()["checks"]["redis"], "unavailable")
        # Must not leak exception text
        self.assertNotIn("down", response.content.decode().lower())

    def test_ready_does_not_require_auth(self):
        response = self.client.get(reverse("health-ready"))
        self.assertNotEqual(response.status_code, 401)
        self.assertNotEqual(response.status_code, 403)

    @override_settings(
        DEBUG=False,
        SECURE_SSL_REDIRECT=True,
        SECURE_REDIRECT_EXEMPT=[r"^health/"],
    )
    def test_live_not_redirected_when_ssl_redirect_enabled(self):
        response = self.client.get(reverse("health-live"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")


class ProductionSettingsCheckTests(SimpleTestCase):
    @override_settings(
        DJANGO_ENV="development",
        DEBUG=True,
        REDIS_URL="",
        CELERY_BROKER_URL="memory://",
        CELERY_TASK_ALWAYS_EAGER=False,
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "t",
            }
        },
    )
    def test_development_skips_hard_checks(self):
        self.assertEqual(check_production_infrastructure(None), [])

    @override_settings(
        DJANGO_ENV="production",
        DEBUG=False,
        SECRET_KEY="x" * 48,
        ALLOWED_HOSTS=["api.example.com"],
        REDIS_URL="redis://redis:6379/0",
        CELERY_BROKER_URL="redis://redis:6379/0",
        CELERY_TASK_ALWAYS_EAGER=False,
        CSRF_TRUSTED_ORIGINS=["https://app.example.com"],
        CACHES={
            "default": {
                "BACKEND": "django_redis.cache.RedisCache",
                "LOCATION": "redis://redis:6379/0",
            }
        },
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": "bookanything",
                "HOST": "db.example-provider.internal",
                "PORT": "5432",
            }
        },
    )
    def test_production_passes_when_configured(self):
        self.assertEqual(check_production_infrastructure(None), [])

    @override_settings(
        DJANGO_ENV="production",
        DEBUG=True,
        SECRET_KEY="change-me",
        ALLOWED_HOSTS=[],
        REDIS_URL="",
        CELERY_BROKER_URL="memory://",
        CELERY_TASK_ALWAYS_EAGER=True,
        CSRF_TRUSTED_ORIGINS=[],
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "t",
            }
        },
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": "",
                "HOST": "localhost",
            }
        },
    )
    def test_production_fails_on_unsafe_defaults(self):
        errors = check_production_infrastructure(None)
        ids = {e.id for e in errors if isinstance(e, Error)}
        self.assertIn("digitalid.E001", ids)
        self.assertIn("digitalid.E002", ids)
        self.assertIn("digitalid.E003", ids)
        self.assertIn("digitalid.E004", ids)
        self.assertIn("digitalid.E005", ids)
        self.assertIn("digitalid.E006", ids)
        self.assertIn("digitalid.E007", ids)
        self.assertIn("digitalid.E008", ids)
        self.assertIn("digitalid.E009", ids)
        self.assertIn("digitalid.E010", ids)

    @override_settings(
        DJANGO_ENV="production",
        DEBUG=False,
        SECRET_KEY="x" * 48,
        ALLOWED_HOSTS=["api.example.com"],
        REDIS_URL="redis://redis:6379/0",
        CELERY_BROKER_URL="redis://redis:6379/0",
        CELERY_TASK_ALWAYS_EAGER=False,
        CSRF_TRUSTED_ORIGINS=["https://app.example.com"],
        CACHES={
            "default": {
                "BACKEND": "django_redis.cache.RedisCache",
                "LOCATION": "redis://redis:6379/0",
            }
        },
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": "digitalid",
                "HOST": "postgres",
            }
        },
    )
    def test_production_rejects_docker_compose_postgres_host(self):
        errors = check_production_infrastructure(None)
        ids = {e.id for e in errors if isinstance(e, Error)}
        self.assertIn("digitalid.E010", ids)

    @override_settings(
        DJANGO_ENV="production",
        DEBUG=False,
        SECRET_KEY="x" * 48,
        ALLOWED_HOSTS=["api.example.com"],
        REDIS_URL="redis://redis:6379/0",
        CELERY_BROKER_URL="redis://redis:6379/0",
        CELERY_TASK_ALWAYS_EAGER=False,
        CSRF_TRUSTED_ORIGINS=["https://app.example.com"],
        CACHES={
            "default": {
                "BACKEND": "django_redis.cache.RedisCache",
                "LOCATION": "redis://redis:6379/0",
            }
        },
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": "digitalid",
                "HOST": "pg.digitalid.internal",
            }
        },
    )
    def test_production_allows_vps_private_db_alias(self):
        self.assertEqual(check_production_infrastructure(None), [])


class CeleryTaskRegistrationTests(SimpleTestCase):
    def test_critical_tasks_registered(self):
        names = set(celery_app.tasks.keys())
        self.assertIn("messaging.tasks.deliver_whatsapp_message", names)
        self.assertIn("messaging.tasks.process_due_appointment_reminders", names)
        self.assertIn("messaging.tasks.process_due_retention_messages", names)
        self.assertIn("payments.tasks.noop_reconcile_payments", names)

    def test_beat_schedule_points_at_registered_tasks(self):
        from django.conf import settings

        for entry in settings.CELERY_BEAT_SCHEDULE.values():
            self.assertIn(entry["task"], celery_app.tasks)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class CeleryTaskFailureHandlingTests(TestCase):
    def test_whatsapp_deliver_swallows_missing_message(self):
        from messaging.tasks import deliver_whatsapp_message

        # Unknown id must not raise out of the task wrapper.
        deliver_whatsapp_message("00000000-0000-0000-0000-000000000000")

    def test_reminder_and_retention_tasks_return_counts_on_failure(self):
        from messaging.tasks import (
            process_due_appointment_reminders,
            process_due_retention_messages,
        )

        with patch(
            "messaging.reminders.process_due_appointment_reminders",
            side_effect=RuntimeError("boom"),
        ):
            result = process_due_appointment_reminders()
        self.assertEqual(result["queued"], 0)
        self.assertEqual(result["failed"], 0)

        with patch(
            "customers.retention_automation.process_due_retention_messages",
            side_effect=RuntimeError("boom"),
        ):
            result = process_due_retention_messages()
        self.assertEqual(result["queued"], 0)


class RedisCacheConfigurationTests(SimpleTestCase):
    def test_settings_module_exposes_redis_url(self):
        from django.conf import settings

        self.assertTrue(hasattr(settings, "REDIS_URL"))
        self.assertTrue(hasattr(settings, "DJANGO_ENV"))
        self.assertIn("default", settings.CACHES)
