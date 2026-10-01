"""Production environment system checks (Phase 6.0.2 / 6.0.3 prep)."""

from __future__ import annotations

from django.conf import settings
from django.core.checks import Error, Warning, register

# Hosts that must never be used when DJANGO_ENV=production.
_LOCAL_DB_HOSTS = frozenset(
    {
        "",
        "localhost",
        "127.0.0.1",
        "::1",
        "0.0.0.0",
        "postgres",  # docker-compose service name
        "db",
        "database",
    }
)


def _is_production() -> bool:
    return (getattr(settings, "DJANGO_ENV", "development") or "").lower() == "production"


def _database_host() -> str:
    cfg = (settings.DATABASES or {}).get("default") or {}
    return str(cfg.get("HOST") or "").strip().lower()


def _database_name() -> str:
    cfg = (settings.DATABASES or {}).get("default") or {}
    return str(cfg.get("NAME") or "").strip()


def _is_local_database_host(host: str) -> bool:
    if host in _LOCAL_DB_HOSTS:
        return True
    if host.endswith(".local"):
        return True
    return False


@register()
def check_production_infrastructure(app_configs, **kwargs):
    """Hard requirements when DJANGO_ENV=production."""
    if not _is_production():
        return []

    errors: list[Error] = []

    if settings.DEBUG:
        errors.append(
            Error(
                "DEBUG must be False when DJANGO_ENV=production.",
                id="digitalid.E001",
            )
        )

    secret = settings.SECRET_KEY or ""
    if not secret or secret.startswith("change-me") or len(secret) < 40:
        errors.append(
            Error(
                "DJANGO_SECRET_KEY must be a strong unique value in production.",
                id="digitalid.E002",
            )
        )

    hosts = [h for h in (settings.ALLOWED_HOSTS or []) if h and h != "*"]
    if not hosts:
        errors.append(
            Error(
                "DJANGO_ALLOWED_HOSTS must list real hosts in production.",
                id="digitalid.E003",
            )
        )

    redis_url = (getattr(settings, "REDIS_URL", "") or "").strip()
    if not redis_url:
        errors.append(
            Error(
                "REDIS_URL is required when DJANGO_ENV=production.",
                id="digitalid.E004",
            )
        )

    broker = (getattr(settings, "CELERY_BROKER_URL", "") or "").strip()
    if not broker or broker.startswith("memory://"):
        errors.append(
            Error(
                "CELERY_BROKER_URL must be a real broker (Redis), not memory://, in production.",
                id="digitalid.E005",
            )
        )

    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        errors.append(
            Error(
                "CELERY_TASK_ALWAYS_EAGER must be False in production.",
                id="digitalid.E006",
            )
        )

    cache_backend = settings.CACHES.get("default", {}).get("BACKEND", "")
    if "locmem" in cache_backend.lower():
        errors.append(
            Error(
                "LocMemCache is not allowed when DJANGO_ENV=production; use Redis.",
                id="digitalid.E007",
            )
        )

    csrf_origins = getattr(settings, "CSRF_TRUSTED_ORIGINS", None) or []
    if not csrf_origins:
        errors.append(
            Error(
                "CSRF_TRUSTED_ORIGINS must be set when DJANGO_ENV=production.",
                id="digitalid.E008",
            )
        )

    # --- Production PostgreSQL (Phase 6.0.3 preparation) ---
    db_name = _database_name()
    db_host = _database_host()
    if not db_name:
        errors.append(
            Error(
                "DATABASE_URL must define a database name when DJANGO_ENV=production.",
                id="digitalid.E009",
            )
        )
    if _is_local_database_host(db_host):
        errors.append(
            Error(
                "DATABASE_URL must not target localhost / Docker Compose default "
                "service names (postgres, db, …) when DJANGO_ENV=production. "
                "On Hostinger use the private alias pg.digitalid.internal "
                "(see docker-compose.production.yml).",
                id="digitalid.E010",
            )
        )

    return errors


@register()
def check_production_backup_reminder(app_configs, **kwargs):
    """Soft reminder: backups are operator-owned and Phase 6.0.3 is blocked until verified."""
    if not _is_production():
        return []
    return [
        Warning(
            "PHASE 6.0.3: Confirm automated PostgreSQL backups to EXTERNAL storage "
            "and complete an isolated restore drill (see docs/DATABASE_BACKUP_RESTORE.md "
            "and docs/HOSTINGER_VPS_ASSESSMENT.md). "
            "Local pg_dump and VPS snapshots alone do not satisfy this requirement.",
            id="digitalid.W001",
        )
    ]
