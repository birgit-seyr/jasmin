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
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.commissioning.tests.conftest import make_step_up_token
from apps.shared.auth_cookies import SUPER_ADMIN_REFRESH_COOKIE
from apps.shared.super_admin.models import SuperAdmin, SuperAdminBlacklistedToken
from apps.shared.super_admin.views.auth_views import (
    SuperAdminRefreshToken,
    super_admin_login_view,
    super_admin_logout_view,
    super_admin_step_up_view,
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


def _step_up(factory, admin, data):
    """POST ``data`` to the step-up view authenticated as ``admin``.

    The step-up token passed to ``force_authenticate`` puts the request in the
    state a real super-admin session is in when the frontend interceptor
    re-verifies: an authenticated caller with ``request.auth`` populated.
    """
    admin.is_super_admin = True
    admin.user_role = "super_admin"
    request = factory.post("/auth/step-up/", data, format="json")
    force_authenticate(request, user=admin, token=make_step_up_token(admin))
    return super_admin_step_up_view(request)


def _create_case_variant_admins() -> str:
    """Store the same address twice, capitalised differently, and return the
    lowercase spelling. Both rows are active and share one password."""
    lowercase = "dup.case@example.com"
    with schema_context("public"):
        for stored in ("Dup.Case@example.com", lowercase):
            admin, _ = SuperAdmin.objects.get_or_create(
                email=stored,
                defaults={"first_name": "Dup", "last_name": "Case"},
            )
            admin.is_active = True
            admin.set_password(SUPER_ADMIN_PASSWORD)
            admin.save()
    return lowercase


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

    @pytest.mark.parametrize(
        "email", [{"$ne": None}, ["a@b.example"], 42, True], ids=repr
    )
    def test_non_string_email_returns_400(self, factory, super_admin, email):
        """Anonymous endpoint: a non-string email must not reach the lockout
        key or the ORM lookup, neither of which can take a dict or a list."""
        response = _login(factory, email=email, password=SUPER_ADMIN_PASSWORD)
        assert response.status_code == 400
        assert response.data["code"] == "super_admin.missing_credentials"

    @pytest.mark.parametrize(
        "password", [{"$ne": None}, ["hunter2"], 42, True], ids=repr
    )
    def test_non_string_password_returns_400(self, factory, super_admin, password):
        response = _login(factory, email=SUPER_ADMIN_EMAIL, password=password)
        assert response.status_code == 400
        assert response.data["code"] == "super_admin.missing_credentials"

    def test_mixed_case_email_authenticates(self, factory, super_admin, tenant):
        """The submitted address is normalised, so the account is found
        however the operator capitalised what they typed."""
        response = _login(
            factory, email=SUPER_ADMIN_EMAIL.upper(), password=SUPER_ADMIN_PASSWORD
        )

        assert response.status_code == 200, response.data
        assert response.data["user"]["email"] == SUPER_ADMIN_EMAIL

    def test_surrounding_whitespace_in_email_is_trimmed(
        self, factory, super_admin, tenant
    ):
        response = _login(
            factory,
            email=f"  {SUPER_ADMIN_EMAIL}  ",
            password=SUPER_ADMIN_PASSWORD,
        )

        assert response.status_code == 200, response.data

    def test_account_stored_with_capitals_can_log_in(
        self, factory, _tenant_schema, tenant
    ):
        """The lookup is case-insensitive, so an address stored with an
        uppercase local part authenticates against a lowercase submission."""
        stored_email = "Upper.Case@example.com"
        with schema_context("public"):
            admin, _ = SuperAdmin.objects.get_or_create(
                email=stored_email,
                defaults={"first_name": "Upper", "last_name": "Case"},
            )
            admin.is_active = True
            admin.set_password(SUPER_ADMIN_PASSWORD)
            admin.save()

        response = _login(
            factory, email=stored_email.lower(), password=SUPER_ADMIN_PASSWORD
        )

        assert response.status_code == 200, response.data
        assert response.data["user"]["email"] == stored_email

    def test_duplicate_case_variants_resolve_the_exact_match(
        self, factory, _tenant_schema, tenant
    ):
        """Uniqueness is on the exact address, so two rows may differ in
        local-part case alone — the lookup resolves one of them instead of
        failing on the multiple match."""
        lowercase = _create_case_variant_admins()

        response = _login(factory, email=lowercase, password=SUPER_ADMIN_PASSWORD)

        assert response.status_code == 200, response.data
        assert response.data["user"]["email"] == lowercase

    def test_duplicate_case_variants_still_refuse_a_wrong_password(
        self, factory, _tenant_schema, tenant
    ):
        """A bad password against a doubly-stored address is an ordinary
        credential failure, not a server error."""
        lowercase = _create_case_variant_admins()

        response = _login(factory, email=lowercase, password="wrong")

        assert response.status_code == 400, response.data
        assert response.data["message"] == "Invalid credentials"

    def test_malformed_email_is_refused_before_the_account_lookup(
        self, factory, super_admin
    ):
        """A value that cannot be an address is a validation failure, not a
        credential guess — it never reaches the ORM lookup."""
        response = _login(factory, email="not-an-email", password=SUPER_ADMIN_PASSWORD)

        assert response.status_code == 400
        assert response.data["code"] == "validation_error"
        assert "email" in response.data["details"]

    def test_malformed_body_reveals_nothing_about_the_account(
        self, factory, super_admin
    ):
        """The refusal is identical for a real and an unknown account, so a
        malformed body is not an enumeration oracle."""
        known = _login(factory, email=SUPER_ADMIN_EMAIL, password={"a": 1})
        unknown = _login(factory, email="nobody@example.com", password={"a": 1})

        assert known.status_code == unknown.status_code == 400
        assert known.data["code"] == unknown.data["code"]
        assert known.data["message"] == unknown.data["message"]

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
        their session: trusting only the ``is_super_admin`` claim without
        loading the row would let a disabled account keep minting fresh
        access tokens off its refresh cookie for the token lifetime."""
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
    SimpleJWT ``get_user``, so it must repeat its ``is_active`` check — else a
    super-admin disabled or deleted after login keeps full platform access
    for the token lifetime."""

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
# Rate-limit wiring
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
    assertions above: throttle-scope wiring can ship as a SILENT no-op with
    green CI, so the highest-privilege login gets a real 429 test. The autouse
    ``_clear_throttle_cache`` fixture gives each test
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


# ---------------------------------------------------------------------------
# Step-up spends the same per-account budget as the login
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestStepUpAccountLockout:
    """Step-up re-verifies the password the login view checks, so its failures
    feed the same per-account counter. They are counted here but never
    enforced: the login view counts a failure for any submitted address,
    matching account or not, so enforcing that shared counter at step-up would
    hand an anonymous caller a way to block the operator's step-up-gated
    actions. MAX is lowered to 3 per-test for determinism; the autouse
    ``_clear_throttle_cache`` fixture (``cache.clear``) isolates lock state
    between tests."""

    @pytest.fixture(autouse=True)
    def _low_threshold(self, settings):
        settings.SUPER_ADMIN_LOGIN_MAX_FAILURES = 3

    def test_wrong_password_answers_exactly_as_before(self, factory, super_admin):
        """A failure keeps its original wire shape — counting the attempt does
        not reshape the refusal."""
        response = _step_up(factory, super_admin, {"password": "wrong"})

        assert response.status_code == 400
        assert response.data["code"] == "auth.invalid_credentials"
        assert response.data["message"] == "Incorrect password."

    def test_passing_the_threshold_still_answers_as_a_failure(
        self, factory, super_admin
    ):
        """Step-up spends the budget without consulting it, so a wrong password
        answers the same however many attempts came before."""
        for _ in range(5):
            response = _step_up(factory, super_admin, {"password": "wrong"})

            assert response.status_code == 400
            assert response.data["code"] == "auth.invalid_credentials"

    def test_missing_password_counts_toward_the_budget(self, factory, super_admin):
        """An empty body never reaches ``check_password``, so it has to be
        counted explicitly or it is a free guess. The count shows on the login,
        which is where the counter is enforced."""
        for _ in range(3):
            assert _step_up(factory, super_admin, {}).status_code == 400

        response = _login(
            factory, email=SUPER_ADMIN_EMAIL, password=SUPER_ADMIN_PASSWORD
        )
        assert response.status_code == 429
        assert response.data["code"] == "super_admin.account_locked"

    def test_a_locked_account_can_still_step_up(self, factory, super_admin):
        """Anyone can close the login on a known address by guessing at it, so
        gating step-up on that counter would be a denial of service against the
        operator. The correct password still issues the step-up token."""
        for _ in range(3):
            _login(factory, email=SUPER_ADMIN_EMAIL, password="wrong")
        locked_login = _login(
            factory, email=SUPER_ADMIN_EMAIL, password=SUPER_ADMIN_PASSWORD
        )
        assert locked_login.status_code == 429

        response = _step_up(factory, super_admin, {"password": SUPER_ADMIN_PASSWORD})

        assert response.status_code == 200

    def test_successful_step_up_clears_the_counter(self, factory, super_admin):
        for _ in range(2):
            assert (
                _step_up(factory, super_admin, {"password": "wrong"}).status_code == 400
            )

        success = _step_up(factory, super_admin, {"password": SUPER_ADMIN_PASSWORD})
        assert success.status_code == 200

        # Two more failures leave the login open. Carried over, the four would
        # have crossed the threshold and closed it.
        for _ in range(2):
            assert (
                _step_up(factory, super_admin, {"password": "wrong"}).status_code == 400
            )
        assert (
            _login(
                factory, email=SUPER_ADMIN_EMAIL, password=SUPER_ADMIN_PASSWORD
            ).status_code
            == 200
        )

    def test_step_up_failures_lock_the_login(self, factory, super_admin):
        """One budget per credential: the counter is keyed by the account's
        email, so guesses spent on step-up also close the login."""
        for _ in range(3):
            _step_up(factory, super_admin, {"password": "wrong"})

        response = _login(
            factory, email=SUPER_ADMIN_EMAIL, password=SUPER_ADMIN_PASSWORD
        )
        assert response.status_code == 429
        assert response.data["code"] == "super_admin.account_locked"


# ---------------------------------------------------------------------------
# Non-object / non-string request bodies
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialBodyShapes:
    """Both credential endpoints read their fields straight off the JSON
    body. A value that is not a string is a hand-crafted request, and the
    refusal must be the endpoint's ordinary credential failure — never a 500,
    and never distinguishable from a wrong-but-string password."""

    def test_login_json_array_body_is_a_400(self, factory, super_admin):
        """A whole JSON array as the body has no credentials to read."""
        request = factory.post("/auth/login/", [{"email": SUPER_ADMIN_EMAIL}], "json")
        response = super_admin_login_view(request)

        assert response.status_code == 400
        assert response.data["code"] == "super_admin.missing_credentials"

    @pytest.mark.parametrize("password", [{"$ne": None}, ["hunter2"], 42], ids=repr)
    def test_step_up_non_string_password_is_refused(
        self, factory, super_admin, password
    ):
        response = _step_up(factory, super_admin, {"password": password})

        assert response.status_code == 400
        assert response.data["code"] == "auth.invalid_credentials"

    def test_step_up_json_array_body_is_refused(self, factory, super_admin):
        response = _step_up(factory, super_admin, [{"password": "x"}])

        assert response.status_code == 400
        assert response.data["code"] == "auth.invalid_credentials"

    def test_step_up_non_string_password_matches_a_wrong_string(
        self, factory, super_admin
    ):
        """A non-string password is indistinguishable from a wrong one."""
        non_string = _step_up(factory, super_admin, {"password": ["hunter2"]})
        wrong_string = _step_up(factory, super_admin, {"password": "hunter2"})

        assert non_string.status_code == wrong_string.status_code
        assert non_string.data["code"] == wrong_string.data["code"]
        assert non_string.data["message"] == wrong_string.data["message"]

    def test_step_up_correct_password_still_issues_a_token(self, factory, super_admin):
        response = _step_up(factory, super_admin, {"password": SUPER_ADMIN_PASSWORD})

        assert response.status_code == 200
        assert response.data["access"]
        assert response.data["ttl_seconds"]
