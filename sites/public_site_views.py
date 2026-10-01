from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from businesses.services import get_business_for_organization
from businesses.setup_services import resolve_dashboard_location
from core.mixins import TenantContextMixin
from core.permissions import HasOrganizationContext, IsOrganizationManagerOrAbove
from sites.provisioning_services import (
    get_website_status,
    publish_website,
    unpublish_website,
)
from sites.public_site_services import get_preview_site_for_business, get_public_site_by_slug


def _resolve_location_id(request, business_id):
    location_id = request.query_params.get("location_id")
    if not location_id and hasattr(request, "data"):
        location_id = request.data.get("location_id")
    if location_id:
        return str(location_id)
    business = get_business_for_organization(
        organization=request.organization,
        business_id=business_id,
    )
    location = resolve_dashboard_location(
        organization=request.organization,
        business=business,
        location_id=None,
    )
    return str(location.id)


class PublicSiteDetailView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, slug):
        payload = get_public_site_by_slug(slug)
        response = Response(payload)
        response["Cache-Control"] = "public, max-age=60"
        return response


class BusinessWebsitePreviewView(TenantContextMixin, APIView):
    permission_classes = [
        IsAuthenticated,
        HasOrganizationContext,
        IsOrganizationManagerOrAbove,
    ]

    def get(self, request, business_id):
        location_id = _resolve_location_id(request, business_id)
        payload = get_preview_site_for_business(
            organization=request.organization,
            business_id=business_id,
            location_id=location_id,
        )
        return Response(payload)


class BusinessWebsiteStatusView(TenantContextMixin, APIView):
    permission_classes = [
        IsAuthenticated,
        HasOrganizationContext,
        IsOrganizationManagerOrAbove,
    ]

    def get(self, request, business_id):
        location_id = _resolve_location_id(request, business_id)
        return Response(
            get_website_status(
                organization=request.organization,
                business_id=business_id,
                location_id=location_id,
            )
        )


class BusinessWebsitePublishView(TenantContextMixin, APIView):
    permission_classes = [
        IsAuthenticated,
        HasOrganizationContext,
        IsOrganizationManagerOrAbove,
    ]

    def post(self, request, business_id):
        location_id = _resolve_location_id(request, business_id)
        payload = publish_website(
            organization=request.organization,
            business_id=business_id,
            location_id=location_id,
            actor=request.user,
        )
        return Response(payload, status=status.HTTP_200_OK)


class BusinessWebsiteUnpublishView(TenantContextMixin, APIView):
    permission_classes = [
        IsAuthenticated,
        HasOrganizationContext,
        IsOrganizationManagerOrAbove,
    ]

    def post(self, request, business_id):
        location_id = _resolve_location_id(request, business_id)
        payload = unpublish_website(
            organization=request.organization,
            business_id=business_id,
            location_id=location_id,
            actor=request.user,
        )
        return Response(payload, status=status.HTTP_200_OK)
