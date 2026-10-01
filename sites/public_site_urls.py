from django.urls import path

from sites.public_site_views import PublicSiteDetailView

urlpatterns = [
    path(
        "<slug:slug>/",
        PublicSiteDetailView.as_view(),
        name="public-site-detail",
    ),
]
