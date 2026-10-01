from django.core.management.base import BaseCommand

from messaging.reminders import process_due_appointment_reminders


class Command(BaseCommand):
    help = "Queue due business WhatsApp appointment reminders."

    def handle(self, *args, **options):
        result = process_due_appointment_reminders()
        self.stdout.write(
            "Reminders seen={seen} queued={queued} skipped={skipped} failed={failed}".format(
                **result
            )
        )
