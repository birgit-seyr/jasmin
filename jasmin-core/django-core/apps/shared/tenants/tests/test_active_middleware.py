"""Tests for ``TenantActiveMiddleware`` — the ``Tenant.is_active`` kill-switch.

The middleware is a thin gate, so these exercise it directly with a
``RequestFactory`` request + a stand-in ``request.tenant`` rather than
booting the whole routed stack. Behaviours pinned:

  - inactive tenant on a tenant schema → 403 ``tenant.deactivated``
  - active tenant → request passes through untouched
  - OPTIONS preflight always passes (must not break CORS negotiation)
  - the public/platform schema is never gated (super-admin host must stay
    reachable to flip the flag back)
  - a request that never resolved a tenant doesn't crash the gate
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from django.test import RequestFactory
from django_tenants.utils import schema_context

from apps.shared.tenants.middleware import TenantActiveMiddleware

# Recognizable return so "passed through" is distinguishable from a 403.
_PASSED = object()


def _middleware() -> TenantActiveMiddleware:
    return TenantActiveMiddleware(lambda request: _PASSED)


@pytest.mark.django_db
class TestTenantActiveMiddleware:
    def test_inactive_tenant_is_blocked(self, tenant):
        request = RequestFactory().get("/api/members/")
        request.tenant = SimpleNamespace(is_active=False)

        response = _middleware()(request)

        assert response is not _PASSED
        assert response.status_code == 403
        assert json.loads(response.content)["code"] == "tenant.deactivated"

    def test_active_tenant_passes_through(self, tenant):
        request = RequestFactory().get("/api/members/")
        request.tenant = SimpleNamespace(is_active=True)

        assert _middleware()(request) is _PASSED

    def test_options_preflight_passes_even_when_inactive(self, tenant):
        # Blocking the CORS preflight would surface as a browser CORS error
        # instead of a readable coded 403 on the real request.
        request = RequestFactory().options("/api/members/")
        request.tenant = SimpleNamespace(is_active=False)

        assert _middleware()(request) is _PASSED

    def test_public_schema_is_never_gated(self, tenant):
        # On the public/platform schema ``Tenant.is_active`` doesn't apply —
        # the super-admin host must stay reachable to re-activate a tenant.
        with schema_context("public"):
            request = RequestFactory().get("/api/super-admin/tenants/")
            request.tenant = SimpleNamespace(is_active=False)

            assert _middleware()(request) is _PASSED

    def test_request_without_resolved_tenant_passes_through(self, tenant):
        # An unknown host is 404'd by TenantMainMiddleware upstream; if a
        # request somehow reaches here with no tenant, the gate must not crash.
        request = RequestFactory().get("/api/members/")

        assert _middleware()(request) is _PASSED
