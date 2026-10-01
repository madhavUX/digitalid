from rest_framework import serializers

from catalog.models import Service, ServiceCategory, ServiceLocation


class ServiceCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceCategory
        fields = (
            "id",
            "business",
            "name",
            "slug",
            "display_order",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class ServiceCategoryCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    slug = serializers.SlugField(max_length=255, required=False)
    display_order = serializers.IntegerField(required=False, min_value=0, default=0)

    def validate_name(self, value: str) -> str:
        name = value.strip()
        if not name:
            raise serializers.ValidationError("This field may not be blank.")
        return name


class ServiceCategoryUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False)
    slug = serializers.SlugField(max_length=255, required=False)
    display_order = serializers.IntegerField(required=False, min_value=0)

    def validate_name(self, value: str) -> str:
        name = value.strip()
        if not name:
            raise serializers.ValidationError("This field may not be blank.")
        return name


class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = (
            "id",
            "business",
            "category",
            "name",
            "slug",
            "description",
            "duration_minutes",
            "buffer_before_minutes",
            "buffer_after_minutes",
            "price",
            "currency",
            "is_bookable_online",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class ServiceCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    duration_minutes = serializers.IntegerField(min_value=1)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    currency = serializers.CharField(max_length=3, required=False, default="INR")
    slug = serializers.SlugField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    category_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    buffer_before_minutes = serializers.IntegerField(required=False, min_value=0, default=0)
    buffer_after_minutes = serializers.IntegerField(required=False, min_value=0, default=0)
    is_bookable_online = serializers.BooleanField(required=False, default=True)
    is_active = serializers.BooleanField(required=False, default=True)

    def validate_name(self, value: str) -> str:
        name = value.strip()
        if not name:
            raise serializers.ValidationError("This field may not be blank.")
        return name

    def validate_currency(self, value: str) -> str:
        currency = value.strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise serializers.ValidationError("Enter a valid ISO 4217 currency code.")
        return currency


class ServiceUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False)
    duration_minutes = serializers.IntegerField(min_value=1, required=False)
    price = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        required=False,
    )
    currency = serializers.CharField(max_length=3, required=False)
    slug = serializers.SlugField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    category_id = serializers.UUIDField(required=False, allow_null=True)
    buffer_before_minutes = serializers.IntegerField(required=False, min_value=0)
    buffer_after_minutes = serializers.IntegerField(required=False, min_value=0)
    is_bookable_online = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)

    def validate_name(self, value: str) -> str:
        name = value.strip()
        if not name:
            raise serializers.ValidationError("This field may not be blank.")
        return name

    def validate_currency(self, value: str) -> str:
        currency = value.strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise serializers.ValidationError("Enter a valid ISO 4217 currency code.")
        return currency


class ServiceLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceLocation
        fields = (
            "id",
            "service",
            "location",
            "duration_minutes",
            "price",
            "currency",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class ServiceLocationCreateSerializer(serializers.Serializer):
    location_id = serializers.UUIDField()
    duration_minutes = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    price = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        required=False,
        allow_null=True,
    )
    currency = serializers.CharField(max_length=3, required=False, allow_blank=True, default="")


class ServiceLocationUpdateSerializer(serializers.Serializer):
    duration_minutes = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
    )
    price = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        required=False,
        allow_null=True,
    )
    currency = serializers.CharField(max_length=3, required=False, allow_blank=True)
