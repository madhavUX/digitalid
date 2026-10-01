"""Infrastructure health endpoints (no authentication, no secrets)."""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger("core.health")


@require_GET
def live(request):
    """Liveness: process is up. Does not check dependencies."""
    return JsonResponse({"status": "ok"})


def _database_ok() -> bool:
    try:
        connection.ensure_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return True
    except Exception:
        logger.exception("health.database_unavailable")
        return False


def _redis_required() -> bool:
    env = (getattr(settings, "DJANGO_ENV", "development") or "").lower()
    if env == "production":
        return True
    return bool((getattr(settings, "REDIS_URL", "") or "").strip())


def _redis_ok() -> bool | None:
    """
    True = reachable, False = required but down, None = not required.
    """
    if not _redis_required():
        return None
    redis_url = (getattr(settings, "REDIS_URL", "") or "").strip()
    if not redis_url:
        return False
    try:
        import redis

        client = redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        return True
    except Exception:
        logger.exception("health.redis_unavailable")
        return False


@require_GET
def ready(request):
    """
    Readiness: database required; Redis required when REDIS_URL set or production.
    Never returns exception detail to clients.
    """
    checks: dict[str, str] = {}
    ok = True

    if _database_ok():
        checks["database"] = "ok"
    else:
        checks["database"] = "unavailable"
        ok = False

    redis_state = _redis_ok()
    if redis_state is None:
        checks["redis"] = "skipped"
    elif redis_state:
        checks["redis"] = "ok"
    else:
        checks["redis"] = "unavailable"
        ok = False

    body = {"status": "ok" if ok else "unavailable", "checks": checks}
    return JsonResponse(body, status=200 if ok else 503)
