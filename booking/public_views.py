from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from booking.history_services import get_book_again_prefill, list_guest_booking_history
from booking.plan_services import (
    cancel_plan_via_appointment_token,
    cancel_public_booking_plan,
    create_public_booking_plan,
    get_public_booking_plan,
    pause_plan_via_appointment_token,
    pause_public_booking_plan,
    resume_plan_via_appointment_token,
    resume_public_booking_plan,
)
from booking.public_serializers import (
    PublicAppointmentCancelSerializer,
    PublicAppointmentCreateSerializer,
    PublicAvailabilityQuerySerializer,
    PublicBookingPlanCreateSerializer,
)
from booking.public_services import (
    cancel_managed_appointment,
    cancel_public_appointment,
    create_public_appointment,
    get_appointment_by_public_reference,
    get_managed_appointment,
    public_availability,
    serialize_public_appointment,
)


class PublicAvailabilityThrottle(AnonRateThrottle):
    scope = "public_booking_availability"


class PublicBookingWriteThrottle(AnonRateThrottle):
    scope = "public_booking_write"


class PublicAvailabilityView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicAvailabilityThrottle]

    def get(self, request):
        query = PublicAvailabilityQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = public_availability(
            location_id=query.validated_data["location_id"],
            service_id=query.validated_data["service_id"],
            local_day=query.validated_data["date"],
            staff_id=query.validated_data.get("staff_id"),
        )
        return Response(data)


class PublicAppointmentCreateView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicBookingWriteThrottle]

    def post(self, request):
        serializer = PublicAppointmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = serializer.validated_data["customer"]
        idempotency_key = request.headers.get("Idempotency-Key") or request.META.get(
            "HTTP_IDEMPOTENCY_KEY"
        )
        if idempotency_key is not None:
            idempotency_key = idempotency_key.strip() or None
            if idempotency_key and len(idempotency_key) > 255:
                return Response(
                    {
                        "error": {"Idempotency-Key": "Must be at most 255 characters."},
                        "status_code": 400,
                        "code": "INVALID_IDEMPOTENCY_KEY",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        body, http_status, _is_replay = create_public_appointment(
            location_id=serializer.validated_data["location_id"],
            service_id=serializer.validated_data["service_id"],
            starts_at=serializer.validated_data["start"],
            staff_id=serializer.validated_data.get("staff_id"),
            customer_name=customer["name"],
            customer_phone=customer["phone"],
            customer_email=customer.get("email") or "",
            idempotency_key=idempotency_key,
            attribution_source=serializer.validated_data.get("attribution_source") or "",
            attribution_ref=serializer.validated_data.get("attribution_ref") or "",
        )
        return Response(body, status=http_status)


class PublicAppointmentDetailView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicAvailabilityThrottle]

    def get(self, request, public_reference):
        appointment = get_appointment_by_public_reference(public_reference)
        return Response(serialize_public_appointment(appointment))


class PublicAppointmentCancelView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicBookingWriteThrottle]

    def post(self, request, public_reference):
        serializer = PublicAppointmentCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        body = cancel_public_appointment(
            public_reference=public_reference,
            reason=serializer.validated_data.get("reason") or "",
        )
        return Response(body)


class PublicManageBookingView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicAvailabilityThrottle]

    def get(self, request, token):
        return Response(get_managed_appointment(raw_token=token))


class PublicManageBookingCancelView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicBookingWriteThrottle]

    def post(self, request, token):
        serializer = PublicAppointmentCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        body = cancel_managed_appointment(
            raw_token=token,
            reason=serializer.validated_data.get("reason") or "",
        )
        return Response(body)


class PublicBookingHistoryView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicAvailabilityThrottle]

    def get(self, request, token):
        category = request.query_params.get("category") or "upcoming"
        limit = request.query_params.get("limit")
        offset = request.query_params.get("offset") or 0
        try:
            limit_val = int(limit) if limit is not None else None
            offset_val = int(offset)
        except (TypeError, ValueError):
            return Response(
                {
                    "error": "limit and offset must be integers.",
                    "status_code": 400,
                    "code": "INVALID_PAGINATION",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        body = list_guest_booking_history(
            raw_token=token,
            category=category,
            limit=limit_val,
            offset=offset_val,
        )
        return Response(body)


class PublicBookAgainView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicAvailabilityThrottle]

    def get(self, request, token, public_reference):
        body = get_book_again_prefill(
            raw_token=token,
            public_reference=public_reference,
        )
        return Response(body)


class PublicBookingPlanCreateView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicBookingWriteThrottle]

    def post(self, request):
        serializer = PublicBookingPlanCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = serializer.validated_data["customer"]
        idempotency_key = request.headers.get("Idempotency-Key") or request.META.get(
            "HTTP_IDEMPOTENCY_KEY"
        )
        if idempotency_key is not None:
            idempotency_key = idempotency_key.strip() or None
            if idempotency_key and len(idempotency_key) > 255:
                return Response(
                    {
                        "error": {"Idempotency-Key": "Must be at most 255 characters."},
                        "status_code": 400,
                        "code": "INVALID_IDEMPOTENCY_KEY",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
        body, http_status, _is_replay = create_public_booking_plan(
            location_id=serializer.validated_data["location_id"],
            service_id=serializer.validated_data["service_id"],
            starts_at=serializer.validated_data["start"],
            staff_id=serializer.validated_data.get("staff_id"),
            customer_name=customer["name"],
            customer_phone=customer["phone"],
            customer_email=customer.get("email") or "",
            frequency=serializer.validated_data["frequency"],
            interval=serializer.validated_data["interval"],
            staff_preference=serializer.validated_data.get("staff_preference"),
            preferred_time=serializer.validated_data.get("preferred_time"),
            idempotency_key=idempotency_key,
        )
        return Response(body, status=http_status)


class PublicBookingPlanDetailView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicAvailabilityThrottle]

    def get(self, request, token):
        return Response(get_public_booking_plan(raw_token=token))


class PublicBookingPlanPauseView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicBookingWriteThrottle]

    def post(self, request, token):
        return Response(pause_public_booking_plan(raw_token=token))


class PublicBookingPlanResumeView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicBookingWriteThrottle]

    def post(self, request, token):
        return Response(resume_public_booking_plan(raw_token=token))


class PublicBookingPlanCancelView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicBookingWriteThrottle]

    def post(self, request, token):
        return Response(cancel_public_booking_plan(raw_token=token))


class PublicManagePlanPauseView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicBookingWriteThrottle]

    def post(self, request, token):
        return Response(pause_plan_via_appointment_token(raw_token=token))


class PublicManagePlanResumeView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicBookingWriteThrottle]

    def post(self, request, token):
        return Response(resume_plan_via_appointment_token(raw_token=token))


class PublicManagePlanCancelView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicBookingWriteThrottle]

    def post(self, request, token):
        return Response(cancel_plan_via_appointment_token(raw_token=token))
