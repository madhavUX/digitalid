from django.core.management.base import BaseCommand

from customers.services import reconcile_customer_visit_totals


class Command(BaseCommand):
    help = (
        "Recalculate Customer total_visits, first_visit_at, and last_visit_at "
        "from live COMPLETED appointments. Safe to run repeatedly. "
        "Does not send messages or create appointments."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--organization-id",
            dest="organization_id",
            default=None,
            help="Limit to one organization UUID.",
        )
        parser.add_argument(
            "--business-id",
            dest="business_id",
            default=None,
            help="Limit to one business UUID.",
        )

    def handle(self, *args, **options):
        result = reconcile_customer_visit_totals(
            organization_id=options["organization_id"],
            business_id=options["business_id"],
        )
        self.stdout.write(f"Customers processed: {result['processed']}")
        self.stdout.write(f"Customers updated: {result['updated']}")
