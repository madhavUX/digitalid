from django.urls import path

from businesses.google_views import (
    GoogleBusinessAccountsView,
    GoogleBusinessConnectionView,
    GoogleBusinessDisconnectView,
    GoogleBusinessLocationsView,
    GoogleBusinessSelectLocationView,
    GoogleBusinessSyncUrlView,
    GoogleOAuthCallbackView,
)
from businesses.launch_views import BusinessLaunchProfileView
from businesses.setup_views import BusinessDashboardView, BusinessSetupStatusView
from businesses.views import BusinessDetailView, BusinessListCreateView

urlpatterns = [
    path("businesses/", BusinessListCreateView.as_view(), name="business-list"),
    path("businesses/<uuid:business_id>/", BusinessDetailView.as_view(), name="business-detail"),
    path(
        "businesses/<uuid:business_id>/setup/",
        BusinessSetupStatusView.as_view(),
        name="business-setup",
    ),
    path(
        "businesses/<uuid:business_id>/dashboard/",
        BusinessDashboardView.as_view(),
        name="business-dashboard",
    ),
    path(
        "businesses/<uuid:business_id>/launch-profile/",
        BusinessLaunchProfileView.as_view(),
        name="business-launch-profile",
    ),
    path(
        "businesses/google/callback/",
        GoogleOAuthCallbackView.as_view(),
        name="business-google-oauth-callback",
    ),
    path(
        "businesses/<uuid:business_id>/locations/<uuid:location_id>/google/",
        GoogleBusinessConnectionView.as_view(),
        name="business-location-google",
    ),
    path(
        "businesses/<uuid:business_id>/locations/<uuid:location_id>/google/accounts/",
        GoogleBusinessAccountsView.as_view(),
        name="business-location-google-accounts",
    ),
    path(
        "businesses/<uuid:business_id>/locations/<uuid:location_id>/google/locations/",
        GoogleBusinessLocationsView.as_view(),
        name="business-location-google-locations",
    ),
    path(
        "businesses/<uuid:business_id>/locations/<uuid:location_id>/google/select-location/",
        GoogleBusinessSelectLocationView.as_view(),
        name="business-location-google-select-location",
    ),
    path(
        "businesses/<uuid:business_id>/locations/<uuid:location_id>/google/disconnect/",
        GoogleBusinessDisconnectView.as_view(),
        name="business-location-google-disconnect",
    ),
    path(
        "businesses/<uuid:business_id>/locations/<uuid:location_id>/google/sync-url/",
        GoogleBusinessSyncUrlView.as_view(),
        name="business-location-google-sync-url",
    ),
]
