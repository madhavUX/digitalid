from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from accounts.models import User
from organizations.models import OrganizationMember
from organizations.serializers import OrganizationSerializer


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    organization_name = serializers.CharField(max_length=255)

    def validate_email(self, value: str) -> str:
        return value.lower().strip()

    def validate_password(self, value: str) -> str:
        validate_password(value)
        return value

    def validate_organization_name(self, value: str) -> str:
        name = value.strip()
        if not name:
            raise serializers.ValidationError("This field may not be blank.")
        return name


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_email(self, value: str) -> str:
        return value.lower().strip()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "first_name", "last_name", "date_joined")
        read_only_fields = fields


class MembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationMember
        fields = ("id", "role", "is_active")
        read_only_fields = fields


class AuthResponseSerializer(serializers.Serializer):
    user = UserSerializer()
    organization = OrganizationSerializer(allow_null=True)
    membership = MembershipSerializer(allow_null=True)
    access = serializers.CharField()
    refresh = serializers.CharField()

    def to_representation(self, instance):
        tokens = instance["tokens"]
        return {
            "user": UserSerializer(instance["user"]).data,
            "organization": OrganizationSerializer(instance["organization"]).data
            if instance.get("organization")
            else None,
            "membership": MembershipSerializer(instance["membership"]).data
            if instance.get("membership")
            else None,
            "access": tokens["access"],
            "refresh": tokens["refresh"],
        }
