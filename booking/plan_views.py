from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from booking.models import BookingPlan, BookingPlanStatus
from booking.plan_services import frequency_label, serialize_public_booking_plan
from businesses.services import get_business_for_organization
from core.mixins import TenantContextMixin
from core.pagination import StandardLimitOffsetPagination
from core.permissions import HasOrganizationContext


class BookingPlanListView(TenantContextMixin, APIView):
    """Minimal read of regular bookings for a business (not a CRM)."""

    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        qs = (
            BookingPlan.objects.filter(
                organization=request.organization,
                business=business,
                deleted_at__isnull=True,
            )
            .exclude(status=BookingPlanStatus.CANCELLED)
            .select_related(
                "customer",
                "service",
                "location",
                "staff_profile",
                "business",
            )
            .order_by("next_due_at")
        )
        status_filter = (request.query_params.get("status") or "").strip().upper()
        if status_filter in BookingPlanStatus.values:
            qs = qs.filter(status=status_filter)

        location_id = request.query_params.get("location_id")
        if location_id:
            qs = qs.filter(location_id=location_id)

        paginator = StandardLimitOffsetPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        results = []
        for plan in page:
            public = serialize_public_booking_plan(plan)
            results.append(
                {
                    "customer_name": plan.customer.full_name,
                    "service_name": public["service_name"],
                    "location_name": public["location_name"],
                    "frequency": public["frequency"],
                    "interval": public["interval"],
                    "frequency_label": frequency_label(
                        frequency=plan.frequency,
                        interval=plan.interval,
                    ),
                    "preferred_time": public["preferred_time"],
                    "staff_preference": public["staff_preference"],
                    "staff_name": public["staff_name"],
                    "status": public["status"],
                    "needs_action": public["needs_action"],
                    "next_appointment": public["next_appointment"],
                }
            )
        return paginator.get_paginated_response(results)
