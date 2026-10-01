from django.contrib import admin

from customers.models import Customer, CustomerTag, CustomerTagAssignment


class CustomerTagAssignmentInline(admin.TabularInline):
    model = CustomerTagAssignment
    extra = 0
    autocomplete_fields = ("tag", "organization")
    fields = ("organization", "tag", "created_at")
    readonly_fields = ("created_at",)
    fk_name = "customer"


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "phone",
        "email",
        "business",
        "organization",
        "total_visits",
        "deleted_at",
        "created_at",
    )
    list_filter = ("marketing_opt_in", "whatsapp_opt_in", "deleted_at")
    search_fields = (
        "first_name",
        "last_name",
        "phone",
        "email",
        "business__name",
        "organization__name",
    )
    autocomplete_fields = (
        "organization",
        "business",
        "created_by",
        "updated_by",
        "deleted_by",
    )
    readonly_fields = (
        "id",
        "first_visit_at",
        "last_visit_at",
        "total_visits",
        "total_spend",
        "created_at",
        "updated_at",
        "deleted_at",
    )
    inlines = [CustomerTagAssignmentInline]
    ordering = ("last_name", "first_name")

    def get_queryset(self, request):
        return Customer.all_objects.select_related("organization", "business")

    @admin.display(description="Name")
    def full_name(self, obj):
        return obj.full_name


@admin.register(CustomerTag)
class CustomerTagAdmin(admin.ModelAdmin):
    list_display = ("name", "business", "organization", "created_at")
    search_fields = ("name", "business__name", "organization__name")
    autocomplete_fields = (
        "organization",
        "business",
        "created_by",
        "updated_by",
    )
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("name",)


@admin.register(CustomerTagAssignment)
class CustomerTagAssignmentAdmin(admin.ModelAdmin):
    list_display = ("customer", "tag", "organization", "created_at")
    search_fields = (
        "customer__first_name",
        "customer__last_name",
        "customer__phone",
        "tag__name",
        "organization__name",
    )
    autocomplete_fields = (
        "organization",
        "customer",
        "tag",
        "created_by",
        "updated_by",
    )
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("created_at",)

    def get_queryset(self, request):
        return CustomerTagAssignment.objects.select_related(
            "organization",
            "customer",
            "tag",
        )
