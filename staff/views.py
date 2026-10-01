from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from businesses.services import get_business_for_organization
from core.mixins import TenantContextMixin
from core.pagination import StandardLimitOffsetPagination
from core.permissions import HasOrganizationContext, IsOrganizationManagerOrAbove
from staff.serializers import (
    StaffAvailabilityCreateSerializer,
    StaffAvailabilitySerializer,
    StaffAvailabilityUpdateSerializer,
    StaffProfileCreateSerializer,
    StaffProfileSerializer,
    StaffProfileUpdateSerializer,
    StaffServiceCreateSerializer,
    StaffServiceSerializer,
    StaffServiceUpdateSerializer,
    StaffTimeOffCreateSerializer,
    StaffTimeOffSerializer,
    StaffTimeOffUpdateSerializer,
)
from staff.services import (
    assign_staff_service,
    create_staff_availability,
    create_staff_profile,
    create_staff_time_off,
    delete_staff_availability,
    delete_staff_time_off,
    get_staff_availability,
    get_staff_profile_for_business,
    get_staff_service,
    get_staff_time_off,
    list_staff_availabilities,
    list_staff_profiles,
    list_staff_services,
    list_staff_time_offs,
    remove_staff_service,
    soft_delete_staff_profile,
    update_staff_availability,
    update_staff_profile,
    update_staff_service,
    update_staff_time_off,
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


class StaffProfileListCreateView(_ManagerWriteMixin, TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        queryset = list_staff_profiles(
            organization=request.organization,
            business=business,
        )
        queryset = _filter_staff(queryset, request.query_params)
        paginator = StandardLimitOffsetPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(StaffProfileSerializer(page, many=True).data)

    def post(self, request, business_id):
        get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        serializer = StaffProfileCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = create_staff_profile(
            organization=request.organization,
            business_id=business_id,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(
            StaffProfileSerializer(profile).data,
            status=status.HTTP_201_CREATED,
        )


class StaffProfileDetailView(_ManagerWriteMixin, TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id, staff_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        profile = get_staff_profile_for_business(
            organization=request.organization,
            business=business,
            staff_id=staff_id,
        )
        return Response(StaffProfileSerializer(profile).data)

    def patch(self, request, business_id, staff_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        profile = get_staff_profile_for_business(
            organization=request.organization,
            business=business,
            staff_id=staff_id,
        )
        serializer = StaffProfileUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        profile = update_staff_profile(
            staff_profile=profile,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(StaffProfileSerializer(profile).data)

    def delete(self, request, business_id, staff_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        profile = get_staff_profile_for_business(
            organization=request.organization,
            business=business,
            staff_id=staff_id,
        )
        soft_delete_staff_profile(staff_profile=profile, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class StaffServiceListCreateView(_ManagerWriteMixin, TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id, staff_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        profile = get_staff_profile_for_business(
            organization=request.organization,
            business=business,
            staff_id=staff_id,
        )
        queryset = list_staff_services(
            organization=request.organization,
            staff_profile=profile,
        )
        paginator = StandardLimitOffsetPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(StaffServiceSerializer(page, many=True).data)

    def post(self, request, business_id, staff_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        profile = get_staff_profile_for_business(
            organization=request.organization,
            business=business,
            staff_id=staff_id,
        )
        serializer = StaffServiceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assignment = assign_staff_service(
            organization=request.organization,
            business=business,
            staff_profile=profile,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(
            StaffServiceSerializer(assignment).data,
            status=status.HTTP_201_CREATED,
        )


class StaffServiceDetailView(_ManagerWriteMixin, TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id, staff_id, staff_service_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        profile = get_staff_profile_for_business(
            organization=request.organization,
            business=business,
            staff_id=staff_id,
        )
        assignment = get_staff_service(
            organization=request.organization,
            staff_profile=profile,
            staff_service_id=staff_service_id,
        )
        return Response(StaffServiceSerializer(assignment).data)

    def patch(self, request, business_id, staff_id, staff_service_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        profile = get_staff_profile_for_business(
            organization=request.organization,
            business=business,
            staff_id=staff_id,
        )
        assignment = get_staff_service(
            organization=request.organization,
            staff_profile=profile,
            staff_service_id=staff_service_id,
        )
        serializer = StaffServiceUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        assignment = update_staff_service(
            staff_service=assignment,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(StaffServiceSerializer(assignment).data)

    def delete(self, request, business_id, staff_id, staff_service_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        profile = get_staff_profile_for_business(
            organization=request.organization,
            business=business,
            staff_id=staff_id,
        )
        assignment = get_staff_service(
            organization=request.organization,
            staff_profile=profile,
            staff_service_id=staff_service_id,
        )
        remove_staff_service(staff_service=assignment)
        return Response(status=status.HTTP_204_NO_CONTENT)


class StaffAvailabilityListCreateView(_ManagerWriteMixin, TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id, staff_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        profile = get_staff_profile_for_business(
            organization=request.organization,
            business=business,
            staff_id=staff_id,
        )
        queryset = list_staff_availabilities(
            organization=request.organization,
            staff_profile=profile,
        )
        queryset = _filter_availability(queryset, request.query_params)
        paginator = StandardLimitOffsetPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(StaffAvailabilitySerializer(page, many=True).data)

    def post(self, request, business_id, staff_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        profile = get_staff_profile_for_business(
            organization=request.organization,
            business=business,
            staff_id=staff_id,
        )
        serializer = StaffAvailabilityCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        availability = create_staff_availability(
            organization=request.organization,
            business=business,
            staff_profile=profile,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(
            StaffAvailabilitySerializer(availability).data,
            status=status.HTTP_201_CREATED,
        )


class StaffAvailabilityDetailView(_ManagerWriteMixin, TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id, staff_id, availability_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        profile = get_staff_profile_for_business(
            organization=request.organization,
            business=business,
            staff_id=staff_id,
        )
        availability = get_staff_availability(
            organization=request.organization,
            staff_profile=profile,
            availability_id=availability_id,
        )
        return Response(StaffAvailabilitySerializer(availability).data)

    def patch(self, request, business_id, staff_id, availability_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        profile = get_staff_profile_for_business(
            organization=request.organization,
            business=business,
            staff_id=staff_id,
        )
        availability = get_staff_availability(
            organization=request.organization,
            staff_profile=profile,
            availability_id=availability_id,
        )
        serializer = StaffAvailabilityUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        availability = update_staff_availability(
            availability=availability,
            actor=request.user,
            business=business,
            **serializer.validated_data,
        )
        return Response(StaffAvailabilitySerializer(availability).data)

    def delete(self, request, business_id, staff_id, availability_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        profile = get_staff_profile_for_business(
            organization=request.organization,
            business=business,
            staff_id=staff_id,
        )
        availability = get_staff_availability(
            organization=request.organization,
            staff_profile=profile,
            availability_id=availability_id,
        )
        delete_staff_availability(availability=availability)
        return Response(status=status.HTTP_204_NO_CONTENT)


class StaffTimeOffListCreateView(_ManagerWriteMixin, TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id, staff_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        profile = get_staff_profile_for_business(
            organization=request.organization,
            business=business,
            staff_id=staff_id,
        )
        queryset = list_staff_time_offs(
            organization=request.organization,
            staff_profile=profile,
        )
        queryset = _filter_time_off(queryset, request.query_params)
        paginator = StandardLimitOffsetPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(StaffTimeOffSerializer(page, many=True).data)

    def post(self, request, business_id, staff_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        profile = get_staff_profile_for_business(
            organization=request.organization,
            business=business,
            staff_id=staff_id,
        )
        serializer = StaffTimeOffCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        time_off = create_staff_time_off(
            organization=request.organization,
            staff_profile=profile,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(StaffTimeOffSerializer(time_off).data, status=status.HTTP_201_CREATED)


class StaffTimeOffDetailView(_ManagerWriteMixin, TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id, staff_id, time_off_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        profile = get_staff_profile_for_business(
            organization=request.organization,
            business=business,
            staff_id=staff_id,
        )
        time_off = get_staff_time_off(
            organization=request.organization,
            staff_profile=profile,
            time_off_id=time_off_id,
        )
        return Response(StaffTimeOffSerializer(time_off).data)

    def patch(self, request, business_id, staff_id, time_off_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        profile = get_staff_profile_for_business(
            organization=request.organization,
            business=business,
            staff_id=staff_id,
        )
        time_off = get_staff_time_off(
            organization=request.organization,
            staff_profile=profile,
            time_off_id=time_off_id,
        )
        serializer = StaffTimeOffUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        time_off = update_staff_time_off(
            time_off=time_off,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(StaffTimeOffSerializer(time_off).data)

    def delete(self, request, business_id, staff_id, time_off_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        profile = get_staff_profile_for_business(
            organization=request.organization,
            business=business,
            staff_id=staff_id,
        )
        time_off = get_staff_time_off(
            organization=request.organization,
            staff_profile=profile,
            time_off_id=time_off_id,
        )
        delete_staff_time_off(time_off=time_off)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _filter_availability(queryset, params):
    weekday = params.get("weekday")
    if weekday is not None and weekday != "":
        try:
            queryset = queryset.filter(weekday=int(weekday))
        except ValueError:
            pass

    location_id = params.get("location_id")
    if location_id:
        queryset = queryset.filter(location_id=location_id)

    ordering = params.get("ordering", "weekday")
    allowed = {
        "weekday",
        "-weekday",
        "starts_at",
        "-starts_at",
        "created_at",
        "-created_at",
    }
    if ordering in allowed:
        queryset = queryset.order_by(ordering)
    return queryset


def _filter_time_off(queryset, params):
    ordering = params.get("ordering", "-starts_at")
    allowed = {"starts_at", "-starts_at", "ends_at", "-ends_at", "created_at", "-created_at"}
    if ordering in allowed:
        queryset = queryset.order_by(ordering)
    return queryset


def _filter_staff(queryset, params):
    is_active = params.get("is_active")
    if is_active is not None:
        value = is_active.lower()
        if value in ("true", "1"):
            queryset = queryset.filter(is_active=True)
        elif value in ("false", "0"):
            queryset = queryset.filter(is_active=False)

    is_bookable = params.get("is_bookable")
    if is_bookable is not None:
        value = is_bookable.lower()
        if value in ("true", "1"):
            queryset = queryset.filter(is_bookable=True)
        elif value in ("false", "0"):
            queryset = queryset.filter(is_bookable=False)

    location_id = params.get("location_id")
    if location_id:
        queryset = queryset.filter(location_id=location_id)

    search = params.get("search")
    if search:
        queryset = queryset.filter(Q(display_name__icontains=search) | Q(title__icontains=search))

    ordering = params.get("ordering", "display_name")
    allowed = {
        "display_name",
        "-display_name",
        "created_at",
        "-created_at",
        "title",
        "-title",
    }
    if ordering in allowed:
        queryset = queryset.order_by(ordering)
    return queryset
