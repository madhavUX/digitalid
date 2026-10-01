from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from businesses.services import get_business_for_organization
from catalog.serializers import (
    ServiceCategoryCreateSerializer,
    ServiceCategorySerializer,
    ServiceCategoryUpdateSerializer,
    ServiceCreateSerializer,
    ServiceLocationCreateSerializer,
    ServiceLocationSerializer,
    ServiceLocationUpdateSerializer,
    ServiceSerializer,
    ServiceUpdateSerializer,
)
from catalog.services import (
    assign_service_location,
    create_service,
    create_service_category,
    get_service_category_for_business,
    get_service_for_business,
    get_service_location,
    list_service_categories,
    list_service_locations,
    list_services,
    remove_service_location,
    soft_delete_service,
    soft_delete_service_category,
    update_service,
    update_service_category,
    update_service_location,
)
from core.mixins import TenantContextMixin
from core.pagination import StandardLimitOffsetPagination
from core.permissions import HasOrganizationContext, IsOrganizationOwner


class _OwnerWriteMixin:
    def get_permissions(self):
        if self.request.method in ("POST", "PATCH", "DELETE", "PUT"):
            return [IsAuthenticated(), HasOrganizationContext(), IsOrganizationOwner()]
        return [IsAuthenticated(), HasOrganizationContext()]


class ServiceCategoryListCreateView(_OwnerWriteMixin, TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        queryset = list_service_categories(
            organization=request.organization,
            business=business,
        )
        queryset = _filter_categories(queryset, request.query_params)
        paginator = StandardLimitOffsetPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(ServiceCategorySerializer(page, many=True).data)

    def post(self, request, business_id):
        get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        serializer = ServiceCategoryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        category = create_service_category(
            organization=request.organization,
            business_id=business_id,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(
            ServiceCategorySerializer(category).data,
            status=status.HTTP_201_CREATED,
        )


class ServiceCategoryDetailView(_OwnerWriteMixin, TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id, category_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        category = get_service_category_for_business(
            organization=request.organization,
            business=business,
            category_id=category_id,
        )
        return Response(ServiceCategorySerializer(category).data)

    def patch(self, request, business_id, category_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        category = get_service_category_for_business(
            organization=request.organization,
            business=business,
            category_id=category_id,
        )
        serializer = ServiceCategoryUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        category = update_service_category(
            category=category,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(ServiceCategorySerializer(category).data)

    def delete(self, request, business_id, category_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        category = get_service_category_for_business(
            organization=request.organization,
            business=business,
            category_id=category_id,
        )
        soft_delete_service_category(category=category, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ServiceListCreateView(_OwnerWriteMixin, TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        queryset = list_services(organization=request.organization, business=business)
        queryset = _filter_services(queryset, request.query_params)
        paginator = StandardLimitOffsetPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(ServiceSerializer(page, many=True).data)

    def post(self, request, business_id):
        get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        serializer = ServiceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = create_service(
            organization=request.organization,
            business_id=business_id,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(ServiceSerializer(service).data, status=status.HTTP_201_CREATED)


class ServiceDetailView(_OwnerWriteMixin, TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id, service_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        service = get_service_for_business(
            organization=request.organization,
            business=business,
            service_id=service_id,
        )
        return Response(ServiceSerializer(service).data)

    def patch(self, request, business_id, service_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        service = get_service_for_business(
            organization=request.organization,
            business=business,
            service_id=service_id,
        )
        serializer = ServiceUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        service = update_service(
            service=service,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(ServiceSerializer(service).data)

    def delete(self, request, business_id, service_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        service = get_service_for_business(
            organization=request.organization,
            business=business,
            service_id=service_id,
        )
        soft_delete_service(service=service, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ServiceLocationListCreateView(_OwnerWriteMixin, TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id, service_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        service = get_service_for_business(
            organization=request.organization,
            business=business,
            service_id=service_id,
        )
        queryset = list_service_locations(
            organization=request.organization,
            service=service,
        )
        paginator = StandardLimitOffsetPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(ServiceLocationSerializer(page, many=True).data)

    def post(self, request, business_id, service_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        service = get_service_for_business(
            organization=request.organization,
            business=business,
            service_id=service_id,
        )
        serializer = ServiceLocationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assignment = assign_service_location(
            organization=request.organization,
            business=business,
            service=service,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(
            ServiceLocationSerializer(assignment).data,
            status=status.HTTP_201_CREATED,
        )


class ServiceLocationDetailView(_OwnerWriteMixin, TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id, service_id, service_location_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        service = get_service_for_business(
            organization=request.organization,
            business=business,
            service_id=service_id,
        )
        assignment = get_service_location(
            organization=request.organization,
            service=service,
            service_location_id=service_location_id,
        )
        return Response(ServiceLocationSerializer(assignment).data)

    def patch(self, request, business_id, service_id, service_location_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        service = get_service_for_business(
            organization=request.organization,
            business=business,
            service_id=service_id,
        )
        assignment = get_service_location(
            organization=request.organization,
            service=service,
            service_location_id=service_location_id,
        )
        serializer = ServiceLocationUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        assignment = update_service_location(
            service_location=assignment,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(ServiceLocationSerializer(assignment).data)

    def delete(self, request, business_id, service_id, service_location_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        service = get_service_for_business(
            organization=request.organization,
            business=business,
            service_id=service_id,
        )
        assignment = get_service_location(
            organization=request.organization,
            service=service,
            service_location_id=service_location_id,
        )
        remove_service_location(service_location=assignment)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _filter_categories(queryset, params):
    search = params.get("search")
    if search:
        queryset = queryset.filter(Q(name__icontains=search) | Q(slug__icontains=search))

    ordering = params.get("ordering", "display_order")
    allowed = {
        "display_order",
        "-display_order",
        "name",
        "-name",
        "created_at",
        "-created_at",
    }
    if ordering in allowed:
        queryset = queryset.order_by(ordering)
    return queryset


def _filter_services(queryset, params):
    is_active = params.get("is_active")
    if is_active is not None:
        value = is_active.lower()
        if value in ("true", "1"):
            queryset = queryset.filter(is_active=True)
        elif value in ("false", "0"):
            queryset = queryset.filter(is_active=False)

    is_bookable = params.get("is_bookable_online")
    if is_bookable is not None:
        value = is_bookable.lower()
        if value in ("true", "1"):
            queryset = queryset.filter(is_bookable_online=True)
        elif value in ("false", "0"):
            queryset = queryset.filter(is_bookable_online=False)

    category_id = params.get("category_id")
    if category_id:
        queryset = queryset.filter(category_id=category_id)

    search = params.get("search")
    if search:
        queryset = queryset.filter(Q(name__icontains=search) | Q(slug__icontains=search))

    ordering = params.get("ordering", "name")
    allowed = {"name", "-name", "created_at", "-created_at", "price", "-price"}
    if ordering in allowed:
        queryset = queryset.order_by(ordering)
    return queryset
