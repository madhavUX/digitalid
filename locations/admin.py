from django.contrib import admin

from locations.models import Location


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "business",
        "organization",
        "city",
        "timezone",
        "is_primary",
        "is_active",
        "deleted_at",
        "created_at",
    )
    list_filter = ("is_primary", "is_active", "country", "deleted_at")
    search_fields = ("name", "slug", "city", "business__name", "organization__name")
    autocomplete_fields = (
        "organization",
        "business",
        "created_by",
        "updated_by",
        "deleted_by",
    )
    readonly_fields = ("id", "created_at", "updated_at", "deleted_at")
    ordering = ("name",)

    def get_queryset(self, request):
        return Location.all_objects.select_related("organization", "business")
