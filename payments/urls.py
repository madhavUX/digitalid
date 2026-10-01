from django.urls import path

from payments.views import (
    OwnerPaymentRefundView,
    PublicPaymentOrderCreateView,
    PublicPaymentStatusView,
    PublicPaymentVerifyView,
    RazorpayWebhookView,
)

# Included under /api/v1/public/booking/
urlpatterns = [
    path(
        "appointments/<str:public_reference>/payment-order/",
        PublicPaymentOrderCreateView.as_view(),
        name="public-booking-payment-order",
    ),
    path(
        "appointments/<str:public_reference>/payment/verify/",
        PublicPaymentVerifyView.as_view(),
        name="public-booking-payment-verify",
    ),
    path(
        "appointments/<str:public_reference>/payment/",
        PublicPaymentStatusView.as_view(),
        name="public-booking-payment-status",
    ),
]

# Included under /api/v1/
owner_urlpatterns = [
    path(
        "businesses/<uuid:business_id>/payments/<uuid:payment_id>/refunds/",
        OwnerPaymentRefundView.as_view(),
        name="owner-payment-refund",
    ),
]

# Included under /api/v1/webhooks/
webhook_urlpatterns = [
    path(
        "payments/razorpay/",
        RazorpayWebhookView.as_view(),
        name="webhook-payments-razorpay",
    ),
]
