from django.contrib import admin
from django.urls import include, path

from core.health import live, ready

urlpatterns = [
    path("health/live/", live, name="health-live"),
    path("health/ready/", ready, name="health-ready"),
    path("admin/", admin.site.urls),
    path("api/v1/", include("api.v1.urls")),
]
