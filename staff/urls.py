from django.urls import path

from staff.views import (
    StaffAvailabilityDetailView,
    StaffAvailabilityListCreateView,
    StaffProfileDetailView,
    StaffProfileListCreateView,
    StaffServiceDetailView,
    StaffServiceListCreateView,
    StaffTimeOffDetailView,
    StaffTimeOffListCreateView,
)

urlpatterns = [
    path(
        "businesses/<uuid:business_id>/staff/",
        StaffProfileListCreateView.as_view(),
        name="staff-list",
    ),
    path(
        "businesses/<uuid:business_id>/staff/<uuid:staff_id>/",
        StaffProfileDetailView.as_view(),
        name="staff-detail",
    ),
    path(
        "businesses/<uuid:business_id>/staff/<uuid:staff_id>/services/",
        StaffServiceListCreateView.as_view(),
        name="staff-service-list",
    ),
    path(
        "businesses/<uuid:business_id>/staff/<uuid:staff_id>/services/<uuid:staff_service_id>/",
        StaffServiceDetailView.as_view(),
        name="staff-service-detail",
    ),
    path(
        "businesses/<uuid:business_id>/staff/<uuid:staff_id>/availability/",
        StaffAvailabilityListCreateView.as_view(),
        name="staff-availability-list",
    ),
    path(
        "businesses/<uuid:business_id>/staff/<uuid:staff_id>/availability/<uuid:availability_id>/",
        StaffAvailabilityDetailView.as_view(),
        name="staff-availability-detail",
    ),
    path(
        "businesses/<uuid:business_id>/staff/<uuid:staff_id>/time-off/",
        StaffTimeOffListCreateView.as_view(),
        name="staff-time-off-list",
    ),
    path(
        "businesses/<uuid:business_id>/staff/<uuid:staff_id>/time-off/<uuid:time_off_id>/",
        StaffTimeOffDetailView.as_view(),
        name="staff-time-off-detail",
    ),
]
