from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import auth_views, backup_views
from .viewsets import OpsChecklistViewSet, TenantManagementViewSet

app_name = "super_admin"

router = DefaultRouter()
router.register(
    "tenants",
    TenantManagementViewSet,
    basename="super-admin-tenants",
)
router.register(
    "ops-checklist",
    OpsChecklistViewSet,
    basename="super-admin-ops-checklist",
)

urlpatterns = [
    # Authentication
    path("auth/login/", auth_views.super_admin_login_view, name="super-admin-login"),
    path("auth/logout/", auth_views.super_admin_logout_view, name="super-admin-logout"),
    path(
        "auth/refresh/",
        auth_views.super_admin_token_refresh_view,
        name="super-admin-refresh",
    ),
    # Step-up authentication. Mirrors the tenant ``/api/auth/step-up/``
    # endpoint; the super-admin variant exists because super-admin
    # auth uses a separate JWT path (``SuperAdminJWTAuthentication``)
    # and the tenant endpoint runs under tenant auth.
    path(
        "auth/step-up/",
        auth_views.super_admin_step_up_view,
        name="super-admin-step-up",
    ),
    # Tenant Management — handled by TenantManagementViewSet:
    #   GET    /tenants/
    #   POST   /tenants/
    #   GET    /tenants/<pk>/
    #   PATCH  /tenants/<pk>/
    #   GET    /tenants/<pk>/users/
    #   GET    /tenants/<pk>/resellers/
    #   POST   /tenants/<pk>/create-admin/
    #   POST   /tenants/<pk>/create-user/
    #   PATCH  /tenants/<pk>/users/<user_id>/roles/
    path("", include(router.urls)),
    # Backup Management (RPC-style — keeps function views)
    path(
        "backups/",
        backup_views.super_admin_list_backups_view,
        name="super-admin-list-backups",
    ),
    path(
        "backups/trigger/",
        backup_views.super_admin_trigger_backup_view,
        name="super-admin-trigger-backup",
    ),
]
