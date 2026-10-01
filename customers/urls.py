from django.urls import path

from customers.views import (
    CustomerDetailView,
    CustomerListCreateView,
    CustomerRetentionSettingsView,
    CustomerRetentionSummaryView,
    CustomerTagAssignmentDetailView,
    CustomerTagAssignmentListCreateView,
    CustomerTagDetailView,
    CustomerTagListCreateView,
)

urlpatterns = [
    path(
        "businesses/<uuid:business_id>/customers/",
        CustomerListCreateView.as_view(),
        name="customer-list",
    ),
    path(
        "businesses/<uuid:business_id>/customers/<uuid:customer_id>/",
        CustomerDetailView.as_view(),
        name="customer-detail",
    ),
    path(
        "businesses/<uuid:business_id>/customers/<uuid:customer_id>/retention-summary/",
        CustomerRetentionSummaryView.as_view(),
        name="customer-retention-summary",
    ),
    path(
        "businesses/<uuid:business_id>/retention-settings/",
        CustomerRetentionSettingsView.as_view(),
        name="customer-retention-settings",
    ),
    path(
        "businesses/<uuid:business_id>/customer-tags/",
        CustomerTagListCreateView.as_view(),
        name="customer-tag-list",
    ),
    path(
        "businesses/<uuid:business_id>/customer-tags/<uuid:tag_id>/",
        CustomerTagDetailView.as_view(),
        name="customer-tag-detail",
    ),
    path(
        "businesses/<uuid:business_id>/customers/<uuid:customer_id>/tags/",
        CustomerTagAssignmentListCreateView.as_view(),
        name="customer-tag-assignment-list",
    ),
    path(
        "businesses/<uuid:business_id>/customers/<uuid:customer_id>/tags/<uuid:assignment_id>/",
        CustomerTagAssignmentDetailView.as_view(),
        name="customer-tag-assignment-detail",
    ),
]
