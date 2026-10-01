from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from businesses.setup_services import get_business_dashboard, get_business_setup_status
from core.mixins import TenantContextMixin
from core.permissions import HasOrganizationContext, IsOrganizationManagerOrAbove


class BusinessSetupStatusView(TenantContextMixin, APIView):
    permission_classes = [
        IsAuthenticated,
        HasOrganizationContext,
        IsOrganizationManagerOrAbove,
    ]

    def get(self, request, business_id):
        location_id = request.query_params.get("location_id") or None
        payload = get_business_setup_status(
            organization=request.organization,
            business_id=business_id,
            location_id=location_id,
        )
        return Response(payload)


class BusinessDashboardView(TenantContextMixin, APIView):
    permission_classes = [
        IsAuthenticated,
        HasOrganizationContext,
        IsOrganizationManagerOrAbove,
    ]

    def get(self, request, business_id):
        location_id = request.query_params.get("location_id") or None
        payload = get_business_dashboard(
            organization=request.organization,
            business_id=business_id,
            location_id=location_id,
        )
        return Response(payload)
