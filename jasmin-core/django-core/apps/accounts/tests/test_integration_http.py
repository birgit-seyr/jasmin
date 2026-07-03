"""HTTP-level integration tests for accounts.

These tests exercise the wiring between URLs, views, services, signals,
and JWT/cookie machinery — catching breakage that pure-service tests
would miss.

Endpoints covered:
- POST /api/auth/login/
- POST /api/auth/refresh/
- POST /api/auth/logout/
- POST /api/auth/register/
- GET  /api/auth/invitations/<token>/
- POST /api/auth/invitations/accept/
- GET   /api/auth/admin/users/
- POST  /api/auth/admin/users/
- PATCH /api/auth/admin/users/<id>/
- POST  /api/auth/admin/users/<id>/resend-invitation/

End-to-end flows:
1. Self-registration → office confirms → login succeeds.
2. Admin invite → verify token → accept → login succeeds.
3. Cross-tenant access token replay rejected.
4. Refresh rotates the cookie.
5. Permission gating: non-admin → 403, admin → 200.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import JasminUser
from apps.authz.roles import Role
from apps.commissioning.models import Member, UserInvitation
from apps.commissioning.tests.factories import JasminUserFactory
from apps.shared.auth_cookies import (
    TENANT_REFRESH_COOKIE,
    TENANT_REFRESH_COOKIE_PATH,
)

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _set_password(user, raw):
    user.set_password(raw)
    user.save(update_fields=["password"])


def _login(client, email, password):
    return client.post(
        "/api/auth/login/",
        data={"email": email, "password": password},
        format="json",
    )


# --------------------------------------------------------------------------- #
# /login/                                                                      #
# --------------------------------------------------------------------------- #


class TestLoginEndpoint:
    def test_active_login_sets_refresh_cookie(self, tenant):
        u = JasminUserFactory(email="login@example.com")
        _set_password(u, "Z3rgRushIsScary!42")
        client = APIClient()
        resp = _login(client, "login@example.com", "Z3rgRushIsScary!42")
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["access"]
        assert resp.data["user"]["email"] == "login@example.com"
        assert resp.data["tenant"]["schema_name"] == tenant.schema_name
        cookie = resp.cookies.get(TENANT_REFRESH_COOKIE)
        assert cookie is not None
        assert cookie["httponly"]
        assert cookie["path"] == TENANT_REFRESH_COOKIE_PATH

    def test_missing_fields_returns_400(self, tenant):
        client = APIClient()
        resp = client.post("/api/auth/login/", data={}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_non_email_email_returns_400(self, tenant):
        # LoginRequestSerializer.email is an EmailField — a non-email is a
        # serializer 400. (Assert the canonical body, not the German message.)
        resp = APIClient().post(
            "/api/auth/login/",
            data={"email": "not-an-email", "password": "whatever123"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "validation_error"
        assert "email" in resp.data["details"]

    def test_missing_password_returns_400(self, tenant):
        resp = APIClient().post(
            "/api/auth/login/", data={"email": "a@b.com"}, format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "validation_error"
        assert "password" in resp.data["details"]

    def test_wrong_password_returns_400(self, tenant):
        u = JasminUserFactory(email="bp@example.com")
        _set_password(u, "GoodPass!42xyz")
        resp = _login(APIClient(), "bp@example.com", "WrongPass!42xyz")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_inactive_user_returns_403_with_helpful_message(self, tenant):
        u = JasminUserFactory(account_status="inactive", email="off@example.com")
        _set_password(u, "Off!Pass42xyz")
        resp = _login(APIClient(), "off@example.com", "Off!Pass42xyz")
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert "deactivated" in resp.data["message"].lower()

    def test_pending_approval_returns_403(self, tenant):
        u = JasminUserFactory(account_status="pending_approval")
        _set_password(u, "Pending!42xyzabc")
        resp = _login(APIClient(), u.email, "Pending!42xyzabc")
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert "approval" in resp.data["message"].lower()


# --------------------------------------------------------------------------- #
# /refresh/                                                                    #
# --------------------------------------------------------------------------- #


class TestRefreshEndpoint:
    def test_no_cookie_returns_401(self, tenant):
        resp = APIClient().post("/api/auth/refresh/", data={}, format="json")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_cookie_rotation(self, tenant):
        u = JasminUserFactory(email="rot@example.com")
        _set_password(u, "Rotate!42xyzabc")
        client = APIClient()
        login_resp = _login(client, "rot@example.com", "Rotate!42xyzabc")
        assert login_resp.status_code == 200
        old_cookie = client.cookies.get(TENANT_REFRESH_COOKIE).value

        # The refresh endpoint reads from cookies on the client.
        resp = client.post("/api/auth/refresh/", data={}, format="json")
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["access"]
        new_cookie = resp.cookies.get(TENANT_REFRESH_COOKIE)
        assert new_cookie is not None
        assert new_cookie.value != old_cookie  # rotated

    def test_garbage_refresh_returns_401(self, tenant):
        client = APIClient()
        client.cookies[TENANT_REFRESH_COOKIE] = "not-a-jwt"
        resp = client.post("/api/auth/refresh/", data={}, format="json")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


# --------------------------------------------------------------------------- #
# /logout/                                                                     #
# --------------------------------------------------------------------------- #


class TestLogoutEndpoint:
    def test_clears_cookie(self, tenant):
        u = JasminUserFactory(email="bye@example.com")
        _set_password(u, "Bye!42xyzabc")
        client = APIClient()
        _login(client, "bye@example.com", "Bye!42xyzabc")
        assert client.cookies.get(TENANT_REFRESH_COOKIE).value
        resp = client.post("/api/auth/logout/", data={}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        # Cleared cookie has empty value + Max-Age 0.
        cleared = resp.cookies.get(TENANT_REFRESH_COOKIE)
        assert cleared is not None
        assert cleared.value == ""

    def test_logout_without_cookie_still_succeeds(self, tenant):
        resp = APIClient().post("/api/auth/logout/", data={}, format="json")
        assert resp.status_code == status.HTTP_200_OK


# --------------------------------------------------------------------------- #
# /register/ + invitation flow                                                 #
# --------------------------------------------------------------------------- #


class TestRegisterEndpoint:
    payload = {
        "first_name": "Reggie",
        "last_name": "Strant",
        "email": "reg@example.com",
        "password": "Reggie!Pass42xyz",
        "user_language": "en",
    }

    def test_self_register_creates_pending_user(self, tenant):
        resp = APIClient().post("/api/auth/register/", data=self.payload, format="json")
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        u = JasminUser.objects.get(email="reg@example.com")
        assert u.account_status == "pending_approval"

    def test_register_returns_field_error_on_collision(self, tenant):
        JasminUserFactory(email="dupreg@example.com")
        bad = {**self.payload, "email": "dupreg@example.com"}
        resp = APIClient().post("/api/auth/register/", data=bad, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_register_bad_typed_field_returns_400(self, tenant):
        # is_valid runs before the service: a non-int coop_shares_count 400s.
        bad = {**self.payload, "coop_shares_count": "not-a-number"}
        resp = APIClient().post("/api/auth/register/", data=bad, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "validation_error"
        assert "coop_shares_count" in resp.data["details"]


class TestInvitationVerify:
    def test_invalid_token_returns_404(self, tenant):
        # Use a well-formed UUID that doesn't exist as an invitation,
        # so the URL resolves to the view (not the URL-level 404 path).
        resp = APIClient().get(
            "/api/auth/invitations/00000000-0000-0000-0000-000000000000/"
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND


class TestInvitationAccept:
    def test_missing_fields_returns_400(self, tenant):
        resp = APIClient().post("/api/auth/invitations/accept/", data={}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_token_returns_400(self, tenant):
        resp = APIClient().post(
            "/api/auth/invitations/accept/",
            data={"token": "00000000-0000-0000-0000-000000000000", "password": "x"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_token_returns_validation_error(self, tenant):
        resp = APIClient().post(
            "/api/auth/invitations/accept/",
            data={"password": "Whatever!Pass42x"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "validation_error"
        assert "token" in resp.data["details"]


# --------------------------------------------------------------------------- #
# /admin/users/* — IsAdmin gating                                              #
# --------------------------------------------------------------------------- #


def _step_up_client(user) -> APIClient:
    """Authenticated client whose access token carries a fresh
    ``step_up_verified_at`` claim. Granting a role via ``create`` /
    ``partial_update`` (a ``roles`` payload) is step-up gated, so admin-user
    flows that assign roles need this rather than a bare ``force_authenticate``.
    """
    import time

    from rest_framework_simplejwt.tokens import AccessToken

    token = AccessToken.for_user(user)
    token["step_up_verified_at"] = int(time.time())
    client = APIClient()
    client.force_authenticate(user=user, token=token)
    return client


class TestAdminUsersGating:
    def test_unauthenticated_list_returns_401_or_403(self, tenant):
        resp = APIClient().get("/api/auth/admin/users/")
        assert resp.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_non_admin_list_returns_403(self, tenant):
        u = JasminUserFactory(roles=[Role.OFFICE])
        client = APIClient()
        client.force_authenticate(user=u)
        resp = client.get("/api/auth/admin/users/")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_list_returns_200(self, tenant):
        u = JasminUserFactory(roles=[Role.ADMIN])
        client = APIClient()
        client.force_authenticate(user=u)
        resp = client.get("/api/auth/admin/users/")
        assert resp.status_code == status.HTTP_200_OK
        assert isinstance(resp.data, list)

    def test_admin_create_user(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        # roles in the payload → step-up gated (SEC-2).
        client = _step_up_client(admin)
        with patch("apps.shared.invitations._send_invitation_email"):
            resp = client.post(
                "/api/auth/admin/users/",
                data={
                    "first_name": "New",
                    "last_name": "User",
                    "email": "newadmin@example.com",
                    "roles": [Role.STAFF],
                },
                format="json",
            )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert resp.data["account_status"] == "pending_invitation"

    def test_admin_create_missing_email_returns_400(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        client = APIClient()
        client.force_authenticate(user=admin)
        resp = client.post(
            "/api/auth/admin/users/",
            data={"first_name": "New", "last_name": "User"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "validation_error"
        assert "email" in resp.data["details"]

    def test_admin_partial_update_empty_body_returns_200(self, tenant):
        # partial=True: an empty PATCH is a valid no-op (200), not a 400.
        admin = JasminUserFactory(roles=[Role.ADMIN])
        target = JasminUserFactory(account_status="active")
        client = APIClient()
        client.force_authenticate(user=admin)
        resp = client.patch(
            f"/api/auth/admin/users/{target.id}/", data={}, format="json"
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["id"] == target.id

    def test_admin_partial_update_renames_user(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        target = JasminUserFactory(account_status="active")
        client = APIClient()
        client.force_authenticate(user=admin)
        resp = client.patch(
            f"/api/auth/admin/users/{target.id}/",
            data={"first_name": "Renamed"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["first_name"] == "Renamed"

    def test_admin_partial_update_invalid_choice_returns_400(self, tenant):
        # account_status is a ChoiceField — an invalid choice is rejected by
        # is_valid (which runs on a REAL user id; a bad id would 404 first).
        admin = JasminUserFactory(roles=[Role.ADMIN])
        target = JasminUserFactory(account_status="active")
        client = APIClient()
        client.force_authenticate(user=admin)
        resp = client.patch(
            f"/api/auth/admin/users/{target.id}/",
            data={"account_status": "banana"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "validation_error"
        assert "account_status" in resp.data["details"]

    def test_resend_invitation_only_for_pending(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        active_user = JasminUserFactory(account_status="active")
        client = APIClient()
        client.force_authenticate(user=admin)
        resp = client.post(
            f"/api/auth/admin/users/{active_user.id}/resend-invitation/",
            data={},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# --------------------------------------------------------------------------- #
# End-to-end flows                                                             #
# --------------------------------------------------------------------------- #


class TestEndToEndSelfRegistration:
    def test_full_flow(self, tenant):
        client = APIClient()
        # 1. Self-register.
        reg = client.post(
            "/api/auth/register/",
            data={
                "first_name": "E2E",
                "last_name": "Reg",
                "email": "e2e_reg@example.com",
                "password": "E2EReg!42xyzabc",
                "user_language": "en",
            },
            format="json",
        )
        assert reg.status_code == status.HTTP_201_CREATED, reg.data

        # 2. Login should be blocked while pending_approval.
        blocked = _login(client, "e2e_reg@example.com", "E2EReg!42xyzabc")
        assert blocked.status_code == status.HTTP_403_FORBIDDEN

        # 3. Office confirms the Member.
        member = Member.objects.get(email="e2e_reg@example.com")
        office = JasminUserFactory(roles=[Role.OFFICE])
        member.confirm(admin_user=office, save=True)

        # 4. Login now succeeds.
        ok = _login(client, "e2e_reg@example.com", "E2EReg!42xyzabc")
        assert ok.status_code == status.HTTP_200_OK, ok.data
        assert ok.data["access"]


class TestEndToEndInvitation:
    def test_full_flow(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        # roles in the create payload → step-up gated (SEC-2).
        admin_client = _step_up_client(admin)

        # 1. Admin creates the user (which mints an invitation).
        with patch("apps.shared.invitations._send_invitation_email"):
            create_resp = admin_client.post(
                "/api/auth/admin/users/",
                data={
                    "first_name": "E2E",
                    "last_name": "Inv",
                    "email": "e2e_inv@example.com",
                    "roles": [Role.OFFICE],
                },
                format="json",
            )
        assert create_resp.status_code == 201, create_resp.data

        invitation = UserInvitation.objects.get(email="e2e_inv@example.com")

        # 2. Anonymous client verifies the token.
        anon = APIClient()
        verify = anon.get(f"/api/auth/invitations/{invitation.token}/")
        assert verify.status_code == status.HTTP_200_OK
        assert verify.data["email"] == "e2e_inv@example.com"

        # 3. Anonymous client posts a new password.
        accept = anon.post(
            "/api/auth/invitations/accept/",
            data={
                "token": str(invitation.token),
                "password": "InvE2E!42xyzabc",
            },
            format="json",
        )
        assert accept.status_code == status.HTTP_200_OK, accept.data

        # 4. The user can now log in.
        login = _login(anon, "e2e_inv@example.com", "InvE2E!42xyzabc")
        assert login.status_code == status.HTTP_200_OK, login.data


class TestCrossTenantTokenRejection:
    def test_token_for_other_tenant_is_rejected(self, tenant):
        """Mint an access token with a foreign tenant_id claim and confirm
        the JWT auth class refuses it on a protected endpoint."""
        admin = JasminUserFactory(roles=[Role.ADMIN])
        from rest_framework_simplejwt.tokens import AccessToken

        token = AccessToken.for_user(admin)
        token["tenant_id"] = "some-other-tenant"
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        resp = client.get("/api/auth/admin/users/")
        # TenantBoundJWTAuthentication raises InvalidToken → 401.
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_token_for_correct_tenant_passes(self, tenant):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        from rest_framework_simplejwt.tokens import AccessToken

        token = AccessToken.for_user(admin)
        token["tenant_id"] = tenant.schema_name
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        resp = client.get("/api/auth/admin/users/")
        assert resp.status_code == status.HTTP_200_OK


class TestRefreshCookieRotation:
    def test_old_refresh_blacklisted_after_rotation(self, tenant):
        u = JasminUserFactory(email="rotbl@example.com")
        _set_password(u, "RotBL!42xyzabc")
        client = APIClient()
        login = _login(client, "rotbl@example.com", "RotBL!42xyzabc")
        assert login.status_code == 200
        old_cookie = client.cookies.get(TENANT_REFRESH_COOKIE).value

        # First refresh: rotates and blacklists the old cookie.
        first = client.post("/api/auth/refresh/", data={}, format="json")
        assert first.status_code == 200
        new_cookie = client.cookies.get(TENANT_REFRESH_COOKIE).value
        assert new_cookie != old_cookie

        # Replaying the OLD refresh should now fail.
        replay_client = APIClient()
        replay_client.cookies[TENANT_REFRESH_COOKIE] = old_cookie
        replay = replay_client.post("/api/auth/refresh/", data={}, format="json")
        assert replay.status_code == status.HTTP_401_UNAUTHORIZED


# --------------------------------------------------------------------------- #
# PATCH /api/auth/<user_id>/ — self profile update                             #
# --------------------------------------------------------------------------- #


class TestProfileUpdateEndpoint:
    def test_update_own_profile_returns_200(self, tenant):
        user = JasminUserFactory(roles=[Role.OFFICE])
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.patch(
            f"/api/auth/{user.id}/", data={"first_name": "Renamed"}, format="json"
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["first_name"] == "Renamed"

    def test_bad_typed_field_returns_400(self, tenant):
        # All profile fields are optional, so the serializer 400 is a wrong type
        # (a list where a CharField is expected).
        user = JasminUserFactory(roles=[Role.OFFICE])
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.patch(
            f"/api/auth/{user.id}/",
            data={"user_language": ["de", "en"]},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "validation_error"
        assert "user_language" in resp.data["details"]

    def test_editing_other_user_returns_403(self, tenant):
        # The own-id permission check runs ABOVE serializer validation.
        user = JasminUserFactory(roles=[Role.OFFICE])
        other = JasminUserFactory(roles=[Role.OFFICE])
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.patch(
            f"/api/auth/{other.id}/", data={"first_name": "X"}, format="json"
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
