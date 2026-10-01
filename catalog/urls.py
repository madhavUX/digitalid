from django.urls import path

from catalog.views import (
    ServiceCategoryDetailView,
    ServiceCategoryListCreateView,
    ServiceDetailView,
    ServiceListCreateView,
    ServiceLocationDetailView,
    ServiceLocationListCreateView,
)

urlpatterns = [
    path(
        "businesses/<uuid:business_id>/service-categories/",
        ServiceCategoryListCreateView.as_view(),
        name="service-category-list",
    ),
    path(
        "businesses/<uuid:business_id>/service-categories/<uuid:category_id>/",
        ServiceCategoryDetailView.as_view(),
        name="service-category-detail",
    ),
    path(
        "businesses/<uuid:business_id>/services/",
        ServiceListCreateView.as_view(),
        name="service-list",
    ),
    path(
        "businesses/<uuid:business_id>/services/<uuid:service_id>/",
        ServiceDetailView.as_view(),
        name="service-detail",
    ),
    path(
        "businesses/<uuid:business_id>/services/<uuid:service_id>/service-locations/",
        ServiceLocationListCreateView.as_view(),
        name="service-location-list",
    ),
    path(
        "businesses/<uuid:business_id>/services/<uuid:service_id>/service-locations/"
        "<uuid:service_location_id>/",
        ServiceLocationDetailView.as_view(),
        name="service-location-detail",
    ),
]
