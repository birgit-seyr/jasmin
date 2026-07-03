"""Tests for ``SuperAdminIPAllowlistMiddleware`` — the app-layer defense-in-depth
IP allowlist over ``/api/super-admin/`` (CFG-1).

Pure middleware unit tests: a ``RequestFactory`` request + a sentinel
``get_response`` let us assert "passed through" vs "blocked with 403" without
the DB or routing.
"""

from __future__ import annotations

import json

import pytest
from django.http import HttpResponse
from django.test import Client, RequestFactory, override_settings

from apps.shared.super_admin.middleware import SuperAdminIPAllowlistMiddleware

SUPER_ADMIN_PATH = "/api/super-admin/auth/login/"


def _build():
    """Return (middleware, sentinel) — sentinel is what get_response yields, so
    ``resp is sentinel`` means the request was allowed through."""
    sentinel = HttpResponse("ok")
    middleware = SuperAdminIPAllowlistMiddleware(lambda _req: sentinel)
    return middleware, sentinel


@override_settings(SUPER_ADMIN_ALLOWED_IPS=[])
def test_noop_when_allowlist_unset():
    """No allowlist configured -> middleware never interferes (dev / nginx-only
    deployments keep working)."""
    middleware, sentinel = _build()
    req = RequestFactory().get(SUPER_ADMIN_PATH, REMOTE_ADDR="198.51.100.7")
    assert middleware(req) is sentinel


@override_settings(SUPER_ADMIN_ALLOWED_IPS=["203.0.113.0/24"])
def test_blocks_disallowed_ip():
    middleware, sentinel = _build()
    req = RequestFactory().get(SUPER_ADMIN_PATH, REMOTE_ADDR="198.51.100.7")
    resp = middleware(req)
    assert resp is not sentinel
    assert resp.status_code == 403
    assert json.loads(resp.content)["code"] == "super_admin.ip_not_allowed"


@override_settings(SUPER_ADMIN_ALLOWED_IPS=["203.0.113.0/24"])
def test_allows_ip_in_cidr():
    middleware, sentinel = _build()
    req = RequestFactory().get(SUPER_ADMIN_PATH, REMOTE_ADDR="203.0.113.5")
    assert middleware(req) is sentinel


@override_settings(SUPER_ADMIN_ALLOWED_IPS=["2001:db8::/64"])
def test_allows_ipv6_in_cidr():
    middleware, sentinel = _build()
    req = RequestFactory().get(SUPER_ADMIN_PATH, REMOTE_ADDR="2001:db8::abcd")
    assert middleware(req) is sentinel


@override_settings(SUPER_ADMIN_ALLOWED_IPS=["203.0.113.0/24"])
def test_non_super_admin_path_is_unaffected():
    """The allowlist only gates the super-admin prefix — a tenant API call from
    a non-allowlisted IP must pass through untouched."""
    middleware, sentinel = _build()
    req = RequestFactory().get("/api/members/", REMOTE_ADDR="198.51.100.7")
    assert middleware(req) is sentinel


@override_settings(SUPER_ADMIN_ALLOWED_IPS=["203.0.113.5"], TRUSTED_PROXY_COUNT=1)
def test_spoofed_x_forwarded_for_does_not_bypass():
    """An attacker putting an allowed IP at the LEFT of X-Forwarded-For must not
    get in: with one trusted proxy hop, the trusted entry is the rightmost
    (nginx-appended) one — here the attacker's real, non-allowed IP."""
    middleware, sentinel = _build()
    req = RequestFactory().get(
        SUPER_ADMIN_PATH,
        # left = forged allowed IP, right = real client (what nginx appends)
        HTTP_X_FORWARDED_FOR="203.0.113.5, 198.51.100.7",
        REMOTE_ADDR="198.51.100.7",
    )
    resp = middleware(req)
    assert resp is not sentinel
    assert resp.status_code == 403


@override_settings(SUPER_ADMIN_ALLOWED_IPS=["203.0.113.5"], TRUSTED_PROXY_COUNT=1)
def test_trusted_rightmost_xff_is_allowed():
    """Mirror of the spoof test: the legitimately-appended rightmost entry is
    the allowed IP -> passes."""
    middleware, sentinel = _build()
    req = RequestFactory().get(
        SUPER_ADMIN_PATH,
        HTTP_X_FORWARDED_FOR="10.9.9.9, 203.0.113.5",
        REMOTE_ADDR="203.0.113.5",
    )
    assert middleware(req) is sentinel


@override_settings(SUPER_ADMIN_ALLOWED_IPS=["not-an-ip", "203.0.113.0/24"])
def test_malformed_entry_is_skipped_not_fail_open():
    """A typo'd entry is ignored (logged), the valid ones still enforce — a bad
    entry must not silently open the gate."""
    middleware, sentinel = _build()
    blocked = middleware(
        RequestFactory().get(SUPER_ADMIN_PATH, REMOTE_ADDR="198.51.100.7")
    )
    assert blocked.status_code == 403
    allowed = middleware(
        RequestFactory().get(SUPER_ADMIN_PATH, REMOTE_ADDR="203.0.113.9")
    )
    assert allowed is sentinel


@pytest.mark.django_db
@override_settings(SUPER_ADMIN_ALLOWED_IPS=["203.0.113.0/24"])
def test_end_to_end_blocks_real_super_admin_login(_tenant_schema):
    """End-to-end through the real WSGI middleware chain: a request to the
    actual super-admin login URL from a non-allowlisted IP is 403'd before it
    reaches any view (the middleware sits ahead of TenantMainMiddleware, so it
    short-circuits before schema routing). Proves the control is actually wired,
    not just unit-correct."""
    resp = Client().get("/api/super-admin/auth/login/", REMOTE_ADDR="198.51.100.7")
    assert resp.status_code == 403
    assert resp.json()["code"] == "super_admin.ip_not_allowed"
