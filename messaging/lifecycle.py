"""Lifecycle observer for appointment events. Does not send WhatsApp messages."""

from __future__ import annotations

import logging

logger = logging.getLogger("messaging.lifecycle")


def observe_appointment_lifecycle(event) -> None:
    """Queue templates via the automation service. Must not call the WhatsApp provider."""
    logger.info(
        "whatsapp.lifecycle_observed event=%s appointment_id=%s",
        type(event).__name__,
        getattr(event, "appointment_id", None),
    )
    from customers.retention_automation import handle_retention_lifecycle
    from messaging.automation import handle_appointment_event
    from messaging.reminders import handle_reminder_lifecycle

    handle_appointment_event(event)
    handle_reminder_lifecycle(event)
    handle_retention_lifecycle(event)
