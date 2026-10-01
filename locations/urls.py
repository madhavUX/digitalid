from django.urls import path

from locations.views import LocationDetailView, LocationListCreateView

urlpatterns = [
    path(
        "businesses/<uuid:business_id>/locations/",
        LocationListCreateView.as_view(),
        name="location-list",
    ),
    path(
        "businesses/<uuid:business_id>/locations/<uuid:location_id>/",
        LocationDetailView.as_view(),
        name="location-detail",
    ),
]
