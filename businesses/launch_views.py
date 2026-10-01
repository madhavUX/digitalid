from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from businesses.launch_serializers import LaunchProfileWriteSerializer
from businesses.launch_services import (
    get_business_launch_status,
    get_or_create_launch_profile,
    serialize_launch_profile,
    update_launch_profile,
)
from businesses.services import get_business_for_organization
from businesses.setup_services import resolve_dashboard_location
from core.mixins import TenantContextMixin
from core.permissions import (
    HasOrganizationContext,
    IsOrganizationManagerOrAbove,
    IsOrganizationOwner,
)


class BusinessLaunchProfileView(TenantContextMixin, APIView):
    permission_classes = [
        IsAuthenticated,
        HasOrganizationContext,
        IsOrganizationManagerOrAbove,
    ]

    def get(self, request, business_id):
        location_id = request.query_params.get("location_id") or None
        payload = get_business_launch_status(
            organization=request.organization,
            business_id=business_id,
            location_id=location_id,
        )
        return Response(payload)

    def post(self, request, business_id):
        serializer = LaunchProfileWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _reject_manager_review_url_write(request)
        data = dict(serializer.validated_data)
        location_id = data.pop("location_id", None) or request.query_params.get("location_id")
        if not location_id:
            business = get_business_for_organization(
                organization=request.organization,
                business_id=business_id,
            )
            location = resolve_dashboard_location(
                organization=request.organization,
                business=business,
                location_id=None,
            )
            location_id = location.id

        profile = get_or_create_launch_profile(
            organization=request.organization,
            business_id=business_id,
            location_id=location_id,
            actor=request.user,
        )
        if data:
            profile = update_launch_profile(
                organization=request.organization,
                business_id=business_id,
                location_id=location_id,
                actor=request.user,
                data=data,
            )
        status_payload = get_business_launch_status(
            organization=request.organization,
            business_id=business_id,
            location_id=location_id,
        )
        return Response(
            {
                "profile": serialize_launch_profile(profile),
                "launch": status_payload,
            },
            status=status.HTTP_201_CREATED,
        )

    def patch(self, request, business_id):
        serializer = LaunchProfileWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _reject_manager_review_url_write(request)
        data = dict(serializer.validated_data)
        location_id = data.pop("location_id", None) or request.query_params.get("location_id")
        if not location_id:
            business = get_business_for_organization(
                organization=request.organization,
                business_id=business_id,
            )
            location = resolve_dashboard_location(
                organization=request.organization,
                business=business,
                location_id=None,
            )
            location_id = location.id

        profile = update_launch_profile(
            organization=request.organization,
            business_id=business_id,
            location_id=location_id,
            actor=request.user,
            data=data,
        )
        status_payload = get_business_launch_status(
            organization=request.organization,
            business_id=business_id,
            location_id=location_id,
        )
        return Response(
            {
                "profile": serialize_launch_profile(profile),
                "launch": status_payload,
            }
        )


def _reject_manager_review_url_write(request) -> None:
    if "google_review_url" not in request.data:
        return
    if not IsOrganizationOwner().has_permission(request, None):
        raise PermissionDenied("Only the owner can set the Google review URL.")
