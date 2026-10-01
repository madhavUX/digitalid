from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from booking.serializers import (
    AppointmentCancelSerializer,
    AppointmentCreateSerializer,
    AppointmentSerializer,
    AppointmentUpdateSerializer,
    AvailabilityQuerySerializer,
)
from booking.services import (
    cancel_appointment,
    compute_available_slots,
    create_appointment,
    get_appointment_for_business,
    list_appointments,
    update_appointment,
)
from businesses.services import get_business_for_organization
from catalog.services import get_service_for_business
from core.mixins import TenantContextMixin
from core.pagination import StandardLimitOffsetPagination
from core.permissions import HasOrganizationContext, IsOrganizationManagerOrAbove
from locations.services import get_location_for_business


class _ManagerWriteMixin:
    def get_permissions(self):
        if self.request.method in ("POST", "PATCH", "DELETE", "PUT"):
            return [
                IsAuthenticated(),
                HasOrganizationContext(),
                IsOrganizationManagerOrAbove(),
            ]
        return [IsAuthenticated(), HasOrganizationContext()]


class LocationAvailabilityView(_ManagerWriteMixin, TenantContextMixin, APIView):
    """GET availability — read allowed for all members; writes N/A."""

    permission_classes = [IsAuthenticated, HasOrganizationContext]

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
        query = AvailabilityQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        service = get_service_for_business(
            organization=request.organization,
            business=business,
            service_id=query.validated_data["service_id"],
        )
        slots = compute_available_slots(
            organization=request.organization,
            business=business,
            location=location,
            service=service,
            local_day=query.validated_data["date"],
            staff_id=query.validated_data.get("staff_id"),
        )
        payload = []
        for slot in slots:
            payload.append(
                {
                    "starts_at": slot["starts_at"].isoformat().replace("+00:00", "Z"),
                    "ends_at": slot["ends_at"].isoformat().replace("+00:00", "Z"),
                    "local_starts_at": slot["local_starts_at"],
                    "timezone": slot["timezone"],
                    "staff_profile_id": (
                        str(slot["staff_profile_id"]) if slot["staff_profile_id"] else None
                    ),
                    "staff_options": [str(value) for value in slot["staff_options"]],
                }
            )
        return Response(
            {
                "timezone": location.timezone,
                "date": query.validated_data["date"].isoformat(),
                "service_id": str(service.id),
                "location_id": str(location.id),
                "slot_grid_minutes": 15,
                "slots": payload,
            }
        )


class AppointmentListCreateView(_ManagerWriteMixin, TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        queryset = list_appointments(
            organization=request.organization,
            business=business,
        )
        queryset = _filter_appointments(queryset, request.query_params)
        paginator = StandardLimitOffsetPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(AppointmentSerializer(page, many=True).data)

    def post(self, request, business_id):
        get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        serializer = AppointmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        appointment = create_appointment(
            organization=request.organization,
            business_id=business_id,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(
            AppointmentSerializer(appointment).data,
            status=status.HTTP_201_CREATED,
        )


class AppointmentDetailView(_ManagerWriteMixin, TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id, appointment_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        appointment = get_appointment_for_business(
            organization=request.organization,
            business=business,
            appointment_id=appointment_id,
        )
        return Response(AppointmentSerializer(appointment).data)

    def patch(self, request, business_id, appointment_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        appointment = get_appointment_for_business(
            organization=request.organization,
            business=business,
            appointment_id=appointment_id,
        )
        serializer = AppointmentUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        appointment = update_appointment(
            appointment=appointment,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(AppointmentSerializer(appointment).data)


class AppointmentCancelView(_ManagerWriteMixin, TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def post(self, request, business_id, appointment_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        appointment = get_appointment_for_business(
            organization=request.organization,
            business=business,
            appointment_id=appointment_id,
        )
        serializer = AppointmentCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        appointment = cancel_appointment(
            appointment=appointment,
            actor=request.user,
            reason=serializer.validated_data.get("reason", ""),
        )
        return Response(AppointmentSerializer(appointment).data)


def _filter_appointments(queryset, params):
    starts_after = params.get("starts_at_after")
    if starts_after:
        queryset = queryset.filter(starts_at__gte=starts_after)

    starts_before = params.get("starts_at_before")
    if starts_before:
        queryset = queryset.filter(starts_at__lte=starts_before)

    location_id = params.get("location_id")
    if location_id:
        queryset = queryset.filter(location_id=location_id)

    staff_id = params.get("staff_id")
    if staff_id:
        queryset = queryset.filter(staff_profile_id=staff_id)

    customer_id = params.get("customer_id")
    if customer_id:
        queryset = queryset.filter(customer_id=customer_id)

    service_id = params.get("service_id")
    if service_id:
        queryset = queryset.filter(items__service_id=service_id).distinct()

    status_param = params.get("status")
    if status_param:
        statuses = [part.strip() for part in status_param.split(",") if part.strip()]
        if statuses:
            queryset = queryset.filter(status__in=statuses)

    ordering = params.get("ordering", "starts_at")
    allowed = {
        "starts_at",
        "-starts_at",
        "created_at",
        "-created_at",
        "status",
        "-status",
    }
    if ordering in allowed:
        queryset = queryset.order_by(ordering)
    return queryset
