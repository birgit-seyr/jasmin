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
    path("", include(router.urls)),
]
