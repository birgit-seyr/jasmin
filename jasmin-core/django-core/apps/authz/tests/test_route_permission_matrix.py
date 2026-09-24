"""Per-viewset (route × verb × role) HTTP permission matrix.

The unit tests in ``test_permission_matrix.py`` prove the role *helper*
classes (``IsStaff``, ``IsOffice`` etc.) admit the right roles. This
file proves the *wiring* — that each viewset actually applies the
correct helper for each verb. A future refactor that drops
``RolePermissionsMixin`` from one viewset, or that flips
``read_permission`` / ``write_permission``, will surface here.

Each row in :data:`MATRIX` is::

    (path, method, role, expected_category)

where ``role`` is one of ``"anon"``, ``"member"``, ``"office"``, ``"staff"``
or ``"gardener"`` and the expected category is one of:

  - ``"ok"``    → 2xx (request passed permission + completed)
  - ``"deny"``  → 401 / 403 (rejected by auth or permission)
  - ``"4xx"``   → any non-deny client error (400/404/405) — used when
                  we want to assert "not denied" without setting up
                  valid request bodies for every endpoint

We use ``force_authenticate`` (not real JWT) because the JWT layer is
already covered by ``apps/shared/tenants/tests/test_viewset_isolation_matrix.py``.

Two cautions when adding rows:

``"4xx"`` is the weakest assertion here — a mistyped path 404s straight into
it, so a row meant to prove "this role is no longer denied" can pass while
testing nothing. Check the path resolves before trusting a green ``"4xx"``.

Rows for ``staff`` / ``gardener`` earn their keep. Neither role existed in this
matrix for a long time, and that blind spot is why read-only GET ``@action``
endpoints could sit behind ``write_permission`` — refusing exactly those two
roles on pages they are allowed to open — without any test noticing.
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
    # The empty body clears the permission layer and is then refused by the
    # create-path identity floor, so this lands in "4xx" like the other POSTs
    # the harness sends no valid body for. It still proves office is not denied.
    ("/api/commissioning/members/", "post", "office", "4xx"),
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
    # ------- Read-only GET @actions declared in ``read_actions`` -------
    # A custom @action takes ``write_permission`` unless the viewset names it
    # in ``read_actions``. These all sit on viewsets whose read gate is
    # IsStaff, behind pages already gated on isStaff, so staff and gardener
    # must reach them. "4xx" rather than "ok" because each requires query
    # params the harness does not send — the point is that they are NOT denied.
    ("/api/staff/weekly_plan/grid/", "get", "anon", "deny"),
    ("/api/staff/weekly_plan/grid/", "get", "staff", "4xx"),
    ("/api/staff/weekly_plan/grid/", "get", "gardener", "4xx"),
    ("/api/commissioning/packing_list/boxes_matrix/", "get", "staff", "4xx"),
    ("/api/commissioning/packing_list/boxes_matrix/", "get", "gardener", "4xx"),
    ("/api/commissioning/packing_list/member_amounts/", "get", "staff", "4xx"),
    ("/api/commissioning/share_delivery_details/matrix/", "get", "staff", "4xx"),
    ("/api/commissioning/shares/get_days/", "get", "staff", "ok"),
    ("/api/commissioning/shares/export_csv/", "get", "staff", "4xx"),
    ("/api/commissioning/default_share_contents/bulk_list/", "get", "staff", "4xx"),
    # "ok" rather than "4xx": this one needs no query params, so staff get a
    # real 200 — the strongest form of "the gate no longer refuses them".
    (
        "/api/commissioning/default_share_contents/subscriber_counts/",
        "get",
        "staff",
        "ok",
    ),
    # box_combination_matrix is the one whose viewset read gate is
    # IsStaffOrMember, so the mixin admits a member and the action's own
    # ``enforce_privileged`` is the only thing keeping the whole-tenant
    # tour/station x box matrix away from them. Pin both sides.
    (
        "/api/commissioning/share_delivery/box_combination_matrix/",
        "get",
        "staff",
        "4xx",
    ),
    (
        "/api/commissioning/share_delivery/box_combination_matrix/",
        "get",
        "member",
        "deny",
    ),
    # ------- GET @actions that are office-only ON PURPOSE -------
    # These stay on ``write_permission`` and must never be added to
    # ``read_actions``: their viewsets have member-inclusive read gates, so
    # routing them through ``read_permission`` would hand bulk personal data
    # to member-role callers. A blanket "GET is a read" refactor breaks these
    # rows rather than shipping the leak quietly.
    ("/api/commissioning/members/export_csv/", "get", "member", "deny"),
    ("/api/commissioning/members/export_csv/", "get", "staff", "deny"),
    # Detail route: permissions run in ``initial()`` before the handler calls
    # ``get_object()``, so the pk never resolves and the 403 lands first.
    ("/api/commissioning/members/does-not-exist/emails/", "get", "member", "deny"),
    ("/api/payments/billing_profiles/mandate_status/", "get", "member", "deny"),
    ("/api/payments/billing_profiles/mandate_status/", "get", "staff", "deny"),
    ("/api/payments/charge_schedules/income_by_month/", "get", "member", "deny"),
    ("/api/payments/charge_schedules/income_by_month/", "get", "staff", "deny"),
]


def _user_for_role(role: str):
    if role == "anon":
        return None
    if role == "member":
        return JasminUserFactory(roles=["member"])
    if role == "office":
        return JasminUserFactory(roles=["office", "admin"])
    if role == "staff":
        return JasminUserFactory(roles=["staff"])
    if role == "gardener":
        return JasminUserFactory(roles=["gardener"])
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
