from django.urls import path

from locations.public_views import (
    PublicLocationCategoriesView,
    PublicLocationDetailView,
    PublicLocationServiceDetailView,
    PublicLocationServicesView,
    PublicLocationStaffView,
)

urlpatterns = [
    path(
        "<slug:slug>/",
        PublicLocationDetailView.as_view(),
        name="public-location-detail",
    ),
    path(
        "<slug:slug>/services/",
        PublicLocationServicesView.as_view(),
        name="public-location-services",
    ),
    path(
        "<slug:slug>/services/<str:service_identifier>/",
        PublicLocationServiceDetailView.as_view(),
        name="public-location-service-detail",
    ),
    path(
        "<slug:slug>/categories/",
        PublicLocationCategoriesView.as_view(),
        name="public-location-categories",
    ),
    path(
        "<slug:slug>/staff/",
        PublicLocationStaffView.as_view(),
        name="public-location-staff",
    ),
]
