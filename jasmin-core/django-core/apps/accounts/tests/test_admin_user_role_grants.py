"""Configuration → Users must not grant a role nobody picked.

``create_user_with_invite`` hands its payload to the shared invitation helper,
whose ``_normalize_roles`` answers an empty role list with ``[member]``. That
default belongs to the member-linked callers; reached from this surface — which
never creates members — it mints a member login out of a blank field. The
create path therefore requires an explicit, non-empty role list.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.errors import AdminUserRolesRequired
from apps.accounts.services.user_admin_service import create_user_with_invite
from apps.authz.roles import Role
from apps.commissioning.tests.conftest import make_step_up_token
from apps.commissioning.tests.factories import JasminUserFactory

pytestmark = pytest.mark.django_db

_CODE = "admin_user.roles_required"


class TestCreateRequiresExplicitRoles:
    @pytest.mark.parametrize("roles", [None, [], {}, ""], ids=repr)
    def test_empty_role_payload_is_refused(self, tenant, roles):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        data = {
            "first_name": "No",
            "last_name": "Roles",
            "email": "noroles@example.com",
        }
        if roles is not None:
            data["roles"] = roles

        with pytest.raises(AdminUserRolesRequired) as exc:
            create_user_with_invite(data=data, created_by=admin)

        assert exc.value.code == _CODE
        assert exc.value.field == "roles"

    def test_no_user_is_created_when_roles_are_missing(self, tenant):
        from apps.accounts.models import JasminUser

        admin = JasminUserFactory(roles=[Role.ADMIN])
        with pytest.raises(AdminUserRolesRequired):
            create_user_with_invite(
                data={
                    "first_name": "Ghost",
                    "last_name": "User",
                    "email": "ghost-no-roles@example.com",
                },
                created_by=admin,
            )

        assert not JasminUser.objects.filter(
            email="ghost-no-roles@example.com"
        ).exists()

    def test_explicit_roles_still_create_the_user(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        with patch("apps.shared.invitations._send_invitation_email"):
            payload = create_user_with_invite(
                data={
                    "first_name": "With",
                    "last_name": "Roles",
                    "email": "withroles@example.com",
                    "roles": [Role.OFFICE],
                },
                created_by=admin,
            )

        assert payload["roles"] == [Role.OFFICE]
        assert Role.MEMBER not in payload["roles"]


class TestCreateRequiresExplicitRolesOverHttp:
    def test_absent_roles_key_returns_400(self, tenant):
        # No ``roles`` key → the step-up gate does not fire, so this reaches
        # the service with a plain admin session.
        admin = JasminUserFactory(roles=[Role.ADMIN])
        client = APIClient()
        client.force_authenticate(user=admin)

        resp = client.post(
            "/api/auth/admin/users/",
            data={
                "first_name": "Http",
                "last_name": "NoRoles",
                "email": "http-noroles@example.com",
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == _CODE

    def test_empty_roles_list_returns_400(self, tenant):
        # ``roles`` present → step-up gated, so carry a fresh claim to reach
        # the service's own validation rather than stopping at the 403.
        admin = JasminUserFactory(roles=[Role.ADMIN])
        client = APIClient()
        client.force_authenticate(user=admin, token=make_step_up_token(admin))

        resp = client.post(
            "/api/auth/admin/users/",
            data={
                "first_name": "Http",
                "last_name": "EmptyRoles",
                "email": "http-emptyroles@example.com",
                "roles": [],
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == _CODE
