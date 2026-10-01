from django.urls import path

from booking.plan_views import BookingPlanListView
from booking.views import (
    AppointmentCancelView,
    AppointmentDetailView,
    AppointmentListCreateView,
    LocationAvailabilityView,
)

urlpatterns = [
    path(
        "businesses/<uuid:business_id>/locations/<uuid:location_id>/availability/",
        LocationAvailabilityView.as_view(),
        name="location-availability",
    ),
    path(
        "businesses/<uuid:business_id>/appointments/",
        AppointmentListCreateView.as_view(),
        name="appointment-list",
    ),
    path(
        "businesses/<uuid:business_id>/appointments/<uuid:appointment_id>/",
        AppointmentDetailView.as_view(),
        name="appointment-detail",
    ),
    path(
        "businesses/<uuid:business_id>/appointments/<uuid:appointment_id>/cancel/",
        AppointmentCancelView.as_view(),
        name="appointment-cancel",
    ),
    path(
        "businesses/<uuid:business_id>/booking-plans/",
        BookingPlanListView.as_view(),
        name="booking-plan-list",
    ),
]
