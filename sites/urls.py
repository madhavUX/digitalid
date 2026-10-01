from django.urls import path

from sites.public_site_views import (
    BusinessWebsitePreviewView,
    BusinessWebsitePublishView,
    BusinessWebsiteStatusView,
    BusinessWebsiteUnpublishView,
)
from sites.views import (
    QuickCardAnalyticsView,
    QuickCardDetailView,
    QuickCardPublishView,
    QuickCardQRView,
    QuickCardUnpublishView,
)

urlpatterns = [
    path(
        "businesses/<uuid:business_id>/locations/<uuid:location_id>/quickcard/",
        QuickCardDetailView.as_view(),
        name="quickcard-detail",
    ),
    path(
        "businesses/<uuid:business_id>/locations/<uuid:location_id>/quickcard/publish/",
        QuickCardPublishView.as_view(),
        name="quickcard-publish",
    ),
    path(
        "businesses/<uuid:business_id>/locations/<uuid:location_id>/quickcard/unpublish/",
        QuickCardUnpublishView.as_view(),
        name="quickcard-unpublish",
    ),
    path(
        "businesses/<uuid:business_id>/locations/<uuid:location_id>/quickcard/qr/",
        QuickCardQRView.as_view(),
        name="quickcard-qr",
    ),
    path(
        "businesses/<uuid:business_id>/quickcard/analytics/",
        QuickCardAnalyticsView.as_view(),
        name="quickcard-analytics",
    ),
    path(
        "businesses/<uuid:business_id>/website/",
        BusinessWebsiteStatusView.as_view(),
        name="business-website-status",
    ),
    path(
        "businesses/<uuid:business_id>/website/preview/",
        BusinessWebsitePreviewView.as_view(),
        name="business-website-preview",
    ),
    path(
        "businesses/<uuid:business_id>/website/publish/",
        BusinessWebsitePublishView.as_view(),
        name="business-website-publish",
    ),
    path(
        "businesses/<uuid:business_id>/website/unpublish/",
        BusinessWebsiteUnpublishView.as_view(),
        name="business-website-unpublish",
    ),
]
