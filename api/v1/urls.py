from django.urls import include, path

from payments.urls import owner_urlpatterns as payment_owner_urls
from payments.urls import webhook_urlpatterns as payment_webhook_urls
from sites.views import PublicQuickCardDetailView

urlpatterns = [
    path("", include("accounts.urls")),
    path("", include("organizations.urls")),
    path("", include("businesses.urls")),
    path("", include("locations.urls")),
    path("", include("catalog.urls")),
    path("", include("staff.urls")),
    path("", include("customers.urls")),
    path("", include("booking.urls")),
    path("public/booking/", include("booking.public_urls")),
    path("public/booking/", include("payments.urls")),
    path("public/locations/", include("locations.public_urls")),
    path("public/quickcards/", include("sites.public_urls")),
    path(
        "public/q/<slug:slug>/",
        PublicQuickCardDetailView.as_view(),
        name="public-quickcard-alias",
    ),
    path("public/sites/", include("sites.public_site_urls")),
    path("webhooks/", include("booking.webhook_urls")),
    path("webhooks/", include((payment_webhook_urls, "payments"), namespace="payments-webhooks")),
    path("", include("sites.urls")),
    path("", include("messaging.urls")),
    path("", include((payment_owner_urls, "payments"), namespace="payments-owner")),
]
