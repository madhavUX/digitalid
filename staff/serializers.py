from rest_framework import serializers

from staff.models import StaffAvailability, StaffProfile, StaffService, StaffTimeOff, Weekday


class StaffProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffProfile
        fields = (
            "id",
            "business",
            "location",
            "user",
            "display_name",
            "title",
            "bio",
            "photo_url",
            "is_bookable",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class StaffProfileCreateSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=255)
    location_id = serializers.UUIDField()
    title = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    bio = serializers.CharField(required=False, allow_blank=True, default="")
    photo_url = serializers.URLField(
        max_length=500,
        required=False,
        allow_blank=True,
        default="",
    )
    user_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    is_bookable = serializers.BooleanField(required=False, default=True)
    is_active = serializers.BooleanField(required=False, default=True)

    def validate_display_name(self, value: str) -> str:
        name = value.strip()
        if not name:
            raise serializers.ValidationError("This field may not be blank.")
        return name


class StaffProfileUpdateSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=255, required=False)
    location_id = serializers.UUIDField(required=False)
    title = serializers.CharField(max_length=255, required=False, allow_blank=True)
    bio = serializers.CharField(required=False, allow_blank=True)
    photo_url = serializers.URLField(max_length=500, required=False, allow_blank=True)
    user_id = serializers.UUIDField(required=False, allow_null=True)
    is_bookable = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)

    def validate_display_name(self, value: str) -> str:
        name = value.strip()
        if not name:
            raise serializers.ValidationError("This field may not be blank.")
        return name


class StaffServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffService
        fields = (
            "id",
            "staff_profile",
            "service",
            "duration_minutes",
            "price",
            "currency",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class StaffServiceCreateSerializer(serializers.Serializer):
    service_id = serializers.UUIDField()
    duration_minutes = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    price = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        required=False,
        allow_null=True,
    )
    currency = serializers.CharField(max_length=3, required=False, allow_blank=True, default="")


class StaffServiceUpdateSerializer(serializers.Serializer):
    duration_minutes = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    price = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        required=False,
        allow_null=True,
    )
    currency = serializers.CharField(max_length=3, required=False, allow_blank=True)


class StaffAvailabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffAvailability
        fields = (
            "id",
            "staff_profile",
            "location",
            "weekday",
            "starts_at",
            "ends_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class StaffAvailabilityCreateSerializer(serializers.Serializer):
    location_id = serializers.UUIDField()
    weekday = serializers.ChoiceField(choices=Weekday.choices)
    starts_at = serializers.TimeField()
    ends_at = serializers.TimeField()

    def validate(self, attrs):
        if attrs["ends_at"] <= attrs["starts_at"]:
            raise serializers.ValidationError({"ends_at": "End time must be after start time."})
        return attrs


class StaffAvailabilityUpdateSerializer(serializers.Serializer):
    location_id = serializers.UUIDField(required=False)
    weekday = serializers.ChoiceField(choices=Weekday.choices, required=False)
    starts_at = serializers.TimeField(required=False)
    ends_at = serializers.TimeField(required=False)


class StaffTimeOffSerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffTimeOff
        fields = (
            "id",
            "staff_profile",
            "starts_at",
            "ends_at",
            "reason",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class StaffTimeOffCreateSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if attrs["ends_at"] <= attrs["starts_at"]:
            raise serializers.ValidationError(
                {"ends_at": "End datetime must be after start datetime."}
            )
        return attrs


class StaffTimeOffUpdateSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField(required=False)
    ends_at = serializers.DateTimeField(required=False)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True)
