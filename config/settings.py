from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    DJANGO_ENV=(str, "development"),
    WHATSAPP_ENABLED=(bool, False),
    WHATSAPP_REMINDERS_ENABLED=(bool, False),
    WHATSAPP_REMINDER_24H_ENABLED=(bool, True),
    WHATSAPP_REMINDER_1H_ENABLED=(bool, True),
)

environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

# development | production | test — production enables hard infrastructure checks.
DJANGO_ENV = env("DJANGO_ENV", default="development").lower()

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "rest_framework_simplejwt",
    "accounts",
    "organizations",
    "businesses",
    "locations",
    "catalog",
    "staff",
    "customers",
    "booking",
    "sites",
    "messaging",
    "payments",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# DATABASE_URL is authoritative. Missing URL raises at import (no silent localhost fallback).
# Managed Postgres TLS: append ?sslmode=require (or verify-full) to the URL.
# CONN_MAX_AGE: 0 for local/tests; prefer >0 behind a pooler or short-lived app instances.
_db_config = env.db("DATABASE_URL")
_db_conn_max_age = env.int(
    "DATABASE_CONN_MAX_AGE",
    default=(60 if DJANGO_ENV == "production" else 0),
)
_db_config["CONN_MAX_AGE"] = _db_conn_max_age
if _db_conn_max_age:
    _db_config["CONN_HEALTH_CHECKS"] = True
DATABASES = {"default": _db_config}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# WhiteNoise serves admin/collected static under Gunicorn (DEBUG=False).
# Finders keep local runserver usable without a prior collectstatic.
WHITENOISE_USE_FINDERS = DEBUG
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Redis / cache
# ---------------------------------------------------------------------------
# Development may omit REDIS_URL (LocMem). Production (DJANGO_ENV=production)
# requires REDIS_URL for cache, Celery broker, and distributed throttling.
REDIS_URL = env("REDIS_URL", default="").strip()

if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                # Cache outages must not take down request handling.
                "IGNORE_EXCEPTIONS": True,
            },
            "KEY_PREFIX": env("REDIS_CACHE_KEY_PREFIX", default="digitalid"),
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "digitalid-default",
        }
    }

# HTTPS / cookies — applied when DEBUG is False (staging/production).
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
    # Loopback health probes and container healthchecks hit HTTP without
    # X-Forwarded-Proto; exempt so deploy/Caddy-origin checks do not 301-loop.
    SECURE_REDIRECT_EXEMPT = [r"^health/"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True)
    SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
    "DEFAULT_PAGINATION_CLASS": "core.pagination.StandardLimitOffsetPagination",
    "PAGE_SIZE": 25,
    "EXCEPTION_HANDLER": "core.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_RATES": {
        "public_booking_availability": "120/min",
        "public_booking_write": "30/min",
        "public_catalog": "120/min",
        "public_quickcard_events": "60/min",
        "public_payment_write": "30/min",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# Public booking UI base URL (manage / book-again links in notifications).
PUBLIC_APP_URL = env("PUBLIC_APP_URL", default="http://localhost:3000")

# BookAnything public site root for launch subdomains (storage/display only; no DNS automation).
BOOKANYTHING_SITE_DOMAIN = env("BOOKANYTHING_SITE_DOMAIN", default="bookanything.in")

# Google Business Profile integration.
# mock = in-process fake provider; google = live OAuth; deferred = disabled.
GOOGLE_BUSINESS_PROVIDER = env("GOOGLE_BUSINESS_PROVIDER", default="deferred")
GOOGLE_BUSINESS_ENABLED = env.bool("GOOGLE_BUSINESS_ENABLED", default=False)
GOOGLE_OAUTH_CLIENT_ID = env("GOOGLE_OAUTH_CLIENT_ID", default="")
GOOGLE_OAUTH_CLIENT_SECRET = env("GOOGLE_OAUTH_CLIENT_SECRET", default="")
GOOGLE_OAUTH_REDIRECT_URI = env(
    "GOOGLE_OAUTH_REDIRECT_URI",
    default="http://localhost:8000/api/v1/businesses/google/callback/",
)
GOOGLE_BUSINESS_SCOPES = env(
    "GOOGLE_BUSINESS_SCOPES",
    default="https://www.googleapis.com/auth/business.manage",
)
# 32-byte key as urlsafe base64, or any passphrase (SHA-256 derived) for local/dev.
GOOGLE_TOKEN_ENCRYPTION_KEY = env("GOOGLE_TOKEN_ENCRYPTION_KEY", default="")
# When provider=mock, POST /google/ connects immediately (foundation tests).
GOOGLE_MOCK_DIRECT_CONNECT = env.bool("GOOGLE_MOCK_DIRECT_CONNECT", default=True)

# WhatsApp transactional notifications.
WHATSAPP_ENABLED = env.bool("WHATSAPP_ENABLED", default=False)
WHATSAPP_PROVIDER = env("WHATSAPP_PROVIDER", default="mock")  # mock | meta

# Approved Meta template names (Business Manager).
WHATSAPP_BOOKING_CONFIRMATION_TEMPLATE = env("WHATSAPP_BOOKING_CONFIRMATION_TEMPLATE", default="")
WHATSAPP_BOOKING_CANCELLATION_TEMPLATE = env("WHATSAPP_BOOKING_CANCELLATION_TEMPLATE", default="")
WHATSAPP_TEMPLATE_LANGUAGE = env("WHATSAPP_TEMPLATE_LANGUAGE", default="en")
WHATSAPP_CONFIRMATION_BODY_FIELDS = env(
    "WHATSAPP_CONFIRMATION_BODY_FIELDS",
    default="business_name,service_name,staff_name,date_label,time_label,public_reference",
)
WHATSAPP_CANCELLATION_BODY_FIELDS = env(
    "WHATSAPP_CANCELLATION_BODY_FIELDS",
    default="business_name,service_name,date_label,time_label,public_reference",
)
# Empty = no URL button component. "0" = first URL button dynamic suffix.
WHATSAPP_CONFIRMATION_URL_BUTTON_INDEX = env("WHATSAPP_CONFIRMATION_URL_BUTTON_INDEX", default="0")
WHATSAPP_CANCELLATION_URL_BUTTON_INDEX = env("WHATSAPP_CANCELLATION_URL_BUTTON_INDEX", default="")

# Meta WhatsApp Cloud API (backend-only; never expose to Next.js).
META_WHATSAPP_ACCESS_TOKEN = env("META_WHATSAPP_ACCESS_TOKEN", default="")
META_WHATSAPP_PHONE_NUMBER_ID = env("META_WHATSAPP_PHONE_NUMBER_ID", default="")
META_WHATSAPP_BUSINESS_ACCOUNT_ID = env("META_WHATSAPP_BUSINESS_ACCOUNT_ID", default="")
META_WHATSAPP_VERIFY_TOKEN = env("META_WHATSAPP_VERIFY_TOKEN", default="")
META_WHATSAPP_APP_SECRET = env("META_WHATSAPP_APP_SECRET", default="")
META_WHATSAPP_API_VERSION = env("META_WHATSAPP_API_VERSION", default="v21.0")

# Business-owned WhatsApp Business connection (Phase 4.1). Separate from
# WHATSAPP_PROVIDER, which remains the platform transactional sender.
WHATSAPP_BUSINESS_PROVIDER = env("WHATSAPP_BUSINESS_PROVIDER", default="deferred")
WHATSAPP_TOKEN_ENCRYPTION_KEY = env("WHATSAPP_TOKEN_ENCRYPTION_KEY", default="")

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
# Prefer explicit CELERY_BROKER_URL; otherwise use REDIS_URL; otherwise memory://
# for local development only. memory:// and eager mode are forbidden in production
# (see config.checks).
_celery_broker_default = REDIS_URL if REDIS_URL else "memory://"
CELERY_BROKER_URL = (
    env("CELERY_BROKER_URL", default=_celery_broker_default).strip() or _celery_broker_default
)
_celery_result = env("CELERY_RESULT_BACKEND", default="").strip()
if not _celery_result and REDIS_URL:
    _celery_result = REDIS_URL
if _celery_result:
    CELERY_RESULT_BACKEND = _celery_result
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_IGNORE_RESULT = True
CELERY_WORKER_PREFETCH_MULTIPLIER = env.int("CELERY_WORKER_PREFETCH_MULTIPLIER", default=1)
CELERY_TASK_ACKS_LATE = env.bool("CELERY_TASK_ACKS_LATE", default=True)
CELERY_TASK_TIME_LIMIT = env.int("CELERY_TASK_TIME_LIMIT", default=300)
CELERY_TASK_SOFT_TIME_LIMIT = env.int("CELERY_TASK_SOFT_TIME_LIMIT", default=240)
# Beat: run exactly one Beat process per environment. Schedule is process-local
# (CELERY_BEAT_SCHEDULE). Do not start multiple independent Beat schedulers.
CELERY_BEAT_SCHEDULE = {
    "process-due-appointment-reminders": {
        "task": "messaging.tasks.process_due_appointment_reminders",
        "schedule": 60.0,
    },
    "process-due-retention-messages": {
        "task": "messaging.tasks.process_due_retention_messages",
        "schedule": 60.0,
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": env("LOG_LEVEL", default="WARNING"),
    },
    "loggers": {
        "celery": {"level": "INFO", "propagate": True},
        "messaging.tasks": {"level": "INFO", "propagate": True},
        "payments": {"level": "INFO", "propagate": True},
        "core.health": {"level": "WARNING", "propagate": True},
        "django.request": {"level": "WARNING", "propagate": True},
    },
}

# Automated appointment reminders (scheduler-driven; not created at booking time).
WHATSAPP_REMINDERS_ENABLED = env.bool("WHATSAPP_REMINDERS_ENABLED", default=False)
WHATSAPP_REMINDER_24H_ENABLED = env.bool("WHATSAPP_REMINDER_24H_ENABLED", default=True)
WHATSAPP_REMINDER_1H_ENABLED = env.bool("WHATSAPP_REMINDER_1H_ENABLED", default=True)
WHATSAPP_REMINDER_24H_OFFSET_MINUTES = env.int("WHATSAPP_REMINDER_24H_OFFSET_MINUTES", default=1440)
WHATSAPP_REMINDER_1H_OFFSET_MINUTES = env.int("WHATSAPP_REMINDER_1H_OFFSET_MINUTES", default=60)
WHATSAPP_REMINDER_MAX_LATE_MINUTES = env.int("WHATSAPP_REMINDER_MAX_LATE_MINUTES", default=30)
WHATSAPP_REMINDER_24H_TEMPLATE = env("WHATSAPP_REMINDER_24H_TEMPLATE", default="")
WHATSAPP_REMINDER_1H_TEMPLATE = env("WHATSAPP_REMINDER_1H_TEMPLATE", default="")
WHATSAPP_REMINDER_TEMPLATE_LANGUAGE = env("WHATSAPP_REMINDER_TEMPLATE_LANGUAGE", default="")
WHATSAPP_REMINDER_24H_BODY_FIELDS = env(
    "WHATSAPP_REMINDER_24H_BODY_FIELDS",
    default="business_name,service_name,staff_name,date_label,time_label,public_reference",
)
WHATSAPP_REMINDER_1H_BODY_FIELDS = env(
    "WHATSAPP_REMINDER_1H_BODY_FIELDS",
    default="business_name,service_name,staff_name,time_label,public_reference",
)
WHATSAPP_REMINDER_24H_URL_BUTTON_INDEX = env("WHATSAPP_REMINDER_24H_URL_BUTTON_INDEX", default="0")
WHATSAPP_REMINDER_1H_URL_BUTTON_INDEX = env("WHATSAPP_REMINDER_1H_URL_BUTTON_INDEX", default="0")
WHATSAPP_REVIEW_REQUEST_DELAY_HOURS = env.int("WHATSAPP_REVIEW_REQUEST_DELAY_HOURS", default=3)

# Guest booking history (manage-token scoped; public).
MAX_PUBLIC_BOOKING_HISTORY_PAGE_SIZE = env.int("MAX_PUBLIC_BOOKING_HISTORY_PAGE_SIZE", default=50)

# Razorpay payments (backend-only secrets — never expose to Next.js).
# mock = local/tests; deferred = block live charges; razorpay = live SDK.
RAZORPAY_PROVIDER = env("RAZORPAY_PROVIDER", default="mock")
RAZORPAY_KEY_ID = env("RAZORPAY_KEY_ID", default="")
RAZORPAY_KEY_SECRET = env("RAZORPAY_KEY_SECRET", default="")
RAZORPAY_WEBHOOK_SECRET = env("RAZORPAY_WEBHOOK_SECRET", default="")

# Register infrastructure system checks (digitalid.E00x when DJANGO_ENV=production).
from config import checks as _checks  # noqa: E402, F401
