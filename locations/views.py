from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from businesses.services import get_business_for_organization
from core.mixins import TenantContextMixin
from core.pagination import StandardLimitOffsetPagination
from core.permissions import HasOrganizationContext, IsOrganizationOwner
from locations.serializers import (
    LocationCreateSerializer,
    LocationSerializer,
    LocationUpdateSerializer,
)
from locations.services import (
    create_location,
    get_location_for_business,
    list_locations,
    soft_delete_location,
    update_location,
)


class LocationListCreateView(TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), HasOrganizationContext(), IsOrganizationOwner()]
        return [IsAuthenticated(), HasOrganizationContext()]

    def get(self, request, business_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        queryset = list_locations(organization=request.organization, business=business)
        queryset = _filter_locations(queryset, request.query_params)
        paginator = StandardLimitOffsetPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = LocationSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request, business_id):
        # Validate business belongs to resolved tenant before create.
        get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        serializer = LocationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        location = create_location(
            organization=request.organization,
            business_id=business_id,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(LocationSerializer(location).data, status=status.HTTP_201_CREATED)


class LocationDetailView(TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get_permissions(self):
        if self.request.method in ("PATCH", "DELETE"):
            return [IsAuthenticated(), HasOrganizationContext(), IsOrganizationOwner()]
        return [IsAuthenticated(), HasOrganizationContext()]

    def get(self, request, business_id, location_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        location = get_location_for_business(
            organization=request.organization,
            business=business,
            location_id=location_id,
        )
        return Response(LocationSerializer(location).data)

    def patch(self, request, business_id, location_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        location = get_location_for_business(
            organization=request.organization,
            business=business,
            location_id=location_id,
        )
        serializer = LocationUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        location = update_location(
            location=location,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(LocationSerializer(location).data)

    def delete(self, request, business_id, location_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        location = get_location_for_business(
            organization=request.organization,
            business=business,
            location_id=location_id,
        )
        soft_delete_location(location=location, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _filter_locations(queryset, params):
    is_active = params.get("is_active")
    if is_active is not None:
        value = is_active.lower()
        if value in ("true", "1"):
            queryset = queryset.filter(is_active=True)
        elif value in ("false", "0"):
            queryset = queryset.filter(is_active=False)

    is_primary = params.get("is_primary")
    if is_primary is not None:
        value = is_primary.lower()
        if value in ("true", "1"):
            queryset = queryset.filter(is_primary=True)
        elif value in ("false", "0"):
            queryset = queryset.filter(is_primary=False)

    search = params.get("search")
    if search:
        queryset = queryset.filter(
            Q(name__icontains=search) | Q(city__icontains=search) | Q(slug__icontains=search)
        )

    ordering = params.get("ordering", "name")
    allowed = {"name", "-name", "created_at", "-created_at", "city", "-city"}
    if ordering in allowed:
        queryset = queryset.order_by(ordering)

    return queryset
