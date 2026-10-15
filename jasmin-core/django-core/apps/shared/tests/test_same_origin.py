"""The same-origin guard on the refresh-cookie endpoints, and the production
CORS settings it backs up.

Every tenant host and the super-admin host share one registrable domain, so a
page on one of them is same-site to all the others and its requests carry their
``SameSite=Strict`` refresh cookies. Production CORS answers no sibling origin,
so such a page can't read a login or refresh answer; the guard
(``apps.shared.same_origin``) refuses the request itself, so it can't mint,
rotate or revoke a session either.

The tenant endpoints are called through the routed stack. The super-admin ones
are called as views: their URLconf belongs to the public schema, and
``testserver`` is a tenant host.
"""

from __future__ import annotations

import ast
import runpy
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import override_settings
from django_tenants.utils import schema_context
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.test import APIClient, APIRequestFactory

from apps.accounts.models import JasminUser
from apps.accounts.services import issue_post_two_factor_tokens
from apps.commissioning.tests.factories import JasminUserFactory
from apps.shared.auth_cookies import (
    SUPER_ADMIN_REFRESH_COOKIE,
    TENANT_REFRESH_COOKIE,
)
from apps.shared.same_origin import require_same_origin
from apps.shared.super_admin.models import SuperAdmin, SuperAdminBlacklistedToken
from apps.shared.super_admin.views.auth_views import (
    SuperAdminRefreshToken,
    super_admin_login_view,
    super_admin_logout_view,
    super_admin_token_refresh_view,
)

pytestmark = pytest.mark.django_db

# This file lives at apps/shared/tests/<file>, so django-core is three up.
DJANGO_CORE = Path(__file__).resolve().parents[3]

REFUSED_CODE = "auth.cross_origin_refused"
PASSWORD = "Z3rgRushIsScary!42"
TENANT_HOST = "pytest.localhost"  # a Domain row of the test tenant
SUPER_ADMIN_HOST = "marillen.localhost"
SIBLING_ORIGIN = "http://other-farm.localhost"

# What a browser sends from a page on another host: current browsers classify it
# in Sec-Fetch-Site (same-site for a sibling subdomain, cross-site beyond the
# farm's domain), older ones only name the page's origin.
CROSS_ORIGIN_HEADERS = [
    pytest.param({"HTTP_SEC_FETCH_SITE": "same-site"}, id="same-site-fetch"),
    pytest.param({"HTTP_SEC_FETCH_SITE": "cross-site"}, id="cross-site-fetch"),
    pytest.param({"HTTP_ORIGIN": SIBLING_ORIGIN}, id="sibling-origin"),
]


def _own_origin_headers(host: str) -> list:
    """What a page on ``host`` sends, plus a caller that is no browser. The
    gateway hands the backend a Host without a port, while a dev origin has one.
    """
    return [
        pytest.param({"HTTP_SEC_FETCH_SITE": "same-origin"}, id="same-origin-fetch"),
        pytest.param({"HTTP_ORIGIN": f"http://{host}"}, id="own-origin"),
        pytest.param({"HTTP_ORIGIN": f"http://{host}:3000"}, id="own-origin-port"),
        pytest.param({}, id="no-browser-headers"),
    ]


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """The login endpoints carry throttle scopes whose buckets live in the
    default cache, and tests run in random order."""
    cache.clear()
    yield
    cache.clear()


# --------------------------------------------------------------------------- #
# Production settings                                                          #
# --------------------------------------------------------------------------- #

# Enough for the DEBUG=False boot guards of config/settings.py. RUNNING_IN_DOCKER
# skips its ``from .settings_local import *``, which needs the config package.
PRODUCTION_ENV = {
    "DEBUG": "False",
    "RUNNING_IN_DOCKER": "True",
    "DJANGO_SECRET_KEY": "test-only-secret-key",
    "FIELD_ENCRYPTION_KEY": "test-only-field-key",
    "INVOICE_HASH_KEY": "test-only-invoice-hash-key",
    "EMAIL_ADMIN": "ops@farm.example",
    "EMAIL_HOST": "smtp.farm.example",
    "FRONTEND_DOMAIN": "farm.example",
    "POSTGRES_DB": "jasmin",
    "POSTGRES_USER": "jasmin",
    "POSTGRES_PASSWORD": "test-only-db-password",
    "REDIS_URL": "redis://redis:6379/0",
}
LISTED_ORIGIN = "https://ops.farm.example"
CORS_SETTING_NAMES = (
    "CORS_ALLOW_ALL_ORIGINS",
    "CORS_ALLOWED_ORIGINS",
    "CORS_ALLOWED_ORIGIN_REGEXES",
    "CORS_ALLOW_CREDENTIALS",
)


def _production_settings(monkeypatch, **env: str) -> dict:
    """``config/settings.py`` as a production process evaluates it."""
    with monkeypatch.context() as environment:
        for name in (
            "CORS_ALLOWED_ORIGINS",
            "CSRF_TRUSTED_ORIGINS",
            "AUTH_ORIGIN_GUARD",
            "SENTRY_DSN",
        ):
            environment.delenv(name, raising=False)
        for name, value in {**PRODUCTION_ENV, **env}.items():
            environment.setenv(name, value)
        return runpy.run_path(str(DJANGO_CORE / "config" / "settings.py"))


def _cors_answer(method: str, origin: str):
    client = APIClient()
    if method == "preflight":
        return client.options(
            "/api/auth/refresh/",
            HTTP_ORIGIN=origin,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        )
    return client.post("/api/auth/refresh/", HTTP_ORIGIN=origin)


class TestProductionSettings:
    def test_no_origin_pattern_and_no_origin_by_default(self, monkeypatch):
        production = _production_settings(monkeypatch)

        assert production["CORS_ALLOW_ALL_ORIGINS"] is False
        assert production["CORS_ALLOWED_ORIGIN_REGEXES"] == []
        assert production["CORS_ALLOWED_ORIGINS"] == []

    def test_listed_origins_pass_through_without_empty_entries(self, monkeypatch):
        production = _production_settings(
            monkeypatch,
            CORS_ALLOWED_ORIGINS=f"{LISTED_ORIGIN}, ,https://tools.example,",
        )

        assert production["CORS_ALLOWED_ORIGINS"] == [
            LISTED_ORIGIN,
            "https://tools.example",
        ]

    def test_csrf_trusts_the_farm_hosts_and_the_listed_extras(self, monkeypatch):
        production = _production_settings(
            monkeypatch, CSRF_TRUSTED_ORIGINS="https://extra.example"
        )

        assert production["CSRF_TRUSTED_ORIGINS"] == [
            "https://farm.example",
            "https://*.farm.example",
            "https://extra.example",
        ]

    @pytest.mark.parametrize("method", ["preflight", "post"])
    def test_a_sibling_subdomain_gets_no_cors_answer(self, monkeypatch, tenant, method):
        production = _production_settings(
            monkeypatch, CORS_ALLOWED_ORIGINS=LISTED_ORIGIN
        )
        cors_settings = {name: production[name] for name in CORS_SETTING_NAMES}

        # The guard is off, so the answer below is CORS alone.
        with override_settings(AUTH_ORIGIN_GUARD=False, **cors_settings):
            sibling = _cors_answer(method, "https://other-farm.farm.example")
            listed = _cors_answer(method, LISTED_ORIGIN)

        assert "Access-Control-Allow-Origin" not in sibling
        # A listed origin is answered, so the absence above is the settings' doing.
        assert listed["Access-Control-Allow-Origin"] == LISTED_ORIGIN

    @pytest.mark.parametrize(
        ("value", "enabled"),
        [
            (None, True),
            ("True", True),
            ("", True),
            ("yes", True),
            ("False", False),
            ("false", False),
        ],
    )
    def test_only_false_switches_the_guard_off(self, monkeypatch, value, enabled):
        env = {} if value is None else {"AUTH_ORIGIN_GUARD": value}

        assert _production_settings(monkeypatch, **env)["AUTH_ORIGIN_GUARD"] is enabled


# --------------------------------------------------------------------------- #
# The rule                                                                     #
# --------------------------------------------------------------------------- #


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@require_same_origin
def _probe_view(request):
    return Response({"reached": True})


def _probe(host: str, headers: dict[str, str]):
    request = APIRequestFactory().post("/probe/", HTTP_HOST=host, **headers)
    return _probe_view(request)


@pytest.fixture
def guard_logger():
    with patch("apps.shared.same_origin.logger") as mock_logger:
        yield mock_logger


def _rendered(mock_logger) -> str:
    """The log line as it reaches the handler, format string applied."""
    fmt, *args = mock_logger.warning.call_args[0]
    return fmt % tuple(args)


class TestTheRule:
    @pytest.mark.parametrize(
        ("host", "headers"),
        [
            pytest.param(
                TENANT_HOST, {"HTTP_SEC_FETCH_SITE": "none"}, id="user-started"
            ),
            pytest.param(
                TENANT_HOST,
                {"HTTP_SEC_FETCH_SITE": "Same-Origin"},
                id="fetch-site-in-another-case",
            ),
            pytest.param(
                TENANT_HOST,
                {"HTTP_SEC_FETCH_SITE": "same-origin", "HTTP_ORIGIN": SIBLING_ORIGIN},
                id="fetch-site-decides-over-origin",
            ),
            pytest.param(TENANT_HOST, {"HTTP_ORIGIN": "null"}, id="opaque-origin"),
            pytest.param(
                TENANT_HOST,
                {"HTTP_ORIGIN": "https://PYTEST.Localhost"},
                id="origin-in-another-case",
            ),
            pytest.param(
                f"{TENANT_HOST}:8000",
                {"HTTP_ORIGIN": f"http://{TENANT_HOST}:3000"},
                id="ports-differ-behind-the-dev-proxy",
            ),
        ],
    )
    def test_passes(self, host, headers):
        response = _probe(host, headers)

        assert response.status_code == 200, response.data

    @pytest.mark.parametrize(
        ("host", "headers"),
        [
            pytest.param(
                TENANT_HOST,
                {
                    "HTTP_SEC_FETCH_SITE": "cross-site",
                    "HTTP_ORIGIN": f"http://{TENANT_HOST}",
                },
                id="fetch-site-decides-over-a-matching-origin",
            ),
            pytest.param(
                TENANT_HOST,
                {"HTTP_ORIGIN": f"http://{TENANT_HOST}.attacker.example"},
                id="own-host-as-a-prefix",
            ),
            pytest.param(
                TENANT_HOST, {"HTTP_ORIGIN": "http://localhost"}, id="parent-domain"
            ),
            pytest.param(
                TENANT_HOST, {"HTTP_ORIGIN": TENANT_HOST}, id="origin-without-scheme"
            ),
            pytest.param(
                TENANT_HOST,
                {"HTTP_ORIGIN": f"http://[{TENANT_HOST}"},
                id="unparseable-origin",
            ),
        ],
    )
    def test_refused(self, host, headers):
        response = _probe(host, headers)

        assert response.status_code == 403
        assert response.data["code"] == REFUSED_CODE

    def test_a_refusal_is_logged_with_its_reason(self, guard_logger):
        _probe(TENANT_HOST, {"HTTP_ORIGIN": SIBLING_ORIGIN})

        line = _rendered(guard_logger)
        assert line.startswith(
            "auth.cross_origin_refused reason=origin_host path=/probe/ "
            f"host={TENANT_HOST} origin='{SIBLING_ORIGIN}' sec_fetch_site=None"
        )

    def test_logged_header_values_are_bounded_and_escaped(self, guard_logger):
        _probe(TENANT_HOST, {"HTTP_SEC_FETCH_SITE": "x\n" + "y" * 5000})

        line = _rendered(guard_logger)
        assert "reason=fetch_site" in line
        assert "\n" not in line
        assert len(line) < 500

    def test_a_passing_request_logs_nothing(self, guard_logger):
        _probe(TENANT_HOST, {"HTTP_SEC_FETCH_SITE": "same-origin"})

        assert guard_logger.warning.call_count == 0

    def test_the_kill_switch_skips_the_check(self, settings, guard_logger):
        settings.AUTH_ORIGIN_GUARD = False

        response = _probe(TENANT_HOST, {"HTTP_SEC_FETCH_SITE": "cross-site"})

        assert response.status_code == 200
        assert guard_logger.warning.call_count == 0


# --------------------------------------------------------------------------- #
# Tenant endpoints                                                             #
# --------------------------------------------------------------------------- #

# What each view answers once the guard lets the request below through.
TENANT_VIEW_STATUS = {
    "login/": 200,
    "refresh/": 200,
    "logout/": 200,
    "logout-all/": 200,
    # A made-up challenge, which the view itself refuses.
    "two-factor/verify/": 400,
}
TENANT_COOKIE_WRITERS = {"login/", "refresh/", "logout/", "logout-all/"}


@dataclass(frozen=True)
class TenantSession:
    user: JasminUser
    refresh: str


@pytest.fixture
def tenant_session(tenant) -> TenantSession:
    """A user with a password and a live refresh token on the test tenant."""
    user = JasminUserFactory()
    user.set_password(PASSWORD)
    user.save(update_fields=["password"])
    tokens = issue_post_two_factor_tokens(user=user, tenant=tenant)
    return TenantSession(user=user, refresh=tokens.refresh)


def _post_to_tenant(endpoint: str, session: TenantSession, headers: dict[str, str]):
    client = APIClient(HTTP_HOST=TENANT_HOST, **headers)
    client.cookies[TENANT_REFRESH_COOKIE] = session.refresh
    if endpoint == "logout-all/":
        client.force_authenticate(user=session.user)
    body = {
        "login/": {"email": session.user.email, "password": PASSWORD},
        "two-factor/verify/": {"challenge_token": "made-up", "code": "123456"},
    }.get(endpoint, {})
    return client.post(f"/api/auth/{endpoint}", body, format="json")


def _session_still_refreshes(session: TenantSession) -> bool:
    client = APIClient(HTTP_HOST=TENANT_HOST)
    client.cookies[TENANT_REFRESH_COOKIE] = session.refresh
    return client.post("/api/auth/refresh/").status_code == 200


class TestTenantEndpoints:
    @pytest.mark.parametrize("headers", CROSS_ORIGIN_HEADERS)
    @pytest.mark.parametrize("endpoint", list(TENANT_VIEW_STATUS))
    def test_cross_origin_request_is_refused_and_changes_nothing(
        self, tenant_session, endpoint, headers
    ):
        response = _post_to_tenant(endpoint, tenant_session, headers)

        assert response.status_code == 403
        assert response.data["code"] == REFUSED_CODE
        assert TENANT_REFRESH_COOKIE not in response.cookies
        # Neither rotated, revoked nor blacklisted.
        assert _session_still_refreshes(tenant_session)

    @pytest.mark.parametrize("headers", _own_origin_headers(TENANT_HOST))
    @pytest.mark.parametrize("endpoint", list(TENANT_VIEW_STATUS))
    def test_own_origin_request_reaches_the_view(
        self, tenant_session, endpoint, headers
    ):
        response = _post_to_tenant(endpoint, tenant_session, headers)

        assert response.status_code == TENANT_VIEW_STATUS[endpoint], response.data
        if endpoint in TENANT_COOKIE_WRITERS:
            assert TENANT_REFRESH_COOKIE in response.cookies

    @pytest.mark.parametrize("headers", CROSS_ORIGIN_HEADERS)
    @pytest.mark.parametrize("endpoint", list(TENANT_VIEW_STATUS))
    def test_the_kill_switch_lets_every_request_through(
        self, settings, tenant_session, endpoint, headers
    ):
        settings.AUTH_ORIGIN_GUARD = False

        response = _post_to_tenant(endpoint, tenant_session, headers)

        assert response.status_code == TENANT_VIEW_STATUS[endpoint], response.data


# --------------------------------------------------------------------------- #
# Super-admin endpoints                                                        #
# --------------------------------------------------------------------------- #

SUPER_ADMIN_VIEWS = {
    "login": super_admin_login_view,
    "refresh": super_admin_token_refresh_view,
    "logout": super_admin_logout_view,
}


@pytest.fixture
def super_admin(_tenant_schema) -> SuperAdmin:
    with schema_context("public"):
        admin, _ = SuperAdmin.objects.get_or_create(
            email="origin-guard@example.com",
            defaults={"first_name": "Origin", "last_name": "Guard"},
        )
        admin.is_active = True
        admin.set_password(PASSWORD)
        admin.save()
    return admin


@pytest.fixture
def super_admin_refresh(super_admin) -> SuperAdminRefreshToken:
    refresh = SuperAdminRefreshToken()
    refresh["user_id"] = super_admin.id
    refresh["email"] = super_admin.email
    refresh["is_super_admin"] = True
    return refresh


def _post_to_super_admin(
    endpoint: str,
    admin: SuperAdmin,
    refresh: SuperAdminRefreshToken,
    headers: dict[str, str],
):
    body = {"email": admin.email, "password": PASSWORD} if endpoint == "login" else {}
    request = APIRequestFactory().post(
        f"/api/super-admin/auth/{endpoint}/",
        body,
        format="json",
        HTTP_HOST=SUPER_ADMIN_HOST,
        **headers,
    )
    request.COOKIES[SUPER_ADMIN_REFRESH_COOKIE] = str(refresh)
    return SUPER_ADMIN_VIEWS[endpoint](request)


def _blacklisted(refresh: SuperAdminRefreshToken) -> bool:
    with schema_context("public"):
        return SuperAdminBlacklistedToken.objects.filter(jti=refresh["jti"]).exists()


class TestSuperAdminEndpoints:
    @pytest.mark.parametrize("headers", CROSS_ORIGIN_HEADERS)
    @pytest.mark.parametrize("endpoint", list(SUPER_ADMIN_VIEWS))
    def test_cross_origin_request_is_refused_and_changes_nothing(
        self, super_admin, super_admin_refresh, endpoint, headers
    ):
        response = _post_to_super_admin(
            endpoint, super_admin, super_admin_refresh, headers
        )

        assert response.status_code == 403
        assert response.data["code"] == REFUSED_CODE
        assert SUPER_ADMIN_REFRESH_COOKIE not in response.cookies
        assert not _blacklisted(super_admin_refresh)

    @pytest.mark.parametrize("headers", _own_origin_headers(SUPER_ADMIN_HOST))
    @pytest.mark.parametrize("endpoint", list(SUPER_ADMIN_VIEWS))
    def test_own_origin_request_reaches_the_view(
        self, super_admin, super_admin_refresh, endpoint, headers
    ):
        response = _post_to_super_admin(
            endpoint, super_admin, super_admin_refresh, headers
        )

        assert response.status_code == 200, response.data
        # Login sets the cookie, refresh rotates it, logout clears it.
        assert SUPER_ADMIN_REFRESH_COOKIE in response.cookies

    @pytest.mark.parametrize("headers", CROSS_ORIGIN_HEADERS)
    @pytest.mark.parametrize("endpoint", list(SUPER_ADMIN_VIEWS))
    def test_the_kill_switch_lets_every_request_through(
        self, settings, super_admin, super_admin_refresh, endpoint, headers
    ):
        settings.AUTH_ORIGIN_GUARD = False

        response = _post_to_super_admin(
            endpoint, super_admin, super_admin_refresh, headers
        )

        assert response.status_code == 200, response.data


# --------------------------------------------------------------------------- #
# Coverage                                                                     #
# --------------------------------------------------------------------------- #

COOKIE_HELPERS = frozenset(
    {
        "set_tenant_refresh_cookie",
        "clear_tenant_refresh_cookie",
        "get_tenant_refresh_token",
        "set_super_admin_refresh_cookie",
        "clear_super_admin_refresh_cookie",
        "get_super_admin_refresh_token",
    }
)
KNOWN_COOKIE_VIEWS = frozenset(
    {
        "user_login_view",
        "user_token_refresh_view",
        "user_logout_view",
        "user_logout_all_view",
        "two_factor_verify_view",
        "super_admin_login_view",
        "super_admin_token_refresh_view",
        "super_admin_logout_view",
    }
)


def _name(node: ast.expr) -> str | None:
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _cookie_views() -> dict[str, set[str | None]]:
    """Every ``@api_view`` function under ``apps/`` that calls a refresh-cookie
    helper, directly or through other functions of its module, mapped to the
    names of its decorators."""
    views: dict[str, set[str | None]] = {}
    apps_dir = DJANGO_CORE / "apps"
    for path in sorted(apps_dir.rglob("*.py")):
        if {"tests", "migrations"} & set(path.relative_to(apps_dir).parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions = {
            node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
        }
        calls = {
            name: {_name(call) for call in ast.walk(node) if isinstance(call, ast.Call)}
            for name, node in functions.items()
        }
        reaching = {name for name, called in calls.items() if called & COOKIE_HELPERS}
        while grown := {
            name
            for name, called in calls.items()
            if name not in reaching and called & reaching
        }:
            reaching |= grown
        for name in reaching:
            decorators = {_name(node) for node in functions[name].decorator_list}
            if "api_view" in decorators:
                views[name] = decorators
    return views


def test_every_refresh_cookie_endpoint_is_guarded():
    views = _cookie_views()

    # The scan has to see the endpoints that exist, or it proves nothing.
    assert KNOWN_COOKIE_VIEWS <= views.keys()
    unguarded = sorted(
        name
        for name, decorators in views.items()
        if "require_same_origin" not in decorators
    )
    assert not unguarded, (
        "These endpoints set, read or rotate a refresh cookie without "
        f"@require_same_origin: {unguarded}"
    )
