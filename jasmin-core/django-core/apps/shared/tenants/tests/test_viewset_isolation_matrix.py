"""Cross-tenant viewset isolation matrix.

The JWT-layer guard (``TenantBoundJWTAuthentication``) is unit-tested in
``apps/authz/tests/test_authentication.py``. This file proves the same
guard fires through real HTTP routing for a representative slice of
tenant-scoped endpoints — so a future refactor of authentication wiring
can't silently disable it on one viewset.

Setup: we mint an access token with a ``tenant_id`` claim that does NOT
match the schema the request will resolve to. Every endpoint must
respond non-2xx (the JWT layer raises ``InvalidToken`` -> 401).

Note: we don't include a "matching-tenant" sanity check here because
APIClient requests pass through ``TenantMainMiddleware``, which resolves
the tenant from ``HTTP_HOST`` (defaults to ``testserver`` in the test
client → public schema), not from the test fixture's schema switch. The
happy-path matching case is covered by ``test_integration_http.py`` and
the per-app integration suites that use ``force_authenticate``.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.commissioning.tests.factories import JasminUserFactory

pytestmark = pytest.mark.django_db


# Representative tenant-scoped endpoints from each major app. Each must
# return non-2xx when the JWT carries a foreign or missing ``tenant_id``.
# URLs verified against the actual routers — note underscores on payments
# and the ``email-templates/`` path on notifications.
PROTECTED_ENDPOINTS = [
    "/api/commissioning/members/",
    "/api/commissioning/abos/",
    "/api/payments/billing_profiles/",
    "/api/payments/charge_schedules/",
    "/api/payments/billing_runs/",
    "/api/notifications/email-templates/",
]


def _mint(user, *, tenant_id: str) -> str:
    token = AccessToken.for_user(user)
    token["tenant_id"] = tenant_id
    return str(token)


@pytest.mark.parametrize("url", PROTECTED_ENDPOINTS)
def test_foreign_tenant_token_is_rejected(tenant, url):
    """Token claims tenant_id='some_other_tenant' — must NEVER return 200."""
    user = JasminUserFactory(roles=["office", "admin"])
    foreign_token = _mint(user, tenant_id="some_other_tenant")

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {foreign_token}")
    resp = client.get(url)

    assert resp.status_code in (401, 403), (
        f"{url} returned {resp.status_code} for a cross-tenant token; "
        f"this is a tenant-isolation bug."
    )


@pytest.mark.parametrize("url", PROTECTED_ENDPOINTS)
def test_token_without_tenant_claim_is_rejected(tenant, url):
    """SimpleJWT default tokens have NO tenant_id. They must also be
    rejected — defense in depth against a downgrade attack."""
    user = JasminUserFactory(roles=["office", "admin"])
    bare_token = str(AccessToken.for_user(user))  # no tenant_id

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {bare_token}")
    resp = client.get(url)

    assert resp.status_code in (
        401,
        403,
    ), f"{url} returned {resp.status_code} for a token without tenant_id."
