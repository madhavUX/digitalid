from django.urls import path

from sites.views import PublicQuickCardDetailView, PublicQuickCardEventView

urlpatterns = [
    path(
        "<slug:slug>/events/",
        PublicQuickCardEventView.as_view(),
        name="public-quickcard-events",
    ),
    path(
        "<slug:slug>/",
        PublicQuickCardDetailView.as_view(),
        name="public-quickcard-detail",
    ),
]
