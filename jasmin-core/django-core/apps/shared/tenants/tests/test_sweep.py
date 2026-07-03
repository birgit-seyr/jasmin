"""Tests for the per-tenant sweep helper.

A deactivated tenant is a frozen tenant — server-initiated housekeeping sweeps
must skip it by default (offboarding / non-payment / breach), while an explicit
``include_inactive=True`` opt-in still reaches it (e.g. forensic checks).
"""

from __future__ import annotations

import pytest

from apps.shared.tenants.models import Tenant
from apps.shared.tenants.sweep import for_each_tenant


@pytest.mark.django_db
def test_for_each_tenant_skips_inactive_by_default(tenant):
    # Deactivate the (session) tenant for the duration of this test.
    Tenant.objects.filter(pk=tenant.pk).update(is_active=False)

    visited: list[str] = []
    for_each_tenant(lambda t: visited.append(t.schema_name))
    assert tenant.schema_name not in visited

    # …but an explicit opt-in still reaches it.
    visited.clear()
    for_each_tenant(lambda t: visited.append(t.schema_name), include_inactive=True)
    assert tenant.schema_name in visited


@pytest.mark.django_db
def test_for_each_tenant_visits_active(tenant):
    visited: list[str] = []
    for_each_tenant(lambda t: visited.append(t.schema_name))
    assert tenant.schema_name in visited
