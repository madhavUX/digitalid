from django.contrib import admin

from payments.models import Payment, PaymentOrder, PaymentWebhookEvent, Refund


@admin.register(PaymentOrder)
class PaymentOrderAdmin(admin.ModelAdmin):
    list_display = (
        "public_reference",
        "business",
        "appointment",
        "status",
        "amount",
        "currency",
        "provider",
        "created_at",
    )
    list_filter = ("status", "provider", "currency")
    search_fields = ("public_reference", "provider_order_id", "idempotency_key")
    readonly_fields = (
        "id",
        "public_reference",
        "provider_order_id",
        "created_at",
        "updated_at",
    )


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "public_reference",
        "business",
        "appointment",
        "status",
        "amount",
        "amount_paid",
        "amount_refunded",
        "provider",
        "created_at",
    )
    list_filter = ("status", "provider", "currency")
    search_fields = ("public_reference", "provider_payment_id", "provider_order_id")
    readonly_fields = (
        "id",
        "public_reference",
        "provider_payment_id",
        "provider_order_id",
        "provider_signature",
        "created_at",
        "updated_at",
        "paid_at",
        "failed_at",
        "refunded_at",
    )


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "payment",
        "status",
        "amount",
        "currency",
        "created_at",
        "processed_at",
    )
    list_filter = ("status", "currency")
    search_fields = ("provider_refund_id", "idempotency_key")
    readonly_fields = ("id", "provider_refund_id", "created_at", "updated_at", "processed_at")


@admin.register(PaymentWebhookEvent)
class PaymentWebhookEventAdmin(admin.ModelAdmin):
    list_display = (
        "provider",
        "event_type",
        "provider_event_id",
        "status",
        "received_at",
        "processed_at",
    )
    list_filter = ("provider", "status", "event_type")
    search_fields = ("provider_event_id", "event_type")
    readonly_fields = (
        "id",
        "provider",
        "provider_event_id",
        "event_type",
        "payload_hash",
        "received_at",
        "processed_at",
        "created_at",
        "updated_at",
    )
