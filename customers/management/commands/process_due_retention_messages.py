from django.core.management.base import BaseCommand

from customers.retention_automation import process_due_retention_messages


class Command(BaseCommand):
    help = (
        "Process due CustomerRetentionMessage rows and queue WhatsApp delivery. "
        "Safe to run repeatedly. Does not send when eligibility fails."
    )

    def handle(self, *args, **options):
        result = process_due_retention_messages()
        self.stdout.write(f"Seen: {result['seen']}")
        self.stdout.write(f"Queued: {result['queued']}")
        self.stdout.write(f"Skipped: {result['skipped']}")
        self.stdout.write(f"Failed: {result['failed']}")
        self.stdout.write(f"Scheduled: {result['scheduled']}")
