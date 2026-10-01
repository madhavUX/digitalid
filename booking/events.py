"""Appointment domain events — lightweight in-process dispatch."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

Handler = Callable[[Any], None]
_HANDLERS: dict[type, list[Handler]] = {}


@dataclass(frozen=True)
class AppointmentBooked:
    appointment_id: UUID
    manage_token: str | None = None


@dataclass(frozen=True)
class AppointmentCancelled:
    appointment_id: UUID


@dataclass(frozen=True)
class AppointmentCreated:
    """Emitted after a new appointment row is committed. Does not send WhatsApp."""

    appointment_id: UUID


@dataclass(frozen=True)
class AppointmentConfirmed:
    appointment_id: UUID


@dataclass(frozen=True)
class AppointmentRescheduled:
    appointment_id: UUID


@dataclass(frozen=True)
class AppointmentCompleted:
    appointment_id: UUID


def register_handler(event_type: type, handler: Handler) -> None:
    _HANDLERS.setdefault(event_type, []).append(handler)


def emit(event: Any) -> None:
    """Dispatch event to registered handlers. Handler failures are swallowed."""
    for handler in _HANDLERS.get(type(event), []):
        try:
            handler(event)
        except Exception:
            logger.exception(
                "booking.event_handler_failed event=%s",
                type(event).__name__,
            )


def clear_handlers() -> None:
    """Test helper."""
    _HANDLERS.clear()
