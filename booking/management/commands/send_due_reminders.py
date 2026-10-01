from django.core.management.base import BaseCommand
from django.utils import timezone

from booking.reminders import process_due_reminders


class Command(BaseCommand):
    help = (
        "Send due WhatsApp appointment reminders (24h / 1h). "
        "Safe to run repeatedly; idempotent per appointment + reminder type."
    )

    def handle(self, *args, **options):
        result = process_due_reminders(now=timezone.now())
        self.stdout.write(
            f"Processed: {result.processed}\n"
            f"Sent: {result.sent}\n"
            f"Skipped: {result.skipped}\n"
            f"Failed: {result.failed}"
        )
