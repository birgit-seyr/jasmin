"""Super-admin view layer.

Submodules:
  - ``auth_views``          — JWT login / refresh / logout flow.
  - ``authentication``      — ``SuperAdminJWTAuthentication`` DRF auth class
                              (used as ``authentication_classes = [...]`` on
                              viewsets; not a "view" despite living here, so
                              it keeps no ``_views`` suffix).
  - ``backup_views``        — backup list / trigger RPC endpoints.

The DRF ``viewsets.py`` (TenantManagementViewSet) lives at the
super_admin top level — separate concern, separate file.

Public re-exports below keep ``from apps.shared.super_admin.views
import <symbol>`` working from outside the package without callers
needing to know the submodule split.
"""

from .auth_views import (  # noqa: F401
    SuperAdminRefreshToken,
    super_admin_login_view,
    super_admin_logout_view,
    super_admin_token_refresh_view,
)
from .authentication import SuperAdminJWTAuthentication  # noqa: F401
from .backup_views import (  # noqa: F401
    super_admin_list_backups_view,
    super_admin_trigger_backup_view,
)
