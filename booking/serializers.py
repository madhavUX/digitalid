from rest_framework import serializers

from booking.models import Appointment, AppointmentItem, AppointmentSource, AppointmentStatus


class AppointmentItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppointmentItem
        fields = (
            "id",
            "service",
            "staff_profile",
            "service_name",
            "duration_minutes",
            "buffer_before_minutes",
            "buffer_after_minutes",
            "price",
            "currency",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class AppointmentSerializer(serializers.ModelSerializer):
    items = AppointmentItemSerializer(many=True, read_only=True)

    class Meta:
        model = Appointment
        fields = (
            "id",
            "business",
            "location",
            "customer",
            "staff_profile",
            "starts_at",
            "ends_at",
            "occupancy_starts_at",
            "occupancy_ends_at",
            "status",
            "source",
            "total_price",
            "currency",
            "deposit_amount",
            "deposit_paid",
            "notes",
            "cancelled_at",
            "completed_at",
            "cancellation_reason",
            "cancelled_by",
            "public_reference",
            "items",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class AppointmentCreateSerializer(serializers.Serializer):
    location_id = serializers.UUIDField()
    customer_id = serializers.UUIDField()
    service_id = serializers.UUIDField()
    starts_at = serializers.DateTimeField()
    staff_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    status = serializers.ChoiceField(
        choices=[AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED],
        required=False,
        default=AppointmentStatus.CONFIRMED,
    )
    source = serializers.ChoiceField(
        choices=AppointmentSource.choices,
        required=False,
        default=AppointmentSource.DASHBOARD,
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class AppointmentUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=AppointmentStatus.choices, required=False)
    starts_at = serializers.DateTimeField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True)
    cancellation_reason = serializers.CharField(required=False, allow_blank=True, max_length=255)


class AppointmentCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)


class AvailabilityQuerySerializer(serializers.Serializer):
    service_id = serializers.UUIDField()
    date = serializers.DateField()
    staff_id = serializers.UUIDField(required=False, allow_null=True, default=None)
