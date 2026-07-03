"""Cell-by-cell matrix for the ``account_status`` transitions allowed
through ``update_user_admin``.

Locks the policy documented in ``apps/accounts/services/user_admin_service.py``
(``_ALLOWED_STATUS_TRANSITIONS`` + the explicit pending-status guard):

  from \\ to        active   inactive   pending_invitation   pending_approval
  active             OK       OK         REJECT (not allowed)  REJECT
  inactive           OK       OK         REJECT                REJECT
  pending_invitation REJECT   REJECT     REJECT                REJECT
  pending_approval   REJECT   REJECT     REJECT                REJECT

If this policy ever changes, update the matrix below — but doing so
should be a deliberate decision, not an accident.
"""

from __future__ import annotations

import pytest

from apps.accounts.errors import AdminUserError
from apps.accounts.services import update_user_admin
from apps.authz.roles import Role
from apps.commissioning.tests.factories import JasminUserFactory

pytestmark = pytest.mark.django_db


_ACTOR_ROLES = [Role.ADMIN]


@pytest.fixture()
def actor(tenant):
    return JasminUserFactory(roles=_ACTOR_ROLES)


# (current_status, new_status, allowed?)
TRANSITIONS = [
    # from active
    ("active", "active", True),
    ("active", "inactive", True),
    ("active", "pending_invitation", False),
    ("active", "pending_approval", False),
    # from inactive
    ("inactive", "active", True),
    ("inactive", "inactive", True),
    ("inactive", "pending_invitation", False),
    ("inactive", "pending_approval", False),
    # from pending_invitation — locked until invitation accepted
    ("pending_invitation", "active", False),
    ("pending_invitation", "inactive", False),
    ("pending_invitation", "pending_invitation", False),
    ("pending_invitation", "pending_approval", False),
    # from pending_approval — locked until office approves via Member flow
    ("pending_approval", "active", False),
    ("pending_approval", "inactive", False),
    ("pending_approval", "pending_invitation", False),
    ("pending_approval", "pending_approval", False),
]


@pytest.mark.parametrize(
    "current, target, allowed",
    TRANSITIONS,
    ids=[f"{c}->{t}={'OK' if a else 'X'}" for c, t, a in TRANSITIONS],
)
def test_account_status_transition(current, target, allowed, tenant, actor):
    user = JasminUserFactory(account_status=current)
    if allowed:
        update_user_admin(user=user, data={"account_status": target}, actor=actor)
        user.refresh_from_db()
        assert user.account_status == target
        # is_active is derived in JasminUser.save() — must follow.
        assert user.is_active is (target == "active")
    else:
        with pytest.raises(AdminUserError):
            update_user_admin(user=user, data={"account_status": target}, actor=actor)
        user.refresh_from_db()
        assert user.account_status == current
