"""Tests for ``views/auth.py`` — super-admin login / logout / refresh.

Direct view-function dispatch via ``APIRequestFactory`` (not ``APIClient``)
for the same reason as ``test_tenant_management_viewset.py``: these views
live under ``PUBLIC_SCHEMA_URLCONF`` (= ``config.public_urls``), so HTTP
routing against the ``testserver`` host (= tenant_urls) would 404.
Calling the ``@api_view``-decorated function directly with a built request
exercises the real view code, including cookie reads via
``get_super_admin_refresh_token`` (it reads ``request.COOKIES``, which
``APIRequestFactory`` supports natively).

What we cover:
    - Login: happy path + every failure branch (missing fields, unknown
      email, wrong password, inactive account).
    - Logout: happy path (cookie present → blacklist row written +
      ``Set-Cookie`` cleared) and no-cookie / bad-cookie no-ops.
    - Refresh: happy path (rotation mints a new refresh JTI and
      blacklists the old one), plus 401 branches for missing /
      invalid / non-superadmin tokens.
"""

from __future__ import annotations

import pytest
from django_tenants.utils import schema_context
from rest_framework.test import APIRequestFactory

from apps.shared.auth_cookies import SUPER_ADMIN_REFRESH_COOKIE
from apps.shared.super_admin.models import SuperAdmin, SuperAdminBlacklistedToken
from apps.shared.super_admin.views.auth_views import (
    SuperAdminRefreshToken,
    super_admin_login_view,
    super_admin_logout_view,
    super_admin_token_refresh_view,
)

SUPER_ADMIN_EMAIL = "auth-test@example.com"
SUPER_ADMIN_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def super_admin(_tenant_schema):
    """A SuperAdmin row in the public schema with a known password.

    ``get_or_create`` + ``set_password`` keeps the fixture idempotent
    across tests in the same session (the SuperAdmin manager hashes the
    password via ``set_password`` on the model).
    """
    with schema_context("public"):
        admin, _ = SuperAdmin.objects.get_or_create(
            email=SUPER_ADMIN_EMAIL,
            defaults={"first_name": "Auth", "last_name": "Tester"},
        )
        admin.is_active = True
        admin.set_password(SUPER_ADMIN_PASSWORD)
        admin.save()
    return admin


@pytest.fixture
def factory():
    return APIRequestFactory()


def _login(factory, **data):
    """POST to login view, return Response."""
    request = factory.post("/auth/login/", data, format="json")
    return super_admin_login_view(request)


def _refresh_cookie_value(response) -> str | None:
    """Pull the super-admin refresh cookie value out of a Response."""
    morsel = response.cookies.get(SUPER_ADMIN_REFRESH_COOKIE)
    return morsel.value if morsel else None


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLogin:
    def test_happy_path_returns_access_and_user(self, factory, super_admin, tenant):
        """Valid creds → 200, access token in body, refresh cookie set."""
        response = _login(
            factory, email=SUPER_ADMIN_EMAIL, password=SUPER_ADMIN_PASSWORD
        )

        assert response.status_code == 200
        assert response.data["access"]
        assert response.data["is_super_admin"] is True
        assert response.data["user"]["email"] == SUPER_ADMIN_EMAIL
        # ``tenants`` is the platform's tenant list (used by the
        # super-admin UI to seed the tenant switcher).
        assert any(
            t["schema_name"] == tenant.schema_name for t in response.data["tenants"]
        )
        # Refresh cookie is HttpOnly — only visible via response.cookies.
        assert _refresh_cookie_value(response) is not None

    def test_missing_email_returns_400(self, factory):
        response = _login(factory, password="anything")
        assert response.status_code == 400
        assert "required" in response.data["message"].lower()

    def test_missing_password_returns_400(self, factory):
        response = _login(factory, email=SUPER_ADMIN_EMAIL)
        assert response.status_code == 400
        assert "required" in response.data["message"].lower()

    def test_unknown_email_returns_400(self, factory, _tenant_schema):
        response = _login(factory, email="nobody@example.com", password="whatever")
        assert response.status_code == 400
        assert response.data["message"] == "Invalid credentials"

    def test_wrong_password_returns_400(self, factory, super_admin):
        response = _login(factory, email=SUPER_ADMIN_EMAIL, password="wrong")
        assert response.status_code == 400
        assert response.data["message"] == "Invalid credentials"

    def test_inactive_account_returns_403(self, factory, super_admin):
        with schema_context("public"):
            super_admin.is_active = False
            super_admin.save(update_fields=["is_active"])
        try:
            response = _login(
                factory, email=SUPER_ADMIN_EMAIL, password=SUPER_ADMIN_PASSWORD
            )
            assert response.status_code == 403
            assert "disabled" in response.data["message"].lower()
        finally:
            # Restore so other tests in the same session see the row active.
            with schema_context("public"):
                super_admin.is_active = True
                super_admin.save(update_fields=["is_active"])


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLogout:
    def test_happy_path_blacklists_token_and_clears_cookie(self, factory, super_admin):
        """Cookie present → JTI written to blacklist + Set-Cookie cleared."""
        # Mint a real refresh through the production helper so the token's
        # JTI / exp claims look exactly like a logged-in session's would.
        refresh = SuperAdminRefreshToken()
        refresh["user_id"] = super_admin.id
        refresh["email"] = super_admin.email
        refresh["is_super_admin"] = True
        jti = refresh["jti"]

        request = factory.post("/auth/logout/")
        request.COOKIES[SUPER_ADMIN_REFRESH_COOKIE] = str(refresh)
        response = super_admin_logout_view(request)

        assert response.status_code == 200
        with schema_context("public"):
            assert SuperAdminBlacklistedToken.objects.filter(jti=jti).exists()
        # ``clear`` writes an empty value with max-age=0 — value is "".
        morsel = response.cookies.get(SUPER_ADMIN_REFRESH_COOKIE)
        assert morsel is not None
        assert morsel.value == ""

    def test_no_cookie_clears_anyway(self, factory, _tenant_schema):
        """No cookie → still 200 + still emits the clear-cookie header."""
        request = factory.post("/auth/logout/")
        response = super_admin_logout_view(request)

        assert response.status_code == 200
        # No blacklist row should have been written.
        with schema_context("public"):
            # Brand-new test → table either empty or contains rows from
            # other tests. Just check the response doesn't crash.
            pass
        assert SUPER_ADMIN_REFRESH_COOKIE in response.cookies

    def test_invalid_token_does_not_crash(self, factory, _tenant_schema):
        """Garbled cookie → log + 200 + cleared cookie (don't 500)."""
        request = factory.post("/auth/logout/")
        request.COOKIES[SUPER_ADMIN_REFRESH_COOKIE] = "not-a-real-jwt"
        response = super_admin_logout_view(request)

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRefresh:
    def _build_refresh(self, super_admin) -> SuperAdminRefreshToken:
        refresh = SuperAdminRefreshToken()
        refresh["user_id"] = super_admin.id
        refresh["email"] = super_admin.email
        refresh["is_super_admin"] = True
        return refresh

    def test_happy_path_returns_new_access(self, factory, super_admin):
        refresh = self._build_refresh(super_admin)
        request = factory.post("/auth/refresh/")
        request.COOKIES[SUPER_ADMIN_REFRESH_COOKIE] = str(refresh)
        response = super_admin_token_refresh_view(request)

        assert response.status_code == 200
        assert response.data["access"]
        assert response.data["is_super_admin"] is True
        assert response.data["schema"] == "public"

    def test_no_cookie_returns_401(self, factory, _tenant_schema):
        request = factory.post("/auth/refresh/")
        response = super_admin_token_refresh_view(request)

        assert response.status_code == 401
        assert "required" in response.data["message"].lower()

    def test_invalid_token_returns_401(self, factory, _tenant_schema):
        request = factory.post("/auth/refresh/")
        request.COOKIES[SUPER_ADMIN_REFRESH_COOKIE] = "garbage.jwt.token"
        response = super_admin_token_refresh_view(request)

        assert response.status_code == 401
        assert "invalid" in response.data["message"].lower()

    def test_non_superadmin_token_returns_401(self, factory, super_admin):
        """A refresh that wasn't minted as a super-admin session is rejected.

        Defence-in-depth: even if someone fabricates a refresh signed
        with the same key (e.g. by reusing a tenant-side refresh), the
        ``is_super_admin`` claim guard stops it from being upgraded
        into a super-admin access token.
        """
        refresh = SuperAdminRefreshToken()
        refresh["user_id"] = super_admin.id
        # No is_super_admin claim — default False.

        request = factory.post("/auth/refresh/")
        request.COOKIES[SUPER_ADMIN_REFRESH_COOKIE] = str(refresh)
        response = super_admin_token_refresh_view(request)

        assert response.status_code == 401
        assert "super admin" in response.data["message"].lower()

    def test_rotation_blacklists_old_jti(self, factory, super_admin, settings):
        """When ROTATE_REFRESH_TOKENS + BLACKLIST_AFTER_ROTATION are on,
        the old refresh's JTI must be blacklisted and a new refresh cookie
        issued. Without this lock-in a stolen refresh stays valid forever
        even after the legitimate user has rotated.
        """
        # Ensure the rotation knobs are on regardless of how prod settings
        # may shift over time; this test asserts behavior of the view under
        # the documented configuration.
        settings.SIMPLE_JWT = {
            **settings.SIMPLE_JWT,
            "ROTATE_REFRESH_TOKENS": True,
            "BLACKLIST_AFTER_ROTATION": True,
        }

        refresh = self._build_refresh(super_admin)
        old_jti = refresh["jti"]

        request = factory.post("/auth/refresh/")
        request.COOKIES[SUPER_ADMIN_REFRESH_COOKIE] = str(refresh)
        response = super_admin_token_refresh_view(request)

        assert response.status_code == 200
        with schema_context("public"):
            assert SuperAdminBlacklistedToken.objects.filter(jti=old_jti).exists()
        new_cookie = _refresh_cookie_value(response)
        assert new_cookie is not None and new_cookie != str(refresh)

    def test_inactive_account_refresh_rejected(self, factory, super_admin):
        """A super-admin deactivated AFTER login must not be able to renew
        their session. The old code trusted only the ``is_super_admin``
        claim and never loaded the row, so a disabled account kept minting
        fresh access tokens off its refresh cookie for the token lifetime."""
        refresh = self._build_refresh(super_admin)
        request = factory.post("/auth/refresh/")
        request.COOKIES[SUPER_ADMIN_REFRESH_COOKIE] = str(refresh)

        with schema_context("public"):
            super_admin.is_active = False
            super_admin.save(update_fields=["is_active"])
        try:
            response = super_admin_token_refresh_view(request)
            assert response.status_code == 401
        finally:
            with schema_context("public"):
                super_admin.is_active = True
                super_admin.save(update_fields=["is_active"])


# ---------------------------------------------------------------------------
# JWT authentication — is_active enforcement on every request
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSuperAdminJWTAuthentication:
    """``SuperAdminJWTAuthentication.get_user`` fully overrides the base
    SimpleJWT ``get_user`` and used to drop its ``is_active`` check, so a
    super-admin disabled or deleted after login kept full platform access
    for the token lifetime. The auth class now mirrors the base class."""

    def _token(self, super_admin):
        from rest_framework_simplejwt.tokens import AccessToken

        token = AccessToken()
        token["user_id"] = super_admin.id
        token["is_super_admin"] = True
        token["user_role"] = "super_admin"
        return token

    def test_get_user_rejects_inactive_account(self, super_admin):
        from rest_framework.exceptions import AuthenticationFailed

        from apps.shared.super_admin.views.authentication import (
            SuperAdminJWTAuthentication,
        )

        token = self._token(super_admin)
        with schema_context("public"):
            super_admin.is_active = False
            super_admin.save(update_fields=["is_active"])
        try:
            with pytest.raises(AuthenticationFailed):
                SuperAdminJWTAuthentication().get_user(token)
        finally:
            with schema_context("public"):
                super_admin.is_active = True
                super_admin.save(update_fields=["is_active"])

    def test_get_user_returns_active_account(self, super_admin):
        from apps.shared.super_admin.views.authentication import (
            SuperAdminJWTAuthentication,
        )

        user = SuperAdminJWTAuthentication().get_user(self._token(super_admin))

        assert user.id == super_admin.id
        assert user.is_super_admin is True


# ---------------------------------------------------------------------------
# Rate-limit wiring (SEC-7)
# ---------------------------------------------------------------------------


class TestRateLimitWiring:
    """Super-admin login + step-up authenticate via ``check_password``
    directly (not Django's ``authenticate()``), so django-axes never sees
    the failures. A strict ScopedRateThrottle scope is the app-layer cap;
    these assertions pin that wiring so it can't silently regress."""

    def test_login_and_step_up_carry_strict_scope(self):
        from apps.shared.super_admin.views.auth_views import (
            super_admin_login_view,
            super_admin_step_up_view,
        )

        assert super_admin_login_view.cls.throttle_scope == "super_admin_login"
        assert super_admin_step_up_view.cls.throttle_scope == "super_admin_login"

    def test_scope_has_a_rate_configured(self):
        from django.conf import settings

        rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
        assert rates.get("super_admin_login")


# ---------------------------------------------------------------------------
# Functional throttle: the scope actually fires (not just wired)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLoginThrottleFires:
    """End-to-end proof the rate limit engages — stronger than the wiring
    assertions above. This codebase has a documented history (the 2026-06
    accounts fix) of the ``.cls.throttle_scope`` pattern shipping as a
    SILENT no-op with green CI, so the highest-privilege login gets a real
    429 test. The autouse ``_clear_throttle_cache`` fixture gives each test
    a fresh bucket.

    Direct view-function dispatch (not ``reverse()`` + ``APIClient``): the
    super-admin views live under ``PUBLIC_SCHEMA_URLCONF``, so HTTP routing
    against the tenant ``testserver`` host 404s. Calling the
    ``@api_view``-wrapped function still runs the full DRF dispatch,
    including ``check_throttles()`` in ``initial()`` — which fires BEFORE
    the view body, so wrong credentials still count toward the cap."""

    # The ``super_admin_login`` scope rate (config/settings.py).
    RATE = 10

    def test_429_after_login_quota_exhausted(self, factory, _tenant_schema):
        # Vary the email each attempt so the PER-ACCOUNT lockout
        # (super_admin/lockout.py) never trips — this isolates the PER-IP
        # throttle, which keys on client IP regardless of account.
        for i in range(self.RATE):
            payload = {"email": f"nobody{i}@example.com", "password": "wrong"}
            request = factory.post("/auth/login/", payload, format="json")
            resp = super_admin_login_view(request)
            assert resp.status_code != 429, (
                f"request {i + 1}/{self.RATE} throttled too early "
                f"(status {resp.status_code}) — rate lower than {self.RATE}?"
            )

        request = factory.post(
            "/auth/login/",
            {"email": "nobody-final@example.com", "password": "wrong"},
            format="json",
        )
        resp = super_admin_login_view(request)
        assert resp.status_code == 429, (
            f"request {self.RATE + 1} should be 429 but got {resp.status_code}"
            " — the super_admin_login throttle scope is a no-op."
        )


# ---------------------------------------------------------------------------
# Per-account brute-force lockout (super_admin/lockout.py)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLoginAccountLockout:
    """After N failed attempts an ACCOUNT is refused (429) regardless of source
    IP — the layer the per-IP throttle can't provide against a distributed /
    rotating-IP guessing attack on the platform-root credential. MAX is
    lowered to 3 per-test (via the ``settings`` fixture) for determinism; the
    autouse ``_clear_throttle_cache`` fixture (``cache.clear``) isolates lock
    state between tests."""

    @pytest.fixture(autouse=True)
    def _low_threshold(self, settings):
        settings.SUPER_ADMIN_LOGIN_MAX_FAILURES = 3

    def test_locks_account_after_max_failures(self, factory, _tenant_schema):
        email = "lockme@example.com"
        # First 3 wrong attempts return the normal 400; the 3rd sets the lock.
        for _ in range(3):
            assert _login(factory, email=email, password="wrong").status_code == 400

        # The next attempt is refused BEFORE any credential check.
        resp = _login(factory, email=email, password="wrong")
        assert resp.status_code == 429
        assert resp.data["code"] == "super_admin.account_locked"

    def test_locked_account_refused_even_with_correct_password(
        self, factory, super_admin
    ):
        # Burn the account's attempts with the wrong password...
        for _ in range(3):
            _login(factory, email=SUPER_ADMIN_EMAIL, password="wrong")
        # ...the CORRECT password is now still refused: the lock is checked
        # before ``check_password``, so it is a true account-level lock.
        resp = _login(factory, email=SUPER_ADMIN_EMAIL, password=SUPER_ADMIN_PASSWORD)
        assert resp.status_code == 429
        assert resp.data["code"] == "super_admin.account_locked"

    def test_successful_login_resets_failure_counter(self, factory, super_admin):
        # Two failures (below the threshold of 3), then a success clears them.
        for _ in range(2):
            assert (
                _login(factory, email=SUPER_ADMIN_EMAIL, password="wrong").status_code
                == 400
            )
        assert (
            _login(
                factory, email=SUPER_ADMIN_EMAIL, password=SUPER_ADMIN_PASSWORD
            ).status_code
            == 200
        )
        # After the reset it takes a full threshold again — two more failures
        # do NOT lock (they would have, had the counter carried over).
        for _ in range(2):
            assert (
                _login(factory, email=SUPER_ADMIN_EMAIL, password="wrong").status_code
                == 400
            )

    def test_lock_is_per_account(self, factory, super_admin):
        # Lock a different account...
        for _ in range(3):
            _login(factory, email="other@example.com", password="wrong")
        assert (
            _login(factory, email="other@example.com", password="wrong").status_code
            == 429
        )
        # ...the real super-admin is unaffected and can still log in.
        resp = _login(factory, email=SUPER_ADMIN_EMAIL, password=SUPER_ADMIN_PASSWORD)
        assert resp.status_code == 200
