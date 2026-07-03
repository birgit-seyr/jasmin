"""Password-reset HTTP flow + JWT-after-logout regression tests.

Complements:
- ``test_integration_http.py``  (login/refresh/logout happy path + rotation)
- ``test_services_extra.py``    (service-level password reset + blacklist
  units)

The gaps locked here:
1. The full HTTP path: request reset -> confirm reset -> login with new
   password works. Includes the silent-on-miss / silent-on-blocked-status
   contract that prevents user enumeration.
2. After ``/logout/``, the just-blacklisted refresh token cannot be replayed
   on ``/refresh/``. (Rotation is covered separately; logout is its own
   path because it goes through ``blacklist_refresh`` directly, not via
   the rotation logic.)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import JasminUser
from apps.commissioning.tests.factories import JasminUserFactory
from apps.shared.auth_cookies import TENANT_REFRESH_COOKIE

pytestmark = pytest.mark.django_db


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
# /password-reset/request/ + /password-reset/confirm/                          #
# --------------------------------------------------------------------------- #


class TestPasswordResetFlowHTTP:
    """End-to-end: request reset, extract uid+token, confirm, log in."""

    def test_full_flow_resets_password_and_allows_login(self, tenant):
        u = JasminUserFactory(email="reset@example.com")
        _set_password(u, "OldPass!42xyzabc")

        # 1) Request the reset. Capture the (uid, token) the service
        #    would otherwise email out — patching the email layer keeps
        #    the test independent of TenantEmailConfig setup.
        with patch(
            "apps.accounts.services.password_reset_service._send_password_reset_email"
        ) as send_mock:
            resp = APIClient().post(
                "/api/auth/password-reset/request/",
                data={"email": "reset@example.com"},
                format="json",
            )
        assert resp.status_code == status.HTTP_200_OK
        assert send_mock.call_count == 1
        kwargs = send_mock.call_args.kwargs
        uid, token = kwargs["uid"], kwargs["token"]
        assert uid and token

        # 2) Confirm with a strong new password.
        new_password = "NewS3cure!Pass42xyz"
        confirm = APIClient().post(
            "/api/auth/password-reset/confirm/",
            data={"uid": uid, "token": token, "password": new_password},
            format="json",
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.data

        # 3) Old password no longer works.
        bad = _login(APIClient(), "reset@example.com", "OldPass!42xyzabc")
        assert bad.status_code == status.HTTP_400_BAD_REQUEST

        # 4) New password works.
        good = _login(APIClient(), "reset@example.com", new_password)
        assert good.status_code == status.HTTP_200_OK

    def test_token_is_single_use(self, tenant):
        """Re-confirming with the same (uid, token) MUST fail because
        the token incorporates the password hash, which has changed."""
        u = JasminUserFactory(email="single@example.com")
        _set_password(u, "OldPass!42xyzabc")

        uid = urlsafe_base64_encode(force_bytes(u.pk))
        token = PasswordResetTokenGenerator().make_token(u)

        ok = APIClient().post(
            "/api/auth/password-reset/confirm/",
            data={"uid": uid, "token": token, "password": "BrandNew!Pass42xyz"},
            format="json",
        )
        assert ok.status_code == status.HTTP_200_OK

        replay = APIClient().post(
            "/api/auth/password-reset/confirm/",
            data={"uid": uid, "token": token, "password": "Another!Pass42xyz"},
            format="json",
        )
        assert replay.status_code == status.HTTP_400_BAD_REQUEST

    def test_request_for_unknown_email_returns_200_silently(self, tenant):
        """User-enumeration defence: identical 200 on hit and miss, with
        no email dispatched on miss."""
        with patch(
            "apps.accounts.services.password_reset_service._send_password_reset_email"
        ) as send_mock:
            resp = APIClient().post(
                "/api/auth/password-reset/request/",
                data={"email": "nobody@example.com"},
                format="json",
            )
        assert resp.status_code == status.HTTP_200_OK
        assert send_mock.call_count == 0

    def test_request_for_blocked_status_does_not_send(self, tenant):
        """Pending-invitation / pending-approval users have a different
        flow (invitation accept / admin approval). Reset must skip them."""
        JasminUserFactory(
            email="pending@example.com", account_status="pending_invitation"
        )
        with patch(
            "apps.accounts.services.password_reset_service._send_password_reset_email"
        ) as send_mock:
            resp = APIClient().post(
                "/api/auth/password-reset/request/",
                data={"email": "pending@example.com"},
                format="json",
            )
        assert resp.status_code == status.HTTP_200_OK
        assert send_mock.call_count == 0

    def test_request_malformed_email_returns_400(self, tenant):
        # Anti-enumeration applies to VALID emails (always 200). A MALFORMED
        # email is a serializer 400 — validation runs before the email lookup.
        resp = APIClient().post(
            "/api/auth/password-reset/request/",
            data={"email": "not-an-email"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "validation_error"
        assert "email" in resp.data["details"]

    def test_confirm_missing_fields_returns_400(self, tenant):
        # uid/token/password all required → serializer 400 before the service.
        resp = APIClient().post(
            "/api/auth/password-reset/confirm/",
            data={"token": "x", "password": "Whatever!Pass42x"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "validation_error"
        assert "uid" in resp.data["details"]

    def test_confirm_with_garbage_token_returns_400(self, tenant):
        u = JasminUserFactory(email="bad@example.com")
        uid = urlsafe_base64_encode(force_bytes(u.pk))
        resp = APIClient().post(
            "/api/auth/password-reset/confirm/",
            data={
                "uid": uid,
                "token": "not-a-real-token",
                "password": "WhateverPass!42x",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_confirm_rejects_weak_password(self, tenant):
        u = JasminUserFactory(email="weak@example.com")
        _set_password(u, "OldPass!42xyzabc")
        uid = urlsafe_base64_encode(force_bytes(u.pk))
        token = PasswordResetTokenGenerator().make_token(u)

        resp = APIClient().post(
            "/api/auth/password-reset/confirm/",
            data={"uid": uid, "token": token, "password": "abc"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# --------------------------------------------------------------------------- #
# Refresh token blacklisted by /logout/ — full HTTP path                       #
# --------------------------------------------------------------------------- #


class TestRefreshAfterLogout:
    def test_refresh_after_logout_returns_401(self, tenant):
        u = JasminUserFactory(email="lo@example.com")
        _set_password(u, "Logout!Pass42xyz")
        client = APIClient()

        login = _login(client, "lo@example.com", "Logout!Pass42xyz")
        assert login.status_code == status.HTTP_200_OK
        cookie_value = client.cookies.get(TENANT_REFRESH_COOKIE).value
        assert cookie_value

        logout = client.post("/api/auth/logout/", data={}, format="json")
        assert logout.status_code == status.HTTP_200_OK

        # Replay the just-logged-out refresh token on a clean client.
        replay = APIClient()
        replay.cookies[TENANT_REFRESH_COOKIE] = cookie_value
        resp = replay.post("/api/auth/refresh/", data={}, format="json")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_logout_then_login_then_refresh_works(self, tenant):
        """Logging out blacklists the OLD token only — a fresh login must
        get a brand-new refresh that still works."""
        u = JasminUserFactory(email="relog@example.com")
        _set_password(u, "Relog!Pass42xyz")

        # First session: login, logout.
        c1 = APIClient()
        _login(c1, "relog@example.com", "Relog!Pass42xyz")
        c1.post("/api/auth/logout/", data={}, format="json")

        # Second session: fresh login + refresh works.
        c2 = APIClient()
        _login(c2, "relog@example.com", "Relog!Pass42xyz")
        resp = c2.post("/api/auth/refresh/", data={}, format="json")
        assert resp.status_code == status.HTTP_200_OK


# --------------------------------------------------------------------------- #
# GAP-1: session revocation on password reset + logout-everywhere              #
# --------------------------------------------------------------------------- #


def _extract_reset_uid_token(user):
    """Build the (uid, token) a reset email would carry for ``user``."""
    from apps.accounts.services import password_reset_service as prs

    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = prs.token_generator.make_token(user)
    return uid, token


class TestPasswordResetRevokesSessions:
    def test_refresh_token_from_before_reset_is_dead_after_reset(self, tenant):
        # The exact GAP-1 scenario: an attacker holds a refresh token minted
        # before the victim resets their password. After the reset it must no
        # longer be rotatable — a rotating token otherwise survives the reset
        # for its full lifetime.
        user = JasminUserFactory(email="revoke@example.com")
        _set_password(user, "OldPass!42xyzabc")

        stolen = APIClient()
        assert (
            _login(stolen, "revoke@example.com", "OldPass!42xyzabc").status_code
            == status.HTTP_200_OK
        )
        stolen_cookie = stolen.cookies.get(TENANT_REFRESH_COOKIE).value

        # Victim resets the password (fresh token derived like the email link).
        user.refresh_from_db()
        uid, token = _extract_reset_uid_token(user)
        confirm = APIClient().post(
            "/api/auth/password-reset/confirm/",
            data={"uid": uid, "token": token, "password": "BrandNew!42xyzabc"},
            format="json",
        )
        assert confirm.status_code == status.HTTP_200_OK

        # The stolen pre-reset refresh token can no longer mint a session.
        replay = APIClient()
        replay.cookies[TENANT_REFRESH_COOKIE] = stolen_cookie
        resp = replay.post("/api/auth/refresh/", data={}, format="json")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

        # And the victim can log in fresh + refresh normally afterwards.
        fresh = APIClient()
        _login(fresh, "revoke@example.com", "BrandNew!42xyzabc")
        assert (
            fresh.post("/api/auth/refresh/", data={}, format="json").status_code
            == status.HTTP_200_OK
        )


class TestLogoutEverywhere:
    def test_logout_all_kills_other_sessions(self, tenant):
        user = JasminUserFactory(email="all@example.com")
        _set_password(user, "AllPass!42xyzabc")

        # Two independent sessions (two devices).
        device_a = APIClient()
        device_b = APIClient()
        _login(device_a, "all@example.com", "AllPass!42xyzabc")
        _login(device_b, "all@example.com", "AllPass!42xyzabc")
        b_cookie = device_b.cookies.get(TENANT_REFRESH_COOKIE).value

        # Device A triggers "log out everywhere" (authenticated).
        access_a = _login(device_a, "all@example.com", "AllPass!42xyzabc").data[
            "access"
        ]
        auth_a = APIClient()
        auth_a.credentials(HTTP_AUTHORIZATION=f"Bearer {access_a}")
        resp = auth_a.post("/api/auth/logout-all/", data={}, format="json")
        assert resp.status_code == status.HTTP_200_OK

        # Device B's refresh token — never presented to logout-all — is dead.
        replay = APIClient()
        replay.cookies[TENANT_REFRESH_COOKIE] = b_cookie
        resp = replay.post("/api/auth/refresh/", data={}, format="json")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_logout_all_requires_authentication(self, tenant):
        resp = APIClient().post("/api/auth/logout-all/", data={}, format="json")
        assert resp.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_rotated_token_still_revoked(self, tenant):
        # Rotation mints a NEW jti that is not in OutstandingToken, so a
        # blacklist-only revoke would miss it. The iat-based cut-off must still
        # kill a rotated token whose iat predates the revocation. Time-travel a
        # real gap so the rotated iat is a genuinely earlier second than the
        # revoke (the second-granularity cut-off intentionally spares
        # same-second tokens — see _refresh_iat_still_valid).
        import time_machine

        from apps.accounts.services import revoke_all_sessions

        user = JasminUserFactory(email="rot@example.com")
        _set_password(user, "RotPass!42xyzabc")

        client = APIClient()
        with time_machine.travel("2026-06-01 10:00:00+00:00", tick=False):
            _login(client, "rot@example.com", "RotPass!42xyzabc")
            # Rotate: the live cookie now holds a rotated (non-outstanding) token.
            rotated = client.post("/api/auth/refresh/", data={}, format="json")
            assert rotated.status_code == status.HTTP_200_OK
            rotated_cookie = client.cookies.get(TENANT_REFRESH_COOKIE).value

        with time_machine.travel("2026-06-01 10:05:00+00:00", tick=False):
            user.refresh_from_db()
            revoke_all_sessions(user)

            replay = APIClient()
            replay.cookies[TENANT_REFRESH_COOKIE] = rotated_cookie
            resp = replay.post("/api/auth/refresh/", data={}, format="json")
            assert resp.status_code == status.HTTP_401_UNAUTHORIZED


# --------------------------------------------------------------------------- #
# AUTH-2 / AUTH-5: /refresh/ re-validates the account and re-stamps claims      #
# --------------------------------------------------------------------------- #


class TestRefreshRevalidatesAccount:
    def test_deactivated_user_cannot_refresh(self, tenant):
        # AUTH-2: a mid-session deactivation stamps no revoke marker, so GAP-1's
        # iat cut-off doesn't fire — the per-refresh is_active re-check is what
        # kills the still-warm session (the minted access is DOA at endpoints,
        # but the refresh itself must stop rotating).
        user = JasminUserFactory(email="deact@example.com")
        _set_password(user, "Deact!Pass42xyz")
        client = APIClient()
        assert (
            _login(client, "deact@example.com", "Deact!Pass42xyz").status_code
            == status.HTTP_200_OK
        )
        assert (
            client.post("/api/auth/refresh/", data={}, format="json").status_code
            == status.HTTP_200_OK
        )

        # ``is_active`` is DERIVED from ``account_status`` in ``JasminUser.save()``
        # — deactivate via the source field, not the derived flag.
        user.account_status = "inactive"
        user.save(update_fields=["account_status", "updated_at"])
        assert not JasminUser.objects.get(pk=user.pk).is_active

        resp = client.post("/api/auth/refresh/", data={}, format="json")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_refreshed_access_re_stamps_login_claims(self, tenant):
        # AUTH-5: a refreshed access token must carry the same login-time claims
        # (user_role, tenant_id, tenant_name) — the raw refresh-minted token
        # drops user_role/tenant_name, which any code trusting them would notice.
        from rest_framework_simplejwt.tokens import AccessToken

        user = JasminUserFactory(email="claims@example.com")
        _set_password(user, "Claims!Pass42xyz")
        client = APIClient()
        _login(client, "claims@example.com", "Claims!Pass42xyz")

        resp = client.post("/api/auth/refresh/", data={}, format="json")
        assert resp.status_code == status.HTTP_200_OK

        payload = AccessToken(resp.json()["access"]).payload
        assert payload["tenant_id"] == tenant.schema_name
        assert "tenant_name" in payload
        assert "user_role" in payload

    def test_login_email_is_normalized(self, tenant):
        # AUTH-3: the login email is lowercased before authenticate(), so a
        # mixed-case login resolves the same account (and django-axes keys ONE
        # lockout bucket rather than one per case-variation).
        user = JasminUserFactory(email="mixed@example.com")
        _set_password(user, "Mixed!Pass42xyz")
        resp = _login(APIClient(), "MiXeD@Example.COM", "Mixed!Pass42xyz")
        assert resp.status_code == status.HTTP_200_OK
