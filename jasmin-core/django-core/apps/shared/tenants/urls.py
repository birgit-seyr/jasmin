from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views
from .viewsets import TenantEmailConfigViewSet, TenantSettingsViewSet, TenantViewSet

router = DefaultRouter()
router.register(r"tenants", TenantViewSet, basename="tenants")
router.register(r"settings", TenantSettingsViewSet, basename="tenant_settings")
router.register(
    r"email_config", TenantEmailConfigViewSet, basename="tenant_email_config"
)


urlpatterns = [
    path("current/", views.CurrentTenantView.as_view(), name="current_tenant"),
    # Web-app install (home-screen / PWA). Both are fetched by the BROWSER, not
    # by the generated API client, and both must stay ABOVE the router include
    # so the catch-all never shadows them.
    path(
        "manifest.webmanifest",
        views.TenantManifestView.as_view(),
        name="tenant_manifest",
    ),
    path(
        "app-icon.png",
        views.TenantAppIconView.as_view(),
        name="tenant_app_icon",
    ),
    path("", include(router.urls)),
]
