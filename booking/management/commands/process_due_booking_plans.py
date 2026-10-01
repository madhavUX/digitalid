from django.core.management.base import BaseCommand
from django.utils import timezone

from booking.plan_services import process_due_booking_plans


class Command(BaseCommand):
    help = (
        "Process due Book Regularly plans: create the next Appointment only when "
        "the preferred slot is available. Does not create subscriptions or payments. "
        "Example cron: */15 * * * * python manage.py process_due_booking_plans"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Max plans to process in this run (default 100).",
        )

    def handle(self, *args, **options):
        result = process_due_booking_plans(
            now=timezone.now(),
            limit=options["limit"],
        )
        self.stdout.write(
            f"Processed: {result.processed}\n"
            f"Created: {result.created}\n"
            f"Skipped: {result.skipped}\n"
            f"Failed: {result.failed}"
        )
