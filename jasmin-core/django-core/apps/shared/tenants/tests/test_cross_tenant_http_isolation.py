"""End-to-end multi-tenant HTTP isolation.

This complements ``test_viewset_isolation_matrix.py`` (JWT layer) and
``test_schema_isolation.py`` (ORM layer) by covering the full HTTP path:

  - Create object X in tenant B's schema.
  - Issue an authenticated request to a tenant-A host as a tenant-A user.
  - Assert X is invisible: 404 on the detail endpoint, absent from list.

If this ever returns 200 with X's data, a tenant has leaked into another
tenant's responses — the most severe security failure the platform can
have. Lock this down hard.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.db import connection
from django_tenants.utils import schema_context
from rest_framework.test import APIClient

from apps.commissioning.models import Member
from apps.commissioning.tests.factories import JasminUserFactory, MemberFactory
from apps.shared.tenants.models import Domain, Tenant

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Second-tenant fixture
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def _tenant_b_schema(django_db_setup, django_db_blocker):
    """Create a SECOND tenant schema (``test_pytest_b``) once per session.

    Mirrors the ``_tenant_schema`` fixture in
    ``apps/commissioning/tests/conftest.py`` but for the "other tenant"
    side of cross-tenant isolation tests. Idempotent (get-or-create).
    """
    with django_db_blocker.unblock():
        t = Tenant.objects.filter(schema_name="test_pytest_b").first()
        if t is None:
            t = Tenant(schema_name="test_pytest_b", name="Test Farm B")
            t.save()
        else:
            call_command(
                "migrate_schemas",
                schema_name="test_pytest_b",
                interactive=False,
                verbosity=0,
            )
        if not Domain.objects.filter(domain="pytest-b.localhost").exists():
            Domain.objects.create(
                tenant=t, domain="pytest-b.localhost", is_primary=True
            )
        connection.set_schema_to_public()
    yield t
    with django_db_blocker.unblock():
        try:
            t.delete()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
# We use ``force_authenticate`` rather than minting a real JWT here. The
# JWT-binding layer is already covered by
# ``test_viewset_isolation_matrix.py``; this file exercises the *queryset*
# isolation path — does the ORM, scoped to schema A, ever return a row
# that lives in schema B? force_authenticate keeps the test focused on
# that question and avoids host-resolution noise.


def test_tenant_a_cannot_retrieve_tenant_b_member_via_http(tenant, _tenant_b_schema):
    """Object exists in tenant B; tenant A request must 404, not 200.

    Steps:
      1. Switch to tenant B's schema, create a Member X.
      2. Switch back to tenant A's schema.
      3. Create a tenant-A user, authenticate as them.
      4. GET ``/api/commissioning/members/<X.pk>/`` against the default
         ``testserver`` host (which TenantMainMiddleware resolves to
         tenant A's schema via the ``testserver`` Domain row created in
         the shared conftest).
      5. Assert response is 404 and the body does NOT leak X's data.
    """
    # 1. Create X in tenant B.
    with schema_context("test_pytest_b"):
        x = MemberFactory(first_name="LeakedFirst", last_name="LeakedLast")
        x_pk = x.pk
        x_first_name = x.first_name
        # Sanity: the row IS visible from inside tenant B's schema.
        assert Member.objects.filter(pk=x_pk).exists()

    # 2. We're back in tenant A's schema (the `tenant` fixture). The same
    #    PK must NOT correspond to an existing row here (different schema,
    #    independent ID space).
    assert not Member.objects.filter(pk=x_pk).exists(), (
        "Setup invariant broken: tenant A already has a Member with the "
        "same pk as the one we just made in tenant B."
    )

    # 3. Tenant-A authenticated user.
    user_a = JasminUserFactory(roles=["office", "admin"])
    client = APIClient()
    client.force_authenticate(user=user_a)

    # 4. Detail request.
    detail_resp = client.get(f"/api/commissioning/members/{x_pk}/")
    assert detail_resp.status_code == 404, (
        f"CRITICAL: tenant-A request returned {detail_resp.status_code} for "
        f"a tenant-B member id; this is a tenant-isolation breach."
    )

    # 5. The body must NOT contain any of tenant B's data.
    body_text = detail_resp.content.decode("utf-8", errors="ignore")
    assert (
        x_first_name not in body_text
    ), "CRITICAL: tenant-A 404 body leaks tenant-B member data."


def test_tenant_a_list_does_not_include_tenant_b_members(tenant, _tenant_b_schema):
    """Tenant B member must not appear in tenant A's /members/ list."""
    with schema_context("test_pytest_b"):
        b_member = MemberFactory(first_name="BMemberFirst", last_name="BMemberLast")
        b_pk = b_member.pk

    # We're back on tenant A. Add an unrelated A-side member so the list
    # has at least one row (catches "list is empty for unrelated reasons").
    MemberFactory(first_name="AMemberFirst", last_name="AMemberLast")

    user_a = JasminUserFactory(roles=["office", "admin"])
    client = APIClient()
    client.force_authenticate(user=user_a)

    resp = client.get("/api/commissioning/members/")
    assert resp.status_code == 200, (
        f"Tenant-A list request unexpectedly returned {resp.status_code}: "
        f"{resp.content[:200]!r}"
    )
    body_text = resp.content.decode("utf-8", errors="ignore")
    assert (
        b_pk not in body_text
    ), f"CRITICAL: tenant-B member pk {b_pk} appears in tenant-A list."
    assert (
        "BMemberFirst" not in body_text
    ), "CRITICAL: tenant-B member name appears in tenant-A list."
