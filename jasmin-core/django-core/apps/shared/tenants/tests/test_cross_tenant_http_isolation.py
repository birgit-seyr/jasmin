"""End-to-end multi-tenant HTTP isolation.

This complements ``test_viewset_isolation_matrix.py`` (JWT layer) and
``test_schema_isolation.py`` (ORM layer) by covering the full HTTP path:

  - Create object X in tenant B's schema.
  - Prove X really is reachable over HTTP on tenant B's host.
  - Issue the same request to tenant A's host as a tenant-A user.
  - Assert X is invisible there: 404 on the detail endpoint, absent from list.

If this ever returns 200 with X's data, a tenant has leaked into another
tenant's responses — the most severe security failure the platform can
have. Lock this down hard.

Why every request names its host
--------------------------------
``TenantMainMiddleware`` resolves the schema from the request's ``Host``
header, and *every* way of getting that wrong also produces a 404: an
unknown host, a host owned by a third tenant, a mistyped URL. A test that
only asserts "404" therefore passes whether isolation holds or the request
never reached the intended tenant at all. Two guards close that gap:

  - each request addresses its tenant by name (``tenant_host`` /
    ``tenant_b_host``) and asserts the resolved schema via
    ``_assert_resolved_to``;
  - each isolation assertion is paired with a positive control — the row IS
    served on its own tenant's host, and tenant A's own row IS in tenant A's
    list — so a 404/empty body can never be mistaken for isolation.
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
from apps.shared.tenants.tests.conftest import TENANT_HOST

pytestmark = pytest.mark.django_db

MEMBER_LIST_URL = "/api/commissioning/members/"

TENANT_B_SCHEMA = "test_pytest_b"
# The only hostname that resolves to tenant B. Distinct from every other
# test tenant's host so a request can never land in the wrong schema.
TENANT_B_HOST = "pytest-b.localhost"


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
        t = Tenant.objects.filter(schema_name=TENANT_B_SCHEMA).first()
        if t is None:
            t = Tenant(schema_name=TENANT_B_SCHEMA, name="Test Farm B")
            t.save()
        else:
            call_command(
                "migrate_schemas",
                schema_name=TENANT_B_SCHEMA,
                interactive=False,
                verbosity=0,
            )
        Domain.objects.update_or_create(
            domain=TENANT_B_HOST, defaults={"tenant": t, "is_primary": True}
        )
        connection.set_schema_to_public()
    yield t
    with django_db_blocker.unblock():
        try:
            t.delete()
        except Exception:
            pass


@pytest.fixture()
def tenant_b_host(_tenant_b_schema) -> str:
    """Hostname a routed request must use to land in tenant B's schema."""
    domain = (
        Domain.objects.filter(domain=TENANT_B_HOST).select_related("tenant").first()
    )
    assert domain is not None, (
        f"No Domain row for {TENANT_B_HOST!r}; a routed request would 404 in "
        f"TenantMainMiddleware instead of reaching {TENANT_B_SCHEMA!r}."
    )
    assert domain.tenant.schema_name == TENANT_B_SCHEMA, (
        f"{TENANT_B_HOST!r} resolves to schema {domain.tenant.schema_name!r}, "
        f"not {TENANT_B_SCHEMA!r}."
    )
    return TENANT_B_HOST


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# We use ``force_authenticate`` rather than minting a real JWT here. The
# JWT-binding layer is already covered by
# ``test_viewset_isolation_matrix.py``; this file exercises the *queryset*
# isolation path — does the ORM, scoped to schema A, ever return a row
# that lives in schema B?


def _get(host: str, user, url: str):
    """GET ``url`` on ``host`` as ``user``, leaving the test's schema intact.

    ``TenantMainMiddleware`` switches the connection to the schema it resolves
    and never switches back, so without the restore the next ORM statement in
    the test would run in the schema of the last request rather than the one
    its fixture selected.
    """
    previous = connection.tenant
    client = APIClient(HTTP_HOST=host)
    client.force_authenticate(user=user)
    try:
        return client.get(url)
    finally:
        connection.set_tenant(previous)


def _assert_resolved_to(response, expected_schema: str, host: str) -> None:
    """Fail unless the request actually ran in ``expected_schema``.

    Without this the isolation assertions below are satisfied by any request
    that never reached the intended tenant.
    """
    resolved = getattr(
        getattr(response.wsgi_request, "tenant", None), "schema_name", None
    )
    assert resolved == expected_schema, (
        f"Host {host!r} resolved to schema {resolved!r}, expected "
        f"{expected_schema!r} — this test proves nothing until the request "
        f"reaches the tenant it names."
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_tenant_a_cannot_retrieve_tenant_b_member_via_http(
    tenant, tenant_host, _tenant_b_schema, tenant_b_host
):
    """Object exists in tenant B; the same URL on tenant A must 404, not 200.

    Steps:
      1. Switch to tenant B's schema, create a Member X and a B-side user.
      2. GET X's detail URL on tenant B's host — must be 200 (the positive
         control: the row, the route and the permissions all work).
      3. GET the very same URL on tenant A's host as a tenant-A user — must
         be 404, with none of X's data in the body.
    """
    # 1. Create X in tenant B.
    with schema_context(TENANT_B_SCHEMA):
        x = MemberFactory(first_name="LeakedFirst", last_name="LeakedLast")
        x_pk = x.pk
        x_first_name = x.first_name
        user_b = JasminUserFactory(roles=["office", "admin"])
        # Sanity: the row IS visible from inside tenant B's schema.
        assert Member.objects.filter(pk=x_pk).exists()

    detail_url = f"{MEMBER_LIST_URL}{x_pk}/"

    # 2. Positive control on tenant B's own host.
    b_resp = _get(tenant_b_host, user_b, detail_url)
    _assert_resolved_to(b_resp, TENANT_B_SCHEMA, tenant_b_host)
    assert b_resp.status_code == 200, (
        f"Tenant-B member is not reachable on tenant B's own host "
        f"({b_resp.status_code}) — the cross-tenant 404 below would be "
        f"meaningless."
    )
    assert x_first_name in b_resp.content.decode("utf-8", errors="ignore")

    # 3. We're back in tenant A's schema (the `tenant` fixture). The same
    #    PK must NOT correspond to an existing row here (different schema,
    #    independent ID space).
    assert not Member.objects.filter(pk=x_pk).exists(), (
        "Setup invariant broken: tenant A already has a Member with the "
        "same pk as the one we just made in tenant B."
    )

    user_a = JasminUserFactory(roles=["office", "admin"])
    a_resp = _get(tenant_host, user_a, detail_url)
    _assert_resolved_to(a_resp, tenant.schema_name, tenant_host)
    assert a_resp.status_code == 404, (
        f"CRITICAL: tenant-A request returned {a_resp.status_code} for "
        f"a tenant-B member id; this is a tenant-isolation breach."
    )
    assert x_first_name not in a_resp.content.decode(
        "utf-8", errors="ignore"
    ), "CRITICAL: tenant-A 404 body leaks tenant-B member data."


def test_tenant_a_list_does_not_include_tenant_b_members(
    tenant, tenant_host, _tenant_b_schema, tenant_b_host
):
    """Tenant B member must not appear in tenant A's /members/ list."""
    with schema_context(TENANT_B_SCHEMA):
        b_member = MemberFactory(first_name="BMemberFirst", last_name="BMemberLast")
        b_pk = b_member.pk
        user_b = JasminUserFactory(roles=["office", "admin"])

    # Positive control: B's member IS listed on B's own host, so its absence
    # from A's list below is isolation rather than an empty/failed response.
    b_resp = _get(tenant_b_host, user_b, MEMBER_LIST_URL)
    _assert_resolved_to(b_resp, TENANT_B_SCHEMA, tenant_b_host)
    assert b_resp.status_code == 200
    assert b_pk in b_resp.content.decode("utf-8", errors="ignore")

    # We're back on tenant A. Add an A-side member: it must be present in A's
    # list, which proves the list really is tenant A's and not an empty body.
    a_member = MemberFactory(first_name="AMemberFirst", last_name="AMemberLast")

    user_a = JasminUserFactory(roles=["office", "admin"])
    resp = _get(tenant_host, user_a, MEMBER_LIST_URL)
    _assert_resolved_to(resp, tenant.schema_name, tenant_host)
    assert resp.status_code == 200, (
        f"Tenant-A list request unexpectedly returned {resp.status_code}: "
        f"{resp.content[:200]!r}"
    )
    body_text = resp.content.decode("utf-8", errors="ignore")
    assert (
        a_member.pk in body_text
    ), "Tenant-A list is missing tenant A's own member; the test proves nothing."
    assert (
        b_pk not in body_text
    ), f"CRITICAL: tenant-B member pk {b_pk} appears in tenant-A list."
    assert (
        "BMemberFirst" not in body_text
    ), "CRITICAL: tenant-B member name appears in tenant-A list."


# Hostname -> the schema that owns it. Every routed test in the suite depends on
# this mapping, because ``TenantMainMiddleware`` resolves the schema from the
# Host header alone. A host absent from the run is skipped (its package's
# conftest never loaded); a present row naming the wrong schema is the failure.
TEST_HOST_OWNERS = {
    # apps/commissioning/tests/conftest.py. ``testserver`` is Django's default
    # test-client hostname, so a bare APIClient() lands wherever it points.
    "testserver": "test_pytest",
    "pytest.localhost": "test_pytest",
    TENANT_HOST: "test_tenants",  # apps/shared/tenants/tests/conftest.py
    TENANT_B_HOST: TENANT_B_SCHEMA,  # this file
}


def test_no_test_host_resolves_to_another_tenants_schema(
    tenant, tenant_host, tenant_b_host
):
    """Every seeded test hostname must resolve to the tenant that owns it.

    ``Domain.domain`` is unique, so one hostname seeded by two conftests behind
    an "if not exists" guard belongs to whichever ran first, and the loser's
    routed tests then read the winner's schema without saying so. This reads
    every ``Domain`` row rather than only the two hosts this file uses: the pair
    that collides is rarely the pair the failing test names — ``testserver`` is
    the one that has actually collided, and no test addresses it by name.
    """
    rows = [
        (domain.domain, domain.tenant.schema_name)
        for domain in Domain.objects.select_related("tenant")
    ]
    hostnames = [host for host, _ in rows]
    assert len(hostnames) == len(
        set(hostnames)
    ), f"One hostname with two Domain rows: {sorted(hostnames)}"

    owners = dict(rows)
    for host in (tenant_host, tenant_b_host):
        assert host in owners, f"No Domain row for {host!r}; rows: {owners}"

    misrouted = {
        host: owners[host]
        for host, schema in TEST_HOST_OWNERS.items()
        if host in owners and owners[host] != schema
    }
    expected = {host: TEST_HOST_OWNERS[host] for host in misrouted}
    assert not misrouted, (
        f"Test hostname(s) resolve to the wrong schema: {misrouted}, expected "
        f"{expected}. Routed tests addressing those hosts read another tenant's "
        f"data while still passing."
    )
