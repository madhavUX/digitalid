from django.contrib import admin

from messaging.models import (
    AppointmentReminder,
    MessageTemplate,
    WhatsAppAccount,
    WhatsAppInboundMessage,
    WhatsAppMessage,
)


@admin.register(WhatsAppAccount)
class WhatsAppAccountAdmin(admin.ModelAdmin):
    list_display = (
        "business",
        "status",
        "display_phone_number",
        "verified_name",
        "phone_number_id",
        "connected_at",
        "disconnected_at",
        "has_access_token",
    )
    list_filter = ("status",)
    search_fields = (
        "display_phone_number",
        "verified_name",
        "phone_number_id",
        "business_account_id",
        "business__name",
    )
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "deleted_at",
        "has_access_token",
    )
    exclude = ("access_token_encrypted",)

    @admin.display(boolean=True, description="Access token stored")
    def has_access_token(self, obj):
        return bool(obj.access_token_encrypted)

    def get_queryset(self, request):
        return WhatsAppAccount.all_objects.select_related("organization", "business")


@admin.register(MessageTemplate)
class MessageTemplateAdmin(admin.ModelAdmin):
    list_display = ("business", "name", "language", "category", "status", "updated_at")
    list_filter = ("status", "category")
    search_fields = ("name", "business__name")

    def get_queryset(self, request):
        return MessageTemplate.all_objects.select_related("business")


@admin.register(WhatsAppMessage)
class WhatsAppMessageAdmin(admin.ModelAdmin):
    list_display = (
        "business",
        "status",
        "message_type",
        "template_name",
        "provider_message_id",
        "created_at",
        "sent_at",
    )
    list_filter = ("status", "message_type")
    search_fields = ("template_name", "provider_message_id", "business__name")
    readonly_fields = ("id", "created_at", "updated_at", "payload")


@admin.register(AppointmentReminder)
class AppointmentReminderAdmin(admin.ModelAdmin):
    list_display = (
        "business",
        "notification_type",
        "status",
        "schedule_version",
        "scheduled_for",
        "sent_at",
    )
    list_filter = ("status", "notification_type")
    search_fields = ("idempotency_key", "appointment__public_reference", "business__name")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(WhatsAppInboundMessage)
class WhatsAppInboundMessageAdmin(admin.ModelAdmin):
    list_display = ("business", "message_type", "processing_status", "created_at")
    list_filter = ("message_type", "processing_status")
    search_fields = ("provider_message_id", "business__name")
    readonly_fields = ("id", "created_at", "updated_at", "text", "phone_number")
