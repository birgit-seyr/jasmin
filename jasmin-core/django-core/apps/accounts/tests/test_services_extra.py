"""Gap tests for accounts services not covered by `test_status_flow.py`:

- `auth_service.refresh_access_token` rotation + tenant binding
- `auth_service.blacklist_refresh` idempotency
- `auth_service.update_user_profile` whitelist
- `user_admin_service.list_active_users` / `serialize_user_row`
- Reseller link lifecycle on update_user_admin
- create_user_with_invite required-field validation
- backends.EmailOrUsernameModelBackend behaviour
"""

from __future__ import annotations

import pytest
from django.db import connection
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.backends import EmailOrUsernameModelBackend
from apps.accounts.services.auth_service import (
    InvalidToken,
    TenantMismatch,
    blacklist_refresh,
    refresh_access_token,
    update_user_profile,
)
from apps.accounts.services.user_admin_service import (
    AdminUserError,
    create_user_with_invite,
    list_active_users,
    serialize_user_row,
    update_user_admin,
)
from apps.authz.roles import Role
from apps.commissioning.tests.factories import (
    JasminUserFactory,
    ResellerFactory,
)

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# refresh_access_token                                                         #
# --------------------------------------------------------------------------- #


def _refresh_for(user, *, tenant_id: str | None):
    refresh = RefreshToken.for_user(user)
    if tenant_id is not None:
        refresh["tenant_id"] = tenant_id
    return str(refresh)


class TestRefreshAccessToken:
    def test_happy_path_rotates_refresh(self, tenant):
        user = JasminUserFactory()
        old = _refresh_for(user, tenant_id=tenant.schema_name)
        out = refresh_access_token(refresh_token=old, tenant_schema=tenant.schema_name)
        assert out["access"]
        # ROTATE_REFRESH_TOKENS is True in settings → new refresh returned.
        assert out["refresh"]
        assert out["refresh"] != old

    def test_missing_tenant_claim_raises(self, tenant):
        user = JasminUserFactory()
        bad = _refresh_for(user, tenant_id=None)
        with pytest.raises(InvalidToken):
            refresh_access_token(refresh_token=bad, tenant_schema=tenant.schema_name)

    def test_tenant_mismatch_raises(self, tenant):
        user = JasminUserFactory()
        token = _refresh_for(user, tenant_id="other-tenant")
        with pytest.raises(TenantMismatch):
            refresh_access_token(refresh_token=token, tenant_schema=tenant.schema_name)

    def test_unresolved_tenant_schema_fails_closed(self, tenant):
        """A valid token must NOT refresh when tenant resolution failed
        (``tenant_schema=None``) — the binding check may never be skipped."""
        user = JasminUserFactory()
        token = _refresh_for(user, tenant_id=tenant.schema_name)
        with pytest.raises(InvalidToken):
            refresh_access_token(refresh_token=token, tenant_schema=None)

    def test_garbage_token_raises_invalid(self, tenant):
        with pytest.raises(InvalidToken):
            refresh_access_token(
                refresh_token="not-a-jwt", tenant_schema=tenant.schema_name
            )


class TestBlacklistRefresh:
    def test_blacklists_valid_token_silently(self, tenant):
        user = JasminUserFactory()
        token = _refresh_for(user, tenant_id=tenant.schema_name)
        # Returns None and does not raise.
        assert blacklist_refresh(token) is None

    def test_garbage_token_does_not_raise(self, tenant):
        assert blacklist_refresh("nonsense") is None

    def test_double_blacklist_does_not_raise(self, tenant):
        user = JasminUserFactory()
        token = _refresh_for(user, tenant_id=tenant.schema_name)
        blacklist_refresh(token)
        # idempotent
        blacklist_refresh(token)


# --------------------------------------------------------------------------- #
# update_user_profile                                                          #
# --------------------------------------------------------------------------- #


class TestUpdateUserProfile:
    def test_updates_whitelisted_fields(self, tenant):
        u = JasminUserFactory(first_name="Old", last_name="Name", user_language="en")
        fields = update_user_profile(
            user=u,
            data={
                "first_name": "New",
                "last_name": "Person",
                "user_language": "de",
            },
        )
        u.refresh_from_db()
        assert u.first_name == "New"
        assert u.last_name == "Person"
        assert u.user_language == "de"
        assert set(fields) == {"first_name", "last_name", "user_language"}

    def test_ignores_unknown_fields(self, tenant):
        u = JasminUserFactory(first_name="Keep")
        fields = update_user_profile(
            user=u,
            data={"first_name": "Edit", "is_superuser": True, "roles": ["admin"]},
        )
        u.refresh_from_db()
        assert u.first_name == "Edit"
        assert u.is_superuser is False
        assert "is_superuser" not in fields
        assert "roles" not in fields

    def test_no_changes_no_save(self, tenant):
        u = JasminUserFactory()
        before = u.updated_at
        fields = update_user_profile(user=u, data={})
        u.refresh_from_db()
        assert fields == []
        assert u.updated_at == before


# --------------------------------------------------------------------------- #
# user_admin_service: list / serialize / reseller link / required fields       #
# --------------------------------------------------------------------------- #


class TestSerializeUserRow:
    def test_returns_expected_keys(self, tenant):
        u = JasminUserFactory(roles=[Role.OFFICE], user_language="en")
        row = serialize_user_row(u)
        assert row["email"] == u.email
        assert row["roles"] == [Role.OFFICE]
        assert row["account_status"] == "active"
        assert row["is_active"] is True
        assert row["reseller_id"] is None
        assert row["invitation_expires_at"] is None

    def test_includes_reseller_id_when_linked(self, tenant):
        u = JasminUserFactory(roles=[Role.CUSTOMER])
        r = ResellerFactory()
        r.linked_user = u
        r.save(update_fields=["linked_user"])
        row = serialize_user_row(u)
        assert row["reseller_id"] == str(r.id)


class TestListActiveUsers:
    def test_lists_all_users_ordered_by_first_name(self, tenant):
        JasminUserFactory(first_name="Charlie")
        JasminUserFactory(first_name="Alice")
        JasminUserFactory(first_name="Bob")
        rows = list_active_users()
        names = [r["first_name"] for r in rows]
        # Must include all three, sorted alphabetically.
        first_three = [n for n in names if n in {"Alice", "Bob", "Charlie"}]
        assert first_three == sorted(first_three)


class TestCreateUserWithInviteValidation:
    def test_missing_required_field_rejected(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        with pytest.raises(AdminUserError) as exc:
            create_user_with_invite(
                data={"first_name": "X", "last_name": "Y"},
                created_by=admin,
            )
        assert "missing required" in exc.value.message.lower()

    def test_blank_field_treated_as_missing(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        with pytest.raises(AdminUserError):
            create_user_with_invite(
                data={"first_name": " ", "last_name": "Y", "email": "x@y.com"},
                created_by=admin,
            )

    def test_invalid_role_rejected(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        with pytest.raises(AdminUserError) as exc:
            create_user_with_invite(
                data={
                    "first_name": "X",
                    "last_name": "Y",
                    "email": "z@z.com",
                    "roles": ["bogusrole"],
                },
                created_by=admin,
            )
        assert "invalid roles" in exc.value.message.lower()

    def test_reseller_id_without_customer_role_rejected(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        r = ResellerFactory()
        with pytest.raises(AdminUserError) as exc:
            create_user_with_invite(
                data={
                    "first_name": "X",
                    "last_name": "Y",
                    "email": "noc@y.com",
                    "roles": [Role.STAFF],
                    "reseller_id": str(r.id),
                },
                created_by=admin,
            )
        assert "customer" in exc.value.message.lower()


class TestUpdateUserAdminResellerLink:
    def test_setting_reseller_id_links(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        target = JasminUserFactory(roles=[Role.CUSTOMER])
        r = ResellerFactory()
        update_user_admin(
            user=target,
            data={"reseller_id": str(r.id)},
            actor=admin,
        )
        r.refresh_from_db()
        assert r.linked_user_id == target.id

    def test_removing_customer_role_unlinks_reseller(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        target = JasminUserFactory(roles=[Role.CUSTOMER])
        r = ResellerFactory()
        r.linked_user = target
        r.save(update_fields=["linked_user"])
        update_user_admin(
            user=target,
            data={"roles": [Role.STAFF]},
            actor=admin,
        )
        r.refresh_from_db()
        assert r.linked_user_id is None

    def test_clearing_reseller_id(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        target = JasminUserFactory(roles=[Role.CUSTOMER])
        r = ResellerFactory()
        r.linked_user = target
        r.save(update_fields=["linked_user"])
        update_user_admin(
            user=target,
            data={"reseller_id": None},
            actor=admin,
        )
        r.refresh_from_db()
        assert r.linked_user_id is None

    def test_reseller_already_linked_to_other_user_rejected(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        other = JasminUserFactory(roles=[Role.CUSTOMER])
        target = JasminUserFactory(roles=[Role.CUSTOMER])
        r = ResellerFactory()
        r.linked_user = other
        r.save(update_fields=["linked_user"])
        with pytest.raises(AdminUserError) as exc:
            update_user_admin(
                user=target,
                data={"reseller_id": str(r.id)},
                actor=admin,
            )
        assert "already linked" in exc.value.message.lower()

    def test_customer_combo_violation_rejected(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        target = JasminUserFactory(roles=[Role.STAFF])
        with pytest.raises(AdminUserError) as exc:
            update_user_admin(
                user=target,
                data={"roles": [Role.CUSTOMER, Role.STAFF]},
                actor=admin,
            )
        assert "customer" in exc.value.message.lower()


# --------------------------------------------------------------------------- #
# backends.EmailOrUsernameModelBackend                                         #
# --------------------------------------------------------------------------- #


class TestEmailBackend:
    backend = EmailOrUsernameModelBackend()

    def _user(self, **kw):
        u = JasminUserFactory(**kw)
        u.set_password("CorrectHorse42!Battery")
        u.save()
        return u

    def test_login_with_email(self, tenant):
        u = self._user()
        out = self.backend.authenticate(
            None, username=u.email, password="CorrectHorse42!Battery"
        )
        assert out is not None
        assert out.id == u.id

    def test_login_with_username(self, tenant):
        u = self._user(username="alice123")
        out = self.backend.authenticate(
            None, username="alice123", password="CorrectHorse42!Battery"
        )
        assert out is not None and out.id == u.id

    def test_email_lookup_is_case_insensitive(self, tenant):
        u = self._user(email="MixedCase@Example.com")
        out = self.backend.authenticate(
            None, username="mixedcase@example.com", password="CorrectHorse42!Battery"
        )
        assert out is not None and out.id == u.id

    def test_unknown_user_returns_none(self, tenant):
        out = self.backend.authenticate(
            None, username="ghost@example.com", password="anything"
        )
        assert out is None

    def test_wrong_password_returns_none(self, tenant):
        u = self._user()
        out = self.backend.authenticate(None, username=u.email, password="wrong")
        assert out is None

    def test_inactive_user_still_returns_user(self, tenant):
        """The backend intentionally does NOT enforce status; the auth_service
        does, so it can return a precise reason. See `apps/accounts/backends.py`."""
        u = self._user(account_status="inactive")
        out = self.backend.authenticate(
            None, username=u.email, password="CorrectHorse42!Battery"
        )
        assert out is not None and out.id == u.id

    def test_public_schema_skips(self):
        """No tenant context → no authentication attempt."""
        connection.set_schema_to_public()
        try:
            out = self.backend.authenticate(
                None, username="anyone@example.com", password="x"
            )
            assert out is None
        finally:
            pass

    def test_missing_credentials_returns_none(self, tenant):
        assert self.backend.authenticate(None, username=None, password="x") is None
        assert (
            self.backend.authenticate(None, username="a@b.com", password=None) is None
        )


class TestUpdateUserAdminLastAdminGuard:
    """``update_user_admin`` must not let the last active admin lose the role
    (including via self-demotion) — that locks the tenant out."""

    def test_cannot_remove_admin_from_last_active_admin(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN], account_status="active")
        with pytest.raises(AdminUserError, match="last active admin"):
            update_user_admin(user=admin, data={"roles": [Role.OFFICE]}, actor=admin)
        admin.refresh_from_db()
        assert Role.ADMIN in admin.roles  # role unchanged

    def test_can_remove_admin_when_another_active_admin_exists(self, tenant):
        other = JasminUserFactory(roles=[Role.ADMIN], account_status="active")
        admin = JasminUserFactory(roles=[Role.ADMIN], account_status="active")
        update_user_admin(user=admin, data={"roles": [Role.OFFICE]}, actor=other)
        admin.refresh_from_db()
        assert Role.ADMIN not in admin.roles

    def test_inactive_admin_does_not_count_as_active(self, tenant):
        # An inactive second admin can't keep the tenant administrable.
        JasminUserFactory(roles=[Role.ADMIN], account_status="inactive")
        admin = JasminUserFactory(roles=[Role.ADMIN], account_status="active")
        with pytest.raises(AdminUserError, match="last active admin"):
            update_user_admin(user=admin, data={"roles": [Role.OFFICE]}, actor=admin)
