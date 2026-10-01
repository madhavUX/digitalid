from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from businesses.services import get_business_for_organization
from core.mixins import TenantContextMixin
from core.pagination import StandardLimitOffsetPagination
from core.permissions import (
    HasOrganizationContext,
    IsOrganizationManagerOrAbove,
    IsOrganizationOwner,
)
from customers.serializers import (
    CustomerCreateSerializer,
    CustomerRetentionSettingsUpdateSerializer,
    CustomerSerializer,
    CustomerTagAssignmentSerializer,
    CustomerTagAssignSerializer,
    CustomerTagCreateSerializer,
    CustomerTagSerializer,
    CustomerTagUpdateSerializer,
    CustomerUpdateSerializer,
)
from customers.services import (
    assign_customer_tag,
    create_customer,
    create_customer_tag,
    delete_customer_tag,
    filter_customers_by_segment,
    get_customer_for_business,
    get_customer_tag_assignment,
    get_customer_tag_for_business,
    get_or_create_retention_settings,
    list_customer_tag_assignments,
    list_customer_tags,
    list_customers,
    remove_customer_tag_assignment,
    serialize_retention_settings,
    soft_delete_customer,
    update_customer,
    update_customer_tag,
    update_retention_settings,
)


class _ManagerWriteMixin:
    def get_permissions(self):
        if self.request.method in ("POST", "PATCH", "DELETE", "PUT"):
            return [
                IsAuthenticated(),
                HasOrganizationContext(),
                IsOrganizationManagerOrAbove(),
            ]
        return [IsAuthenticated(), HasOrganizationContext()]


class CustomerListCreateView(_ManagerWriteMixin, TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        queryset = list_customers(
            organization=request.organization,
            business=business,
        )
        queryset = _filter_customers(
            queryset,
            request.query_params,
            organization=request.organization,
            business=business,
        )
        paginator = StandardLimitOffsetPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(CustomerSerializer(page, many=True).data)

    def post(self, request, business_id):
        get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        serializer = CustomerCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = create_customer(
            organization=request.organization,
            business_id=business_id,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(
            CustomerSerializer(customer).data,
            status=status.HTTP_201_CREATED,
        )


class CustomerDetailView(_ManagerWriteMixin, TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id, customer_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        customer = get_customer_for_business(
            organization=request.organization,
            business=business,
            customer_id=customer_id,
        )
        return Response(CustomerSerializer(customer).data)

    def patch(self, request, business_id, customer_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        customer = get_customer_for_business(
            organization=request.organization,
            business=business,
            customer_id=customer_id,
        )
        serializer = CustomerUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        customer = update_customer(
            customer=customer,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(CustomerSerializer(customer).data)

    def delete(self, request, business_id, customer_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        customer = get_customer_for_business(
            organization=request.organization,
            business=business,
            customer_id=customer_id,
        )
        soft_delete_customer(customer=customer, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CustomerRetentionSummaryView(TenantContextMixin, APIView):
    """Factual retention profile. Same auth as customer GET (OWNER/MANAGER/STAFF)."""

    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id, customer_id):
        from customers.services import get_customer_retention_summary

        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        customer = get_customer_for_business(
            organization=request.organization,
            business=business,
            customer_id=customer_id,
        )
        return Response(get_customer_retention_summary(customer=customer))


class CustomerRetentionSettingsView(TenantContextMixin, APIView):
    """Business retention thresholds. GET: any member; PATCH: OWNER only."""

    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get_permissions(self):
        if self.request.method in ("PATCH", "PUT"):
            return [IsAuthenticated(), HasOrganizationContext(), IsOrganizationOwner()]
        return [
            IsAuthenticated(),
            HasOrganizationContext(),
            IsOrganizationManagerOrAbove(),
        ]

    def get(self, request, business_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        settings = get_or_create_retention_settings(
            organization=request.organization,
            business=business,
            actor=request.user,
        )
        return Response(serialize_retention_settings(settings))

    def patch(self, request, business_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        settings = get_or_create_retention_settings(
            organization=request.organization,
            business=business,
            actor=request.user,
        )
        serializer = CustomerRetentionSettingsUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        settings = update_retention_settings(
            settings=settings,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(serialize_retention_settings(settings))


class CustomerTagListCreateView(_ManagerWriteMixin, TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        queryset = list_customer_tags(
            organization=request.organization,
            business=business,
        )
        queryset = _filter_tags(queryset, request.query_params)
        paginator = StandardLimitOffsetPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(CustomerTagSerializer(page, many=True).data)

    def post(self, request, business_id):
        get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        serializer = CustomerTagCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tag = create_customer_tag(
            organization=request.organization,
            business_id=business_id,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(CustomerTagSerializer(tag).data, status=status.HTTP_201_CREATED)


class CustomerTagDetailView(_ManagerWriteMixin, TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id, tag_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        tag = get_customer_tag_for_business(
            organization=request.organization,
            business=business,
            tag_id=tag_id,
        )
        return Response(CustomerTagSerializer(tag).data)

    def patch(self, request, business_id, tag_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        tag = get_customer_tag_for_business(
            organization=request.organization,
            business=business,
            tag_id=tag_id,
        )
        serializer = CustomerTagUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        tag = update_customer_tag(tag=tag, actor=request.user, **serializer.validated_data)
        return Response(CustomerTagSerializer(tag).data)

    def delete(self, request, business_id, tag_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        tag = get_customer_tag_for_business(
            organization=request.organization,
            business=business,
            tag_id=tag_id,
        )
        delete_customer_tag(tag=tag)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CustomerTagAssignmentListCreateView(_ManagerWriteMixin, TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id, customer_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        customer = get_customer_for_business(
            organization=request.organization,
            business=business,
            customer_id=customer_id,
        )
        queryset = list_customer_tag_assignments(
            organization=request.organization,
            customer=customer,
        )
        paginator = StandardLimitOffsetPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(
            CustomerTagAssignmentSerializer(page, many=True).data
        )

    def post(self, request, business_id, customer_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        customer = get_customer_for_business(
            organization=request.organization,
            business=business,
            customer_id=customer_id,
        )
        serializer = CustomerTagAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assignment = assign_customer_tag(
            organization=request.organization,
            business=business,
            customer=customer,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(
            CustomerTagAssignmentSerializer(assignment).data,
            status=status.HTTP_201_CREATED,
        )


class CustomerTagAssignmentDetailView(_ManagerWriteMixin, TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id, customer_id, assignment_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        customer = get_customer_for_business(
            organization=request.organization,
            business=business,
            customer_id=customer_id,
        )
        assignment = get_customer_tag_assignment(
            organization=request.organization,
            customer=customer,
            assignment_id=assignment_id,
        )
        return Response(CustomerTagAssignmentSerializer(assignment).data)

    def delete(self, request, business_id, customer_id, assignment_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        customer = get_customer_for_business(
            organization=request.organization,
            business=business,
            customer_id=customer_id,
        )
        assignment = get_customer_tag_assignment(
            organization=request.organization,
            customer=customer,
            assignment_id=assignment_id,
        )
        remove_customer_tag_assignment(assignment=assignment)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _filter_customers(queryset, params, *, organization=None, business=None):
    search = params.get("search")
    if search:
        queryset = queryset.filter(
            Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(phone__icontains=search)
            | Q(email__icontains=search)
        )

    tag_id = params.get("tag_id")
    if tag_id:
        queryset = queryset.filter(tag_assignments__tag_id=tag_id).distinct()

    segment = (params.get("segment") or "").strip().upper()
    if segment:
        from customers.models import RetentionSegment

        if segment not in RetentionSegment.values:
            return queryset.none()
        settings = get_or_create_retention_settings(
            organization=organization,
            business=business,
        )
        queryset = filter_customers_by_segment(
            queryset=queryset,
            segment=segment,
            settings=settings,
        )

    ordering = params.get("ordering", "last_name")
    allowed = {
        "last_name",
        "-last_name",
        "first_name",
        "-first_name",
        "created_at",
        "-created_at",
        "last_visit_at",
        "-last_visit_at",
        "phone",
        "-phone",
    }
    if ordering in allowed:
        queryset = queryset.order_by(ordering)
    return queryset


def _filter_tags(queryset, params):
    search = params.get("search")
    if search:
        queryset = queryset.filter(name__icontains=search)

    ordering = params.get("ordering", "name")
    allowed = {"name", "-name", "created_at", "-created_at"}
    if ordering in allowed:
        queryset = queryset.order_by(ordering)
    return queryset
