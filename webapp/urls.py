"""URL configuration; feature endpoints are added in later plan tasks."""

from django.urls import include, path

urlpatterns = [path("api/v1/", include("dashboard.api.urls"))]
