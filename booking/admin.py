from django.contrib import admin
from django.utils.html import format_html

from booking.models import (
    Appointment,
    AppointmentItem,
    IdempotencyRecord,
    NotificationDelivery,
)


def _mask_recipient(value: str) -> str:
    cleaned = (value or "").strip()
    if "@" in cleaned:
        local, _, domain = cleaned.partition("@")
        if len(local) <= 2:
            return f"**@{domain}"
        return f"{local[:2]}***@{domain}"
    if len(cleaned) <= 4:
        return "****"
    return f"{cleaned[:3]}******{cleaned[-4:]}"


class AppointmentItemInline(admin.TabularInline):
    model = AppointmentItem
    extra = 0
    autocomplete_fields = ("service", "staff_profile")
    readonly_fields = (
        "service_name",
        "duration_minutes",
        "buffer_before_minutes",
        "buffer_after_minutes",
        "price",
        "currency",
        "created_at",
    )


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = (
        "public_reference",
        "status",
        "starts_at",
        "staff_profile",
        "customer",
        "location",
        "business",
        "source",
        "deleted_at",
    )
    list_filter = ("status", "source", "location", "deleted_at")
    search_fields = (
        "public_reference",
        "customer__first_name",
        "customer__last_name",
        "customer__phone",
        "staff_profile__display_name",
        "organization__name",
        "business__name",
    )
    autocomplete_fields = (
        "organization",
        "business",
        "location",
        "customer",
        "staff_profile",
        "created_by",
        "updated_by",
        "deleted_by",
        "cancelled_by",
    )
    readonly_fields = (
        "id",
        "public_reference",
        "occupancy_starts_at",
        "occupancy_ends_at",
        "created_at",
        "updated_at",
        "deleted_at",
        "cancelled_at",
    )
    date_hierarchy = "starts_at"
    inlines = [AppointmentItemInline]
    ordering = ("-starts_at",)

    def get_queryset(self, request):
        return Appointment.all_objects.select_related(
            "organization",
            "business",
            "location",
            "customer",
            "staff_profile",
        )


@admin.register(IdempotencyRecord)
class IdempotencyRecordAdmin(admin.ModelAdmin):
    list_display = ("scope", "key", "response_status", "created_at", "updated_at")
    list_filter = ("scope", "response_status")
    search_fields = ("key", "request_hash")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(AppointmentItem)
class AppointmentItemAdmin(admin.ModelAdmin):
    list_display = (
        "service_name",
        "appointment",
        "staff_profile",
        "duration_minutes",
        "price",
        "currency",
    )
    search_fields = (
        "service_name",
        "appointment__public_reference",
        "staff_profile__display_name",
    )
    autocomplete_fields = ("appointment", "service", "staff_profile", "created_by", "updated_by")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(NotificationDelivery)
class NotificationDeliveryAdmin(admin.ModelAdmin):
    list_display = (
        "appointment_reference",
        "notification_type",
        "channel",
        "masked_recipient",
        "status",
        "provider_status",
        "attempt_count",
        "sent_at",
        "provider_message_id",
        "created_at",
    )
    list_filter = ("channel", "notification_type", "status")
    search_fields = (
        "appointment__public_reference",
        "provider_message_id",
        "recipient",
    )
    readonly_fields = (
        "id",
        "appointment",
        "channel",
        "notification_type",
        "masked_recipient",
        "status",
        "provider_status",
        "provider_message_id",
        "attempt_count",
        "last_error",
        "error_class",
        "sent_at",
        "delivered_at",
        "read_at",
        "failed_at",
        "payload_version",
        "created_at",
        "updated_at",
    )
    exclude = ("recipient", "payload_snapshot")
    ordering = ("-created_at",)

    @admin.display(description="Appointment")
    def appointment_reference(self, obj):
        return obj.appointment.public_reference

    @admin.display(description="Recipient")
    def masked_recipient(self, obj):
        return format_html("<code>{}</code>", _mask_recipient(obj.recipient))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
