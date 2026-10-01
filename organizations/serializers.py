from rest_framework import serializers

from accounts.models import User
from organizations.models import Organization, OrganizationMember


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ("id", "name", "slug", "is_active", "created_at")
        read_only_fields = fields


class OrganizationUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "first_name", "last_name")
        read_only_fields = fields


class OrganizationMemberSerializer(serializers.ModelSerializer):
    user = OrganizationUserSerializer(read_only=True)

    class Meta:
        model = OrganizationMember
        fields = ("id", "user", "role", "is_active", "created_at")
        read_only_fields = fields
