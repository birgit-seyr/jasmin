"""The /health/ liveness probe answers 200 ahead of tenant resolution (CFG-1).

Tenant resolution is subdomain-only, with no "no-tenant" fallback: an
unrecognized host has TenantMainMiddleware raise "no tenant for hostname"
(HTTP 404) before any view runs. The Docker HEALTHCHECK, the gateway nginx
healthcheck, and the uptime monitor hit /health/ on hosts that map to no
tenant (localhost, 127.0.0.1, the upstream name), so the probe must be
answered AHEAD of the tenant middleware.

These tests drive the full middleware stack with a deliberately unresolvable
Host. Getting 200 (not 404) proves HealthCheckMiddleware both runs and sits
above TenantMainMiddleware — no DB or tenant context required.
"""

from __future__ import annotations


def test_health_returns_200_on_unresolvable_host(client):
    resp = client.get("/health/", HTTP_HOST="nonexistent.invalid")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_head_returns_200_on_unresolvable_host(client):
    resp = client.head("/health/", HTTP_HOST="nonexistent.invalid")
    assert resp.status_code == 200
