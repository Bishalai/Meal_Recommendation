"""Root URL configuration.

Web pages (HTML) are served from `core.urls.pages` and the JSON API is
mounted under `/api/`.
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
]
