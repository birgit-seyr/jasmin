"""Super-admin support routes — mounted in config/public_urls.py under
``/api/super-admin/`` so they inherit the super-admin IP allowlist (a path-prefix
match) and stay OUT of the tenant schema.yml. SimpleRouter (no API-root view) to
avoid a second api-root under the shared ``/api/super-admin/`` prefix."""

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .admin_viewsets import SupportTicketAdminViewSet

app_name = "support_admin"

router = SimpleRouter()
router.register(
    "support-tickets",
    SupportTicketAdminViewSet,
    basename="super-admin-support-ticket",
)

urlpatterns = [path("", include(router.urls))]
