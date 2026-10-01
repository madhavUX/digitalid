from django.urls import path

from booking.webhook_views import WhatsAppWebhookView

urlpatterns = [
    path("whatsapp/", WhatsAppWebhookView.as_view(), name="webhook-whatsapp"),
    path("whatsapp/meta/", WhatsAppWebhookView.as_view(), name="webhook-whatsapp-meta"),
]
