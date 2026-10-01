from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from businesses.serializers import (
    BusinessCreateSerializer,
    BusinessSerializer,
    BusinessUpdateSerializer,
)
from businesses.services import (
    create_business,
    get_business_for_organization,
    list_businesses,
    soft_delete_business,
    update_business,
)
from core.mixins import TenantContextMixin
from core.pagination import StandardLimitOffsetPagination
from core.permissions import HasOrganizationContext, IsOrganizationOwner


class BusinessListCreateView(TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), HasOrganizationContext(), IsOrganizationOwner()]
        return [IsAuthenticated(), HasOrganizationContext()]

    def get(self, request):
        queryset = list_businesses(organization=request.organization)
        queryset = _filter_businesses(queryset, request.query_params)
        paginator = StandardLimitOffsetPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = BusinessSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        serializer = BusinessCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Ignore any client-supplied organization_id / tenant_id.
        business = create_business(
            organization=request.organization,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(BusinessSerializer(business).data, status=status.HTTP_201_CREATED)


class BusinessDetailView(TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get_permissions(self):
        if self.request.method in ("PATCH", "DELETE"):
            return [IsAuthenticated(), HasOrganizationContext(), IsOrganizationOwner()]
        return [IsAuthenticated(), HasOrganizationContext()]

    def get(self, request, business_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        return Response(BusinessSerializer(business).data)

    def patch(self, request, business_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        serializer = BusinessUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        business = update_business(
            business=business,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(BusinessSerializer(business).data)

    def delete(self, request, business_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        soft_delete_business(business=business, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _filter_businesses(queryset, params):
    vertical = params.get("vertical")
    if vertical:
        queryset = queryset.filter(vertical=vertical)

    is_active = params.get("is_active")
    if is_active is not None:
        value = is_active.lower()
        if value in ("true", "1"):
            queryset = queryset.filter(is_active=True)
        elif value in ("false", "0"):
            queryset = queryset.filter(is_active=False)

    search = params.get("search")
    if search:
        queryset = queryset.filter(Q(name__icontains=search) | Q(slug__icontains=search))

    ordering = params.get("ordering", "name")
    allowed = {"name", "-name", "created_at", "-created_at", "updated_at", "-updated_at"}
    if ordering in allowed:
        queryset = queryset.order_by(ordering)

    return queryset
