"""Role × permission matrix tests for ``apps.authz.permissions``.

These lock in *which* roles each ``HasAnyRole`` subclass admits.
A regression here (e.g. accidentally swapping ``IsStaff`` and ``IsOffice``)
would silently widen or narrow access across many viewsets at once, so we
parametrise the full matrix and assert one cell at a time.
"""

from __future__ import annotations

import pytest
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
    has_any_role,
)
from apps.authz.roles import Role


class _FakeUser:
    """Minimal stand-in for a DRF auth user — avoids the Tenant + DB."""

    is_authenticated = True

    def __init__(self, roles):
        self.roles = list(roles or [])
        self.id = 1


class _AnonUser:
    is_authenticated = False
    roles = []
    id = None


def _request(user, *, path="/x"):
    rf = APIRequestFactory()
    req = rf.get(path)
    req.user = user
    return req


# Single-source-of-truth expectation table. Each entry is
# (PermissionClass, set_of_roles_that_must_be_granted).
EXPECTED_GRANTS: list[tuple[type[HasAnyRole], set[str]]] = [
    (IsOffice, {Role.OFFICE, Role.ADMIN}),
    (IsGardener, {Role.GARDENER, Role.ADMIN}),
    (IsManagement, {Role.MANAGEMENT, Role.ADMIN}),
    (IsAdmin, {Role.ADMIN}),
    (
        IsStaff,
        {Role.GARDENER, Role.STAFF, Role.OFFICE, Role.MANAGEMENT, Role.ADMIN},
    ),
    (IsCustomer, {Role.CUSTOMER, Role.OFFICE, Role.ADMIN}),
    (IsMember, {Role.MEMBER, Role.OFFICE, Role.ADMIN}),
    (CanEdit, {Role.GARDENER, Role.OFFICE, Role.ADMIN, Role.STAFF}),
    (
        IsStaffOrCustomer,
        {
            Role.GARDENER,
            Role.STAFF,
            Role.OFFICE,
            Role.MANAGEMENT,
            Role.ADMIN,
            Role.CUSTOMER,
        },
    ),
    (
        IsStaffOrMember,
        {
            Role.GARDENER,
            Role.STAFF,
            Role.OFFICE,
            Role.MANAGEMENT,
            Role.ADMIN,
            Role.MEMBER,
        },
    ),
]

ALL_ROLES = {
    Role.GARDENER,
    Role.OFFICE,
    Role.STAFF,
    Role.MANAGEMENT,
    Role.MEMBER,
    Role.ADMIN,
    Role.CUSTOMER,
}


@pytest.mark.parametrize("perm_cls,allowed_roles", EXPECTED_GRANTS)
def test_permission_grants_only_expected_roles(perm_cls, allowed_roles):
    """Each role with that permission gets True; every other role gets False."""
    perm = perm_cls()
    for role in ALL_ROLES:
        req = _request(_FakeUser(roles=[role]))
        granted = perm.has_permission(req, view=object())
        if role in allowed_roles:
            assert granted is True, f"{perm_cls.__name__} should ADMIT role={role!r}"
        else:
            assert granted is False, f"{perm_cls.__name__} should DENY role={role!r}"


@pytest.mark.parametrize("perm_cls,_", EXPECTED_GRANTS)
def test_anonymous_user_is_always_denied(perm_cls, _):
    perm = perm_cls()
    req = _request(_AnonUser())
    assert perm.has_permission(req, view=object()) is False


@pytest.mark.parametrize("perm_cls,_", EXPECTED_GRANTS)
def test_user_with_no_roles_is_always_denied(perm_cls, _):
    perm = perm_cls()
    req = _request(_FakeUser(roles=[]))
    assert perm.has_permission(req, view=object()) is False


def test_admin_role_admits_to_every_permission():
    """Admin is the universal master — must satisfy every Is* class."""
    req = _request(_FakeUser(roles=[Role.ADMIN]))
    for perm_cls, _ in EXPECTED_GRANTS:
        assert (
            perm_cls().has_permission(req, view=object()) is True
        ), f"ADMIN must satisfy {perm_cls.__name__}"


def test_has_any_role_helper():
    req_admin = _request(_FakeUser(roles=[Role.ADMIN]))
    req_member = _request(_FakeUser(roles=[Role.MEMBER]))
    req_anon = _request(_AnonUser())

    assert has_any_role(req_admin, Role.OFFICE, Role.ADMIN) is True
    assert has_any_role(req_member, Role.OFFICE, Role.ADMIN) is False
    assert has_any_role(req_anon, Role.OFFICE, Role.ADMIN) is False
