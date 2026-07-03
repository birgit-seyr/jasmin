import logging

from rest_framework.permissions import BasePermission

logger = logging.getLogger("super_admin")


class IsSuperAdmin(BasePermission):
    """
    Permission class to check if user is a super admin.
    Checks the is_super_admin flag in the JWT token payload.

    NOTE: DRF calls has_permission() multiple times per request (once per
    permission class, plus during schema introspection). We therefore log
    only DENIES, not grants — grants are implicit in the request log line.
    """

    def has_permission(self, request, view):
        # Check if user is authenticated
        if not request.user or not request.user.is_authenticated:
            logger.warning(
                "superadmin.permission.denied path=%s reason=not_authenticated",
                request.path,
            )
            return False

        # Check if user has super admin flag from JWT token
        if not getattr(request.user, "is_super_admin", False):
            logger.warning(
                "superadmin.permission.denied user=%s path=%s reason=not_superadmin",
                getattr(request.user, "email", "-"),
                request.path,
            )
            return False

        return True
