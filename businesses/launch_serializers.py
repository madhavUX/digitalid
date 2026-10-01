from rest_framework import serializers

from businesses.models import (
    DomainStatus,
    GoogleBusinessStatus,
    LaunchStatus,
    WebsiteStatus,
    WebsiteTemplateKey,
    WhatsAppSetupStatus,
)


class LaunchProfileWriteSerializer(serializers.Serializer):
    location_id = serializers.UUIDField(required=False)
    template_key = serializers.ChoiceField(
        choices=WebsiteTemplateKey.choices,
        required=False,
        allow_blank=True,
    )
    subdomain = serializers.CharField(required=False, allow_blank=True, max_length=63)
    custom_domain = serializers.CharField(required=False, allow_blank=True, max_length=255)
    domain_status = serializers.ChoiceField(
        choices=DomainStatus.choices,
        required=False,
    )
    google_business_url = serializers.URLField(
        required=False,
        allow_blank=True,
        max_length=500,
    )
    google_review_url = serializers.URLField(
        required=False,
        allow_blank=True,
        max_length=500,
    )
    google_business_status = serializers.ChoiceField(
        choices=GoogleBusinessStatus.choices,
        required=False,
    )
    whatsapp_setup_status = serializers.ChoiceField(
        choices=WhatsAppSetupStatus.choices,
        required=False,
    )
    website_status = serializers.ChoiceField(
        choices=WebsiteStatus.choices,
        required=False,
    )
    launch_status = serializers.ChoiceField(
        choices=LaunchStatus.choices,
        required=False,
    )
