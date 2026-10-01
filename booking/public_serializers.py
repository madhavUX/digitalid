from rest_framework import serializers


class PublicAvailabilityQuerySerializer(serializers.Serializer):
    location_id = serializers.UUIDField()
    service_id = serializers.UUIDField()
    date = serializers.DateField()
    staff_id = serializers.UUIDField(required=False, allow_null=True, default=None)


class PublicCustomerSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=300)
    phone = serializers.CharField(max_length=32)
    email = serializers.EmailField(required=False, allow_blank=True, default="")


class PublicAppointmentCreateSerializer(serializers.Serializer):
    location_id = serializers.UUIDField()
    service_id = serializers.UUIDField()
    staff_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    start = serializers.DateTimeField()
    customer = PublicCustomerSerializer()
    attribution_source = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=32, default=""
    )
    attribution_ref = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=255, default=""
    )


class PublicBookingPlanCreateSerializer(serializers.Serializer):
    location_id = serializers.UUIDField()
    service_id = serializers.UUIDField()
    staff_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    start = serializers.DateTimeField()
    customer = PublicCustomerSerializer()
    frequency = serializers.ChoiceField(choices=["WEEK", "MONTH"])
    interval = serializers.IntegerField(min_value=1, max_value=2)
    staff_preference = serializers.ChoiceField(
        choices=["SAME_STAFF", "ANY_STAFF"],
        required=False,
        allow_null=True,
        default=None,
    )
    preferred_time = serializers.TimeField(required=False, allow_null=True, default=None)


class PublicAppointmentCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
