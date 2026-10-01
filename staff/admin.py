from django.contrib import admin

from staff.models import StaffAvailability, StaffProfile, StaffService, StaffTimeOff


class StaffServiceInline(admin.TabularInline):
    model = StaffService
    extra = 0
    autocomplete_fields = ("service", "organization")
    fields = ("organization", "service", "duration_minutes", "price", "currency")
    fk_name = "staff_profile"


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = (
        "display_name",
        "business",
        "location",
        "organization",
        "is_bookable",
        "is_active",
        "deleted_at",
        "created_at",
    )
    list_filter = ("is_bookable", "is_active", "deleted_at")
    search_fields = (
        "display_name",
        "title",
        "business__name",
        "location__name",
        "organization__name",
        "user__email",
    )
    autocomplete_fields = (
        "organization",
        "business",
        "location",
        "user",
        "created_by",
        "updated_by",
        "deleted_by",
    )
    readonly_fields = ("id", "created_at", "updated_at", "deleted_at")
    inlines = [StaffServiceInline]
    ordering = ("display_name",)

    def get_queryset(self, request):
        return StaffProfile.all_objects.select_related(
            "organization",
            "business",
            "location",
            "user",
        )


@admin.register(StaffService)
class StaffServiceAdmin(admin.ModelAdmin):
    list_display = (
        "staff_profile",
        "service",
        "organization",
        "duration_minutes",
        "price",
        "currency",
        "created_at",
    )
    search_fields = (
        "staff_profile__display_name",
        "service__name",
        "organization__name",
    )
    autocomplete_fields = (
        "organization",
        "staff_profile",
        "service",
        "created_by",
        "updated_by",
    )
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("created_at",)

    def get_queryset(self, request):
        return StaffService.objects.select_related(
            "organization",
            "staff_profile",
            "service",
        )


@admin.register(StaffAvailability)
class StaffAvailabilityAdmin(admin.ModelAdmin):
    list_display = (
        "staff_profile",
        "location",
        "weekday",
        "starts_at",
        "ends_at",
        "organization",
        "created_at",
    )
    list_filter = ("weekday",)
    search_fields = (
        "staff_profile__display_name",
        "location__name",
        "organization__name",
    )
    autocomplete_fields = (
        "organization",
        "staff_profile",
        "location",
        "created_by",
        "updated_by",
    )
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("weekday", "starts_at")


@admin.register(StaffTimeOff)
class StaffTimeOffAdmin(admin.ModelAdmin):
    list_display = (
        "staff_profile",
        "starts_at",
        "ends_at",
        "reason",
        "organization",
        "created_at",
    )
    search_fields = (
        "staff_profile__display_name",
        "reason",
        "organization__name",
    )
    autocomplete_fields = (
        "organization",
        "staff_profile",
        "created_by",
        "updated_by",
    )
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("-starts_at",)
