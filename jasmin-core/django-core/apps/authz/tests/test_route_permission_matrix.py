"""Per-viewset (route × verb × role) HTTP permission matrix.

The unit tests in ``test_permission_matrix.py`` prove the role *helper*
classes (``IsStaff``, ``IsOffice`` etc.) admit the right roles. This
file proves the *wiring* — that each viewset actually applies the
correct helper for each verb. A future refactor that drops
``RolePermissionsMixin`` from one viewset, or that flips
``read_permission`` / ``write_permission``, will surface here.

Each row in :data:`MATRIX` is::

    (path, method, role, expected_category)

where ``role`` is one of ``"anon"``, ``"member"``, ``"office"`` and the
expected category is one of:

  - ``"ok"``    → 2xx (request passed permission + completed)
  - ``"deny"``  → 401 / 403 (rejected by auth or permission)
  - ``"4xx"``   → any non-deny client error (400/404/405) — used when
                  we want to assert "not denied" without setting up
                  valid request bodies for every endpoint

We use ``force_authenticate`` (not real JWT) because the JWT layer is
already covered by ``apps/shared/tenants/tests/test_viewset_isolation_matrix.py``.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.commissioning.tests.factories import JasminUserFactory

pytestmark = pytest.mark.django_db


def _category(status_code: int) -> str:
    if 200 <= status_code < 300:
        return "ok"
    if status_code in (401, 403):
        return "deny"
    return "4xx"


# (path, method, role, expected_category)
MATRIX: list[tuple[str, str, str, str]] = [
    # ------- Members (OfficeOrMember read; Office write via enforce_privileged) -------
    ("/api/commissioning/members/", "get", "anon", "deny"),
    # Members CAN list members — the queryset is row-scoped to their own
    # Member row by ``scope_to_member`` (see _build_member_queryset).
    ("/api/commissioning/members/", "get", "member", "ok"),
    ("/api/commissioning/members/", "get", "office", "ok"),
    # POST: IsOfficeOrMember lets the member pass the permission layer, but
    # ``enforce_privileged`` inside ``create()`` blocks non-office writers.
    ("/api/commissioning/members/", "post", "member", "deny"),
    # NB: MemberSerializer accepts an empty body (all fields default/blank),
    # so a permission-passed POST returns 201, not 4xx. Categorise as "ok":
    # the assertion still proves office is allowed to write.
    ("/api/commissioning/members/", "post", "office", "ok"),
    # ------- Subscriptions / Abos (StaffOrMember read, Office write) -------
    ("/api/commissioning/abos/", "get", "anon", "deny"),
    # Members CAN list abos — the queryset is row-scoped to their own
    # subscriptions by ``apps.authz.scoping`` (verified elsewhere).
    ("/api/commissioning/abos/", "get", "member", "ok"),
    ("/api/commissioning/abos/", "get", "office", "ok"),
    # ------- Billing profiles (StaffOrMember read, Office write) -------
    ("/api/payments/billing_profiles/", "get", "anon", "deny"),
    ("/api/payments/billing_profiles/", "get", "member", "ok"),
    ("/api/payments/billing_profiles/", "get", "office", "ok"),
    ("/api/payments/billing_profiles/", "post", "member", "deny"),
    ("/api/payments/billing_profiles/", "post", "office", "4xx"),
    # ------- Charge schedules (StaffOrMember read; ReadOnlyModelViewSet) -------
    ("/api/payments/charge_schedules/", "get", "anon", "deny"),
    ("/api/payments/charge_schedules/", "get", "member", "ok"),
    ("/api/payments/charge_schedules/", "get", "office", "ok"),
    # POST is method-not-allowed (405) — categorised as "4xx" because
    # the failure is not a permission denial.
    ("/api/payments/charge_schedules/", "post", "office", "4xx"),
    # ------- Billing runs (Staff read, Office write) -------
    ("/api/payments/billing_runs/", "get", "anon", "deny"),
    ("/api/payments/billing_runs/", "get", "member", "deny"),
    ("/api/payments/billing_runs/", "get", "office", "ok"),
    ("/api/payments/billing_runs/", "post", "member", "deny"),
    ("/api/payments/billing_runs/", "post", "office", "4xx"),
    # ------- Notification email templates (Staff read+write) -------
    ("/api/notifications/email-templates/", "get", "anon", "deny"),
    ("/api/notifications/email-templates/", "get", "member", "deny"),
    ("/api/notifications/email-templates/", "get", "office", "ok"),
]


def _user_for_role(role: str):
    if role == "anon":
        return None
    if role == "member":
        return JasminUserFactory(roles=["member"])
    if role == "office":
        return JasminUserFactory(roles=["office", "admin"])
    raise ValueError(f"unknown role: {role}")


@pytest.mark.parametrize("path,method,role,expected", MATRIX)
def test_route_permission_matrix(tenant, path, method, role, expected):
    user = _user_for_role(role)
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)

    if method == "get":
        resp = client.get(path)
    elif method == "post":
        resp = client.post(path, data={}, format="json")
    else:
        raise ValueError(f"unsupported method: {method}")

    actual = _category(resp.status_code)
    assert actual == expected, (
        f"{method.upper()} {path} as {role!r}: got HTTP {resp.status_code} "
        f"({actual!r}), expected category {expected!r}. "
        f"Body head: {resp.content[:200]!r}"
    )
