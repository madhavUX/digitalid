from rest_framework import serializers

from customers.models import Customer, CustomerTag, CustomerTagAssignment


class CustomerTagNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerTag
        fields = ("id", "name")
        read_only_fields = fields


class CustomerSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    tags = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = (
            "id",
            "business",
            "first_name",
            "last_name",
            "full_name",
            "phone",
            "email",
            "date_of_birth",
            "notes",
            "marketing_opt_in",
            "whatsapp_opt_in",
            "first_visit_at",
            "last_visit_at",
            "total_visits",
            "total_spend",
            "tags",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_tags(self, obj: Customer):
        assignments = getattr(obj, "_prefetched_objects_cache", {}).get("tag_assignments")
        if assignments is None:
            assignments = obj.tag_assignments.select_related("tag").all()
        tags = [a.tag for a in assignments]
        return CustomerTagNestedSerializer(tags, many=True).data


class CustomerCreateSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=20)
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    date_of_birth = serializers.DateField(required=False, allow_null=True, default=None)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    marketing_opt_in = serializers.BooleanField(required=False, default=False)
    whatsapp_opt_in = serializers.BooleanField(required=False, default=False)


class CustomerUpdateSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=150, required=False)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=20, required=False)
    email = serializers.EmailField(required=False, allow_blank=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    marketing_opt_in = serializers.BooleanField(required=False)
    whatsapp_opt_in = serializers.BooleanField(required=False)


class CustomerRetentionSettingsUpdateSerializer(serializers.Serializer):
    return_after_days = serializers.IntegerField(min_value=1, required=False)
    inactive_after_days = serializers.IntegerField(min_value=1, required=False)
    due_message_delay_hours = serializers.IntegerField(min_value=1, required=False)
    enabled = serializers.BooleanField(required=False)

    def validate(self, attrs):
        # Cross-field check happens in the service against current + new values.
        return attrs


class CustomerTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerTag
        fields = (
            "id",
            "business",
            "name",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class CustomerTagCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)

    def validate_name(self, value: str) -> str:
        name = value.strip()
        if not name:
            raise serializers.ValidationError("This field may not be blank.")
        return name


class CustomerTagUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)

    def validate_name(self, value: str) -> str:
        name = value.strip()
        if not name:
            raise serializers.ValidationError("This field may not be blank.")
        return name


class CustomerTagAssignmentSerializer(serializers.ModelSerializer):
    tag = CustomerTagNestedSerializer(read_only=True)

    class Meta:
        model = CustomerTagAssignment
        fields = (
            "id",
            "customer",
            "tag",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class CustomerTagAssignSerializer(serializers.Serializer):
    tag_id = serializers.UUIDField()
