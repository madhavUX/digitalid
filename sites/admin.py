from django.contrib import admin

from sites.models import QuickCard


@admin.register(QuickCard)
class QuickCardAdmin(admin.ModelAdmin):
    list_display = (
        "slug",
        "business",
        "location",
        "is_published",
        "published_at",
        "updated_at",
    )
    list_filter = ("is_published", "business")
    search_fields = ("slug", "headline", "location__name", "business__name")
    readonly_fields = (
        "id",
        "organization",
        "business",
        "location",
        "slug",
        "view_count",
        "published_at",
        "created_at",
        "updated_at",
        "created_by",
        "updated_by",
        "deleted_at",
        "deleted_by",
    )
