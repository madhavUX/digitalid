from rest_framework import serializers

from businesses.models import Business, BusinessVertical


class BusinessSerializer(serializers.ModelSerializer):
    class Meta:
        model = Business
        fields = (
            "id",
            "name",
            "slug",
            "vertical",
            "description",
            "logo_url",
            "primary_domain",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class BusinessCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    vertical = serializers.ChoiceField(
        choices=BusinessVertical.choices,
        default=BusinessVertical.SALON,
    )
    slug = serializers.SlugField(max_length=255, required=False, allow_blank=False)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    logo_url = serializers.URLField(
        max_length=500,
        required=False,
        allow_blank=True,
        default="",
    )
    primary_domain = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        allow_null=True,
        default=None,
    )
    is_active = serializers.BooleanField(required=False, default=True)

    def validate_name(self, value: str) -> str:
        name = value.strip()
        if not name:
            raise serializers.ValidationError("This field may not be blank.")
        return name


class BusinessUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False)
    vertical = serializers.ChoiceField(choices=BusinessVertical.choices, required=False)
    slug = serializers.SlugField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    logo_url = serializers.URLField(max_length=500, required=False, allow_blank=True)
    primary_domain = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    is_active = serializers.BooleanField(required=False)

    def validate_name(self, value: str) -> str:
        name = value.strip()
        if not name:
            raise serializers.ValidationError("This field may not be blank.")
        return name
