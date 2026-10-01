"""Secure appointment management tokens (hash-at-rest)."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from booking.models import Appointment, AppointmentManageToken, AppointmentStatus

MANAGE_TOKEN_BYTES = 32
# Long-lived for MVP; revoked_at / soft-delete still deny access.
DEFAULT_TOKEN_TTL_DAYS = 365 * 2


def hash_manage_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_raw_manage_token() -> str:
    return secrets.token_urlsafe(MANAGE_TOKEN_BYTES)


@transaction.atomic
def issue_manage_token(*, appointment: Appointment) -> str:
    """Create or rotate the manage token; return the raw token once."""
    raw = generate_raw_manage_token()
    token_hash = hash_manage_token(raw)
    expires_at = timezone.now() + timedelta(days=DEFAULT_TOKEN_TTL_DAYS)
    AppointmentManageToken.objects.update_or_create(
        appointment=appointment,
        defaults={
            "token_hash": token_hash,
            "expires_at": expires_at,
            "revoked_at": None,
        },
    )
    return raw


def resolve_appointment_for_manage_token(raw_token: str) -> Appointment | None:
    cleaned = (raw_token or "").strip()
    if not cleaned:
        return None
    token_hash = hash_manage_token(cleaned)
    row = (
        AppointmentManageToken.objects.select_related(
            "appointment",
            "appointment__location",
            "appointment__location__business",
            "appointment__staff_profile",
            "appointment__customer",
        )
        .prefetch_related("appointment__items")
        .filter(token_hash=token_hash, revoked_at__isnull=True)
        .first()
    )
    if row is None:
        return None
    if row.expires_at is not None and row.expires_at <= timezone.now():
        return None
    appointment = row.appointment
    if appointment.deleted_at is not None:
        return None
    return appointment


def appointment_can_cancel(appointment: Appointment) -> bool:
    return appointment.status in {
        AppointmentStatus.PENDING,
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.CHECKED_IN,
    }
