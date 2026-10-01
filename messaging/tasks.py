import logging

from celery import shared_task
from django.conf import settings


@shared_task(bind=True, max_retries=3)
def deliver_whatsapp_message(self, message_id: str) -> None:
    """Deliver a queued WhatsApp message outside the booking request."""
    from messaging.services import deliver_queued_message

    try:
        outcome = deliver_queued_message(message_id=message_id)
    except Exception:
        logging.getLogger("messaging.tasks").exception(
            "whatsapp.task_failed message_id=%s",
            message_id,
        )
        return
    if outcome == "retry" and not settings.CELERY_TASK_ALWAYS_EAGER:
        raise self.retry(countdown=30)


@shared_task
def process_due_appointment_reminders() -> dict:
    """Find due durable reminders and queue them. Does not call Meta directly."""
    from messaging.reminders import process_due_appointment_reminders as process_due

    try:
        return process_due()
    except Exception:
        logging.getLogger("messaging.tasks").exception("whatsapp.reminder_task_failed")
        return {"queued": 0, "skipped": 0, "failed": 0, "seen": 0}


@shared_task
def process_due_retention_messages() -> dict:
    """Find due retention messages and queue WhatsApp delivery. Does not call Meta."""
    from customers.retention_automation import process_due_retention_messages as process_due

    try:
        return process_due()
    except Exception:
        logging.getLogger("messaging.tasks").exception("retention.task_failed")
        return {"queued": 0, "skipped": 0, "failed": 0, "seen": 0, "scheduled": 0}
