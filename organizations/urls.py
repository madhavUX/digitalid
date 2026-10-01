from django.urls import path

from organizations.views import CurrentOrganizationView, OrganizationMemberListView

urlpatterns = [
    path("organization/", CurrentOrganizationView.as_view(), name="organization-current"),
    path(
        "organization/members/",
        OrganizationMemberListView.as_view(),
        name="organization-members",
    ),
]
