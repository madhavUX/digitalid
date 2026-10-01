from django.contrib import admin

from catalog.models import Service, ServiceCategory, ServiceLocation


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "business",
        "organization",
        "slug",
        "display_order",
        "deleted_at",
        "created_at",
    )
    list_filter = ("deleted_at",)
    search_fields = ("name", "slug", "business__name", "organization__name")
    autocomplete_fields = (
        "organization",
        "business",
        "created_by",
        "updated_by",
        "deleted_by",
    )
    readonly_fields = ("id", "created_at", "updated_at", "deleted_at")
    ordering = ("display_order", "name")

    def get_queryset(self, request):
        return ServiceCategory.all_objects.select_related("organization", "business")


class ServiceLocationInline(admin.TabularInline):
    model = ServiceLocation
    extra = 0
    autocomplete_fields = ("location", "organization")
    fields = ("organization", "location", "duration_minutes", "price", "currency")
    fk_name = "service"


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "business",
        "category",
        "duration_minutes",
        "price",
        "currency",
        "is_active",
        "is_bookable_online",
        "deleted_at",
    )
    list_filter = ("is_active", "is_bookable_online", "currency", "deleted_at")
    search_fields = ("name", "slug", "business__name", "organization__name")
    autocomplete_fields = (
        "organization",
        "business",
        "category",
        "created_by",
        "updated_by",
        "deleted_by",
    )
    readonly_fields = ("id", "created_at", "updated_at", "deleted_at")
    inlines = [ServiceLocationInline]
    ordering = ("name",)

    def get_queryset(self, request):
        return Service.all_objects.select_related("organization", "business", "category")


@admin.register(ServiceLocation)
class ServiceLocationAdmin(admin.ModelAdmin):
    list_display = (
        "service",
        "location",
        "organization",
        "duration_minutes",
        "price",
        "currency",
        "created_at",
    )
    search_fields = ("service__name", "location__name", "organization__name")
    autocomplete_fields = (
        "organization",
        "service",
        "location",
        "created_by",
        "updated_by",
    )
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("created_at",)

    def get_queryset(self, request):
        return ServiceLocation.objects.select_related(
            "organization",
            "service",
            "location",
        )
