"""Role-based DRF permission classes.

Generic, project-agnostic — only depends on `request.user.roles` being an
iterable of role strings (see `apps.authz.roles.Role`). Any consuming app
imports from here and never reaches into a specific user app.

Mirrors the frontend `RoleFlags` shape in `src/shared/auth/useRoles.ts`. Keep
these in sync — backend enforcement must match UI gating exactly.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from rest_framework.permissions import AllowAny, BasePermission

from apps.shared.request_utils import client_ip

from .roles import Role

logger = logging.getLogger("authz")


def _user_roles(request) -> set[str]:
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return set()
    return set(getattr(user, "roles", None) or [])


def has_any_role(request, *roles: str) -> bool:
    """Helper for inline checks inside views/serializers."""
    return bool(_user_roles(request) & set(roles))


class HasAnyRole(BasePermission):
    """Base class — grants access if user has any of `required_roles`."""

    required_roles: Iterable[str] = ()

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        actual = _user_roles(request)
        granted = bool(actual & set(self.required_roles))
        if not granted:
            tenant = getattr(getattr(request, "tenant", None), "schema_name", "-")
            logger.warning(
                "permission.denied user=%s tenant=%s ip=%s path=%s method=%s "
                "required=%s actual=%s view=%s",
                getattr(request.user, "id", "-"),
                tenant,
                client_ip(request),
                request.path,
                request.method,
                sorted(self.required_roles),
                sorted(actual),
                view.__class__.__name__,
            )
        return granted


# --- Role flag classes (kept 1:1 with frontend RoleFlags) ---------------------


class IsOffice(HasAnyRole):
    required_roles = (Role.OFFICE, Role.ADMIN)


class IsManagement(HasAnyRole):
    required_roles = (Role.MANAGEMENT, Role.ADMIN)


class IsAdmin(HasAnyRole):
    required_roles = (Role.ADMIN,)


class IsStaff(HasAnyRole):
    required_roles = (
        Role.GARDENER,
        Role.STAFF,
        Role.OFFICE,
        Role.MANAGEMENT,
        Role.ADMIN,
    )


class IsCustomer(HasAnyRole):
    required_roles = (Role.CUSTOMER, Role.OFFICE, Role.ADMIN)


class IsMember(HasAnyRole):
    required_roles = (Role.MEMBER, Role.OFFICE, Role.ADMIN)


class CanEdit(HasAnyRole):
    required_roles = (Role.GARDENER, Role.OFFICE, Role.ADMIN, Role.STAFF)


# Composite read-side classes: who is allowed to *see* customer-/member-owned
# data. Row-level filtering is the caller's responsibility (see
# `apps.authz.scoping`).
class IsStaffOrCustomer(HasAnyRole):
    required_roles = (
        Role.GARDENER,
        Role.STAFF,
        Role.OFFICE,
        Role.MANAGEMENT,
        Role.ADMIN,
        Role.CUSTOMER,
    )


class IsStaffOrMember(HasAnyRole):
    required_roles = (
        Role.GARDENER,
        Role.STAFF,
        Role.OFFICE,
        Role.MANAGEMENT,
        Role.ADMIN,
        Role.MEMBER,
    )


class IsStaffOrMemberOrCustomer(HasAnyRole):
    # Read-side gate for catalogue endpoints (delivery days, payment
    # cycles, share types) that every authenticated persona — staff,
    # member, or customer — needs to render their own flow.
    required_roles = (
        Role.GARDENER,
        Role.STAFF,
        Role.OFFICE,
        Role.MANAGEMENT,
        Role.ADMIN,
        Role.MEMBER,
        Role.CUSTOMER,
    )


class IsOfficeOrMember(HasAnyRole):
    required_roles = (
        Role.OFFICE,
        Role.ADMIN,
        Role.MEMBER,
    )


class IsOfficeOrCustomer(HasAnyRole):
    required_roles = (
        Role.OFFICE,
        Role.ADMIN,
        Role.CUSTOMER,
    )


# --- Mixin for ModelViewSets --------------------------------------------------


class RolePermissionsMixin:
    """ViewSet mixin that maps DRF actions to permission classes.

    Usage:
        class InvoiceViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
            read_permission = IsStaff
            write_permission = IsOffice

    Read actions (`list`, `retrieve`) require `read_permission`; everything
    else (create / update / partial_update / destroy / custom @action) requires
    `write_permission`. Both default to `IsAuthenticated`. Any classes set on
    the parent (via `permission_classes`) are layered on top.

    Public actions:
        Set ``public_read_actions`` to a set of action names that should be
        accessible to *anyone* (anonymous + authenticated, no role check).
        Use for endpoints that serve content the public needs before login —
        the registration wizard fetching ``ConsentDocument`` text is the
        canonical case. The set may include ``"list"`` / ``"retrieve"`` and
        custom ``@action`` names alike; entries here override
        ``read_permission`` / ``write_permission`` for that action only.

        class ConsentDocumentViewSet(RolePermissionsMixin, ModelViewSet):
            write_permission = IsOffice          # publishing a new version
            public_read_actions = {"list", "retrieve", "current"}
    """

    read_permission: type[BasePermission] | None = None
    write_permission: type[BasePermission] | None = None
    public_read_actions: frozenset[str] = frozenset()
    # Action names to route through ``read_permission`` instead of
    # ``write_permission``. A custom ``@action`` takes the write gate even when
    # it is a read-only GET, which is stricter than the viewset's declared read
    # gate and surfaces as a 403 on a page the role is allowed to open:
    #
    #     class WeeklyPlanViewSet(RolePermissionsMixin, ViewSet):
    #         read_permission = IsStaff
    #         write_permission = IsOffice
    #         read_actions = frozenset({"grid"})
    #
    # Opt-in on purpose, and it must stay that way. On a viewset whose read
    # gate admits members, the strict default is the only thing keeping a
    # read-only GET office-only — four actions in this codebase rely on that,
    # and naming any of them here would hand bulk personal data to member-role
    # callers. Treating every GET as a read would do it wholesale.
    #
    # Unlike ``public_read_actions`` this never opens an action to anonymous
    # callers; it only picks which of the two declared gates applies.
    #
    # A comment rather than a docstring on purpose: drf-spectacular walks the
    # MRO for the first non-DRF class docstring, so prose here would be
    # published as the API description of every viewset lacking one of its own.
    read_actions: frozenset[str] = frozenset()
    _READ_ACTIONS = frozenset({"list", "retrieve"})

    def get_permissions(self):
        action = getattr(self, "action", None)
        if action in self.public_read_actions:
            # Anonymous-friendly short-circuit. We deliberately drop the
            # base permissions instead of layering AllowAny on top —
            # ``permission_classes = [IsAuthenticated]`` on the parent
            # would otherwise still 401 anonymous callers.
            return [AllowAny()]

        base = super().get_permissions()
        is_read = action in self._READ_ACTIONS or action in self.read_actions
        chosen = self.read_permission if is_read else self.write_permission
        return base + ([chosen()] if chosen else [])


# --- Mixin for plain APIView / GenericAPIView ---------------------------------


class APIViewRolePermissionsMixin:
    """APIView mixin that maps HTTP methods to permission classes.

    Same contract as :class:`RolePermissionsMixin` but keyed off
    ``request.method`` instead of the DRF action — use this on plain
    ``APIView`` / ``GenericAPIView`` subclasses where you define
    ``def get`` / ``def post`` / ``def patch`` / ``def delete`` directly.

    Usage:
        class CurrentStockComparisonView(
            APIViewRolePermissionsMixin, APIView
        ):
            read_permission = IsStaff
            write_permission = IsOffice

            def get(self, request): ...
            def patch(self, request, composite_id): ...
            def delete(self, request, composite_id): ...

    GET / HEAD / OPTIONS require ``read_permission``; everything else (POST /
    PUT / PATCH / DELETE) requires ``write_permission``. Both default to
    ``IsAuthenticated``. Any classes set on the parent (via
    ``permission_classes``) are layered on top.
    """

    read_permission: type[BasePermission] | None = None
    write_permission: type[BasePermission] | None = None
    _READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

    def get_permissions(self):
        base = super().get_permissions()
        method = (getattr(self.request, "method", "") or "").upper()
        chosen = (
            self.read_permission
            if method in self._READ_METHODS
            else self.write_permission
        )
        return base + ([chosen()] if chosen else [])
