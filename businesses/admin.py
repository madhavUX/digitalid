from django.contrib import admin

from businesses.models import (
    Business,
    BusinessLaunchProfile,
    GoogleBusinessConnection,
    GoogleOAuthState,
)


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "organization",
        "vertical",
        "slug",
        "is_active",
        "deleted_at",
        "created_at",
    )
    list_filter = ("vertical", "is_active", "deleted_at")
    search_fields = ("name", "slug", "organization__name", "primary_domain")
    autocomplete_fields = ("organization", "created_by", "updated_by", "deleted_by")
    readonly_fields = ("id", "created_at", "updated_at", "deleted_at")
    ordering = ("name",)

    def get_queryset(self, request):
        return Business.all_objects.select_related("organization")


@admin.register(BusinessLaunchProfile)
class BusinessLaunchProfileAdmin(admin.ModelAdmin):
    list_display = (
        "business",
        "location",
        "template_key",
        "subdomain",
        "domain_status",
        "launch_status",
        "website_status",
        "updated_at",
    )
    list_filter = ("launch_status", "domain_status", "website_status", "template_key")
    search_fields = ("subdomain", "custom_domain", "business__name", "location__name")
    autocomplete_fields = (
        "organization",
        "business",
        "location",
        "created_by",
        "updated_by",
        "deleted_by",
    )
    readonly_fields = ("id", "created_at", "updated_at", "deleted_at")

    def get_queryset(self, request):
        return BusinessLaunchProfile.all_objects.select_related(
            "organization",
            "business",
            "location",
        )


@admin.register(GoogleBusinessConnection)
class GoogleBusinessConnectionAdmin(admin.ModelAdmin):
    list_display = (
        "business",
        "location",
        "provider",
        "status",
        "google_email",
        "last_sync_status",
        "token_expires_at",
        "connected_at",
        "last_synced_at",
        "updated_at",
    )
    list_filter = ("status", "provider", "last_sync_status")
    search_fields = (
        "google_location_id",
        "google_location_display_name",
        "google_business_account_name",
        "google_account_id",
        "google_email",
        "business__name",
        "location__name",
    )
    autocomplete_fields = (
        "organization",
        "business",
        "location",
        "created_by",
        "updated_by",
        "deleted_by",
    )
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "deleted_at",
        "has_access_token",
        "has_refresh_token",
    )
    exclude = ("access_token_encrypted", "refresh_token_encrypted")

    @admin.display(boolean=True, description="Access token stored")
    def has_access_token(self, obj):
        return bool(obj.access_token_encrypted)

    @admin.display(boolean=True, description="Refresh token stored")
    def has_refresh_token(self, obj):
        return bool(obj.refresh_token_encrypted)

    def get_queryset(self, request):
        return GoogleBusinessConnection.all_objects.select_related(
            "organization",
            "business",
            "location",
        )


@admin.register(GoogleOAuthState)
class GoogleOAuthStateAdmin(admin.ModelAdmin):
    list_display = ("business", "location", "user", "expires_at", "used_at", "created_at")
    list_filter = ("used_at",)
    search_fields = ("state_hash", "user__email", "business__name")
    readonly_fields = ("id", "state_hash", "created_at", "updated_at", "used_at")
    autocomplete_fields = ("user", "organization", "business", "location")
