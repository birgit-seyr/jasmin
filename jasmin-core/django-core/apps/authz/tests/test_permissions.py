"""Tests for `apps.authz.permissions` — DRF permission classes and the
RolePermissionsMixin used across the platform's viewsets.

We use APIRequestFactory + a stub view object instead of routing through
URLs, since the classes only depend on ``request.user.roles``.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import AnonymousUser
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.test import APIRequestFactory

from apps.authz.permissions import (
    CanEdit,
    HasAnyRole,
    IsAdmin,
    IsCustomer,
    IsGardener,
    IsManagement,
    IsMember,
    IsOffice,
    IsStaff,
    IsStaffOrCustomer,
    IsStaffOrMember,
    RolePermissionsMixin,
    has_any_role,
)
from apps.authz.roles import Role
from apps.commissioning.tests.factories import JasminUserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def rf():
    return APIRequestFactory()


def _request(rf, user):
    req = rf.get("/some/path/")
    req.user = user
    return req


# --------------------------------------------------------------------------- #
# has_any_role helper                                                          #
# --------------------------------------------------------------------------- #


class TestHasAnyRole:
    def test_anonymous_returns_false(self, tenant, rf):
        req = _request(rf, AnonymousUser())
        assert has_any_role(req, Role.OFFICE) is False

    def test_no_user_attr_returns_false(self, tenant, rf):
        req = rf.get("/")
        if hasattr(req, "user"):
            delattr(req, "user")
        assert has_any_role(req, Role.OFFICE) is False

    def test_user_with_role_returns_true(self, tenant, rf):
        u = JasminUserFactory(roles=[Role.OFFICE])
        assert has_any_role(_request(rf, u), Role.OFFICE) is True

    def test_user_without_role_returns_false(self, tenant, rf):
        u = JasminUserFactory(roles=[Role.STAFF])
        assert has_any_role(_request(rf, u), Role.OFFICE) is False

    def test_any_of_multiple_roles_matches(self, tenant, rf):
        u = JasminUserFactory(roles=[Role.GARDENER])
        assert has_any_role(_request(rf, u), Role.OFFICE, Role.GARDENER) is True


# --------------------------------------------------------------------------- #
# Role flag classes — happy / sad path matrix                                  #
# --------------------------------------------------------------------------- #


# Each row: (PermissionClass, list-of-allowed-roles, list-of-rejected-roles)
PERMISSION_MATRIX = [
    (
        IsOffice,
        [Role.OFFICE, Role.ADMIN],
        [Role.STAFF, Role.MEMBER, Role.CUSTOMER, Role.GARDENER],
    ),
    (IsGardener, [Role.GARDENER, Role.ADMIN], [Role.OFFICE, Role.STAFF, Role.MEMBER]),
    (IsManagement, [Role.MANAGEMENT, Role.ADMIN], [Role.OFFICE, Role.STAFF]),
    (
        IsAdmin,
        [Role.ADMIN],
        [Role.OFFICE, Role.STAFF, Role.MANAGEMENT, Role.GARDENER, Role.MEMBER],
    ),
    (
        IsStaff,
        [Role.GARDENER, Role.STAFF, Role.OFFICE, Role.MANAGEMENT, Role.ADMIN],
        [Role.MEMBER, Role.CUSTOMER],
    ),
    (
        IsCustomer,
        [Role.CUSTOMER, Role.OFFICE, Role.ADMIN],
        [Role.STAFF, Role.MEMBER, Role.GARDENER],
    ),
    (
        IsMember,
        [Role.MEMBER, Role.OFFICE, Role.ADMIN],
        [Role.STAFF, Role.CUSTOMER, Role.GARDENER],
    ),
    (
        CanEdit,
        [Role.GARDENER, Role.OFFICE, Role.ADMIN, Role.STAFF],
        [Role.MEMBER, Role.MANAGEMENT],
    ),
    (
        IsStaffOrCustomer,
        [
            Role.GARDENER,
            Role.STAFF,
            Role.OFFICE,
            Role.MANAGEMENT,
            Role.ADMIN,
            Role.CUSTOMER,
        ],
        [Role.MEMBER],
    ),
    (
        IsStaffOrMember,
        [
            Role.GARDENER,
            Role.STAFF,
            Role.OFFICE,
            Role.MANAGEMENT,
            Role.ADMIN,
            Role.MEMBER,
        ],
        [Role.CUSTOMER],
    ),
]


@pytest.mark.parametrize("perm_cls,allowed,rejected", PERMISSION_MATRIX)
class TestPermissionClasses:
    def test_anonymous_is_rejected(self, tenant, rf, perm_cls, allowed, rejected):
        perm = perm_cls()
        assert perm.has_permission(_request(rf, AnonymousUser()), object()) is False

    def test_allowed_roles_pass(self, tenant, rf, perm_cls, allowed, rejected):
        perm = perm_cls()
        for role in allowed:
            u = JasminUserFactory(roles=[role])
            assert (
                perm.has_permission(_request(rf, u), object()) is True
            ), f"{perm_cls.__name__} should grant {role}"

    def test_rejected_roles_fail(self, tenant, rf, perm_cls, allowed, rejected):
        perm = perm_cls()
        for role in rejected:
            # `member` only auto-attaches if linked to a Member, so it's safe.
            u = JasminUserFactory(roles=[role])
            assert (
                perm.has_permission(_request(rf, u), object()) is False
            ), f"{perm_cls.__name__} should reject {role}"

    def test_user_with_no_roles_is_rejected(
        self, tenant, rf, perm_cls, allowed, rejected
    ):
        perm = perm_cls()
        u = JasminUserFactory(roles=[])
        assert perm.has_permission(_request(rf, u), object()) is False


# --------------------------------------------------------------------------- #
# Custom subclass behaviour                                                    #
# --------------------------------------------------------------------------- #


class TestHasAnyRoleSubclassing:
    def test_empty_required_roles_rejects_all(self, tenant, rf):
        class Nobody(HasAnyRole):
            required_roles = ()

        u = JasminUserFactory(roles=[Role.ADMIN])
        assert Nobody().has_permission(_request(rf, u), object()) is False

    def test_subclass_with_custom_role(self, tenant, rf):
        class IsGardenerOnly(HasAnyRole):
            required_roles = (Role.GARDENER,)

        u_ok = JasminUserFactory(roles=[Role.GARDENER])
        u_no = JasminUserFactory(roles=[Role.ADMIN])
        assert IsGardenerOnly().has_permission(_request(rf, u_ok), object()) is True
        assert IsGardenerOnly().has_permission(_request(rf, u_no), object()) is False


# --------------------------------------------------------------------------- #
# RolePermissionsMixin                                                         #
# --------------------------------------------------------------------------- #


class _StubViewSet(RolePermissionsMixin, viewsets.ViewSet):
    permission_classes = [IsAuthenticated]
    read_permission = IsStaff
    write_permission = IsOffice


class TestRolePermissionsMixin:
    @pytest.mark.parametrize("action", ["list", "retrieve"])
    def test_read_actions_use_read_permission(self, action):
        vs = _StubViewSet()
        vs.action = action
        perms = vs.get_permissions()
        kinds = {type(p).__name__ for p in perms}
        assert "IsAuthenticated" in kinds
        assert "IsStaff" in kinds
        assert "IsOffice" not in kinds

    @pytest.mark.parametrize(
        "action",
        ["create", "update", "partial_update", "destroy", "custom_action"],
    )
    def test_write_actions_use_write_permission(self, action):
        vs = _StubViewSet()
        vs.action = action
        perms = vs.get_permissions()
        kinds = {type(p).__name__ for p in perms}
        assert "IsAuthenticated" in kinds
        assert "IsOffice" in kinds
        assert "IsStaff" not in kinds

    def test_no_action_falls_through_to_write(self):
        vs = _StubViewSet()
        vs.action = None
        kinds = {type(p).__name__ for p in vs.get_permissions()}
        # `None` is not in `_READ_ACTIONS`, so write_permission applies.
        assert "IsOffice" in kinds

    def test_missing_permissions_attrs_fall_back_to_base_only(self):
        class BareViewSet(RolePermissionsMixin, viewsets.ViewSet):
            permission_classes = [IsAuthenticated]

        vs = BareViewSet()
        vs.action = "list"
        kinds = {type(p).__name__ for p in vs.get_permissions()}
        assert kinds == {"IsAuthenticated"}

    def test_end_to_end_office_can_write_staff_can_read(self, tenant, rf):
        write_perm = _StubViewSet().write_permission()
        read_perm = _StubViewSet().read_permission()
        office = JasminUserFactory(roles=[Role.OFFICE])
        staff = JasminUserFactory(roles=[Role.STAFF])
        assert write_perm.has_permission(_request(rf, office), object()) is True
        assert write_perm.has_permission(_request(rf, staff), object()) is False
        assert read_perm.has_permission(_request(rf, staff), object()) is True
