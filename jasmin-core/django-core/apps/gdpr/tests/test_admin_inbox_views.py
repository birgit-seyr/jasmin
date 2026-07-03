"""Tests for the admin-inbox + user-status endpoints added in the
2026-06 GDPR pass:

  - ``GET /api/gdpr/admin/pending-deletions/`` — admin's PENDING_ADMIN
    inbox with per-row ``blockers``.
  - ``GET /api/gdpr/admin/decided-deletions/`` — paginated history of
    REJECTED / EXECUTED / CANCELLED / EXPIRED requests with the
    ``decided_at`` field derived per-state.
  - ``GET /api/gdpr/my-deletion-status/`` — current user's latest
    request (or null shape if they've never lodged one).

The two admin endpoints are ``IsAdmin``-gated; the
``my-deletion-status`` is ``IsAuthenticated``.
"""

from __future__ import annotations

import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.commissioning.tests.factories import (
    CoopShareFactory,
    JasminUserFactory,
    MemberFactory,
)
from apps.gdpr.models import (
    DeletionLog,
    DeletionRequest,
    DeletionRequestState,
)
from apps.gdpr.services import GDPRService


# Fresh admin client per test (factory-built admin). Authentication is
# via ``force_authenticate`` because these endpoints don't depend on
# the JWT lifecycle — only on the role.
def _admin_client() -> tuple[APIClient, object]:
    admin = JasminUserFactory(roles=["admin"])
    client = APIClient()
    client.force_authenticate(user=admin)
    return client, admin


def _land_in_pending_admin(user) -> DeletionRequest:
    """Lift a request through the lodge → email-confirm flow so it
    lands in PENDING_ADMIN — the state the admin inbox cares about."""
    req = GDPRService.request_deletion(user)
    return GDPRService.confirm_deletion_token(str(req.token))


# ---------------------------------------------------------------------------
# Admin: pending-deletions inbox
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAdminPendingDeletionsView:
    URL = reverse("gdpr-admin-pending-deletions")

    def test_returns_only_pending_admin_rows(self, tenant):
        """Inbox is "what needs my attention now" — terminal states
        belong in the history endpoint, not here."""
        pending_user = JasminUserFactory(roles=["member"], email="p@example.com")
        _land_in_pending_admin(pending_user)

        # Another user, fully executed already — must NOT appear.
        executed_user = JasminUserFactory(roles=["member"], email="e@example.com")
        req = _land_in_pending_admin(executed_user)
        admin = JasminUserFactory(roles=["admin"])
        GDPRService.admin_approve_deletion(req, admin_user=admin)

        client, _ = _admin_client()
        resp = client.get(self.URL)

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body.get("pending"), list)
        emails = {row["requested_email"] for row in body["pending"]}
        assert emails == {"p@example.com"}

    def test_row_shape_carries_blockers_and_dual_emails(self, tenant):
        """Each row exposes the full shape the frontend depends on:
        ``id``, ``requested_email`` (captured), ``current_user_email``
        (live), ``requested_at``, ``email_confirmed_at``, ``blockers``."""
        user = JasminUserFactory(roles=["member"], email="captured@example.com")
        req = _land_in_pending_admin(user)
        # User changes their email after lodging — captured ≠ live.
        user.email = "now-different@example.com"
        user.save(update_fields=["email"])

        client, _ = _admin_client()
        resp = client.get(self.URL)
        rows = resp.json()["pending"]

        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == req.id
        assert row["requested_email"] == "captured@example.com"
        assert row["current_user_email"] == "now-different@example.com"
        assert row["requested_at"] is not None
        assert row["email_confirmed_at"] is not None
        assert row["blockers"] == []

    def test_blockers_list_populated_from_retention_check(self, tenant):
        """The frontend uses ``blockers`` to disable the Approve
        button when the row can't be executed right now. Each blocker
        string comes from ``check_retention_blocks`` — verify open
        CoopShares produce a non-empty list."""
        user = JasminUserFactory(roles=["member"])
        member = MemberFactory(user=user)
        CoopShareFactory(member=member)
        CoopShareFactory(member=member)
        _land_in_pending_admin(user)

        client, _ = _admin_client()
        resp = client.get(self.URL)
        rows = resp.json()["pending"]

        assert len(rows) == 1
        assert len(rows[0]["blockers"]) == 1
        assert "2 open CoopShare(s)" in rows[0]["blockers"][0]

    def test_forbidden_for_non_admin(self, tenant):
        user = JasminUserFactory(roles=["member"])
        _land_in_pending_admin(user)

        non_admin = JasminUserFactory(roles=["office"])
        client = APIClient()
        client.force_authenticate(user=non_admin)
        resp = client.get(self.URL)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Admin: decided-deletions history
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAdminDecidedDeletionsView:
    URL = reverse("gdpr-admin-decided-deletions")

    def test_filters_to_terminal_states_only(self, tenant):
        """History is "decisions made"; an in-flight PENDING_ADMIN row
        does NOT belong here. Mirror of the pending-inbox filter."""
        # One executed, one rejected, one expired, one cancelled, one
        # still PENDING_ADMIN (must be excluded).
        for label in ("executed", "rejected", "expired", "cancelled", "pending"):
            user = JasminUserFactory(roles=["member"], email=f"{label}@example.com")
            req = _land_in_pending_admin(user)
            admin = JasminUserFactory(roles=["admin"])
            if label == "executed":
                GDPRService.admin_approve_deletion(req, admin_user=admin)
            elif label == "rejected":
                GDPRService.admin_reject_deletion(req, admin_user=admin, reason="nope")
            elif label == "expired":
                req.state = DeletionRequestState.EXPIRED
                req.save(update_fields=["state"])
            elif label == "cancelled":
                req.state = DeletionRequestState.CANCELLED
                req.save(update_fields=["state"])
            # pending: leave as-is

        client, _ = _admin_client()
        resp = client.get(self.URL)

        assert resp.status_code == 200
        body = resp.json()
        # Without ``?limit=``, the endpoint returns a plain array
        # (see ``OptionalLimitOffsetPagination`` opt-in semantics).
        assert isinstance(body, list)
        states = {row["state"] for row in body}
        assert states == {"executed", "rejected", "expired", "cancelled"}

    def test_decided_at_derived_per_state(self, tenant):
        """``decided_at`` is the most-relevant timestamp per state:
        executed → ``executed_at`` (or ``admin_confirmed_at`` fallback);
        rejected → ``admin_confirmed_at``; cancelled/expired → None
        (those paths never went through admin review)."""
        admin = JasminUserFactory(roles=["admin"])

        # Executed
        exec_req = _land_in_pending_admin(
            JasminUserFactory(roles=["member"], email="exec@example.com")
        )
        exec_req = GDPRService.admin_approve_deletion(exec_req, admin_user=admin)

        # Rejected
        rej_req = _land_in_pending_admin(
            JasminUserFactory(roles=["member"], email="rej@example.com")
        )
        rej_req = GDPRService.admin_reject_deletion(
            rej_req, admin_user=admin, reason="no"
        )

        # Cancelled (never reviewed by admin)
        cancel_req = _land_in_pending_admin(
            JasminUserFactory(roles=["member"], email="can@example.com")
        )
        cancel_req.state = DeletionRequestState.CANCELLED
        cancel_req.save(update_fields=["state"])

        client, _ = _admin_client()
        rows = client.get(self.URL).json()
        by_email = {r["requested_email"]: r for r in rows}

        assert by_email["exec@example.com"]["decided_at"] is not None
        assert by_email["rej@example.com"]["decided_at"] is not None
        assert by_email["can@example.com"]["decided_at"] is None

        # Rejection reason flows through; non-rejected rows are null.
        assert by_email["rej@example.com"]["rejection_reason"] == "no"
        assert by_email["exec@example.com"]["rejection_reason"] is None
        assert by_email["can@example.com"]["rejection_reason"] is None

    def test_paginates_when_limit_param_passed(self, tenant):
        """``OptionalLimitOffsetPagination`` opt-in: pass ``?limit=`` →
        get the ``{count, results}`` envelope back. Frontend always
        passes the limit; this contract is what powers the history
        table's page-by-page rendering."""
        admin = JasminUserFactory(roles=["admin"])
        for i in range(5):
            req = _land_in_pending_admin(
                JasminUserFactory(roles=["member"], email=f"u{i}@example.com")
            )
            GDPRService.admin_reject_deletion(req, admin_user=admin, reason="n")

        client, _ = _admin_client()
        body = client.get(self.URL + "?limit=2&offset=0").json()

        assert body["count"] == 5
        assert len(body["results"]) == 2
        # Page 2 picks up where page 1 left off.
        body2 = client.get(self.URL + "?limit=2&offset=2").json()
        assert len(body2["results"]) == 2
        page1_ids = {r["id"] for r in body["results"]}
        page2_ids = {r["id"] for r in body2["results"]}
        assert page1_ids.isdisjoint(page2_ids)

    def test_forbidden_for_non_admin(self, tenant):
        non_admin = JasminUserFactory(roles=["office"])
        client = APIClient()
        client.force_authenticate(user=non_admin)
        resp = client.get(self.URL)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# User: my-deletion-status
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMyDeletionStatusView:
    URL = reverse("gdpr-my-deletion-status")

    def test_returns_null_shape_when_no_request_ever_lodged(self, tenant):
        """Frontend probes this on every "Meine Daten" load. If the
        user has no request, all fields are null (NOT 404) so the
        frontend can render the "Request Deletion" button without
        special-casing the missing-row path."""
        user = JasminUserFactory(roles=["member"])
        client = APIClient()
        client.force_authenticate(user=user)

        resp = client.get(self.URL)

        assert resp.status_code == 200
        assert resp.json() == {
            "state": None,
            "requested_at": None,
            "admin_confirmed_at": None,
            "admin_rejection_reason": None,
        }

    def test_returns_most_recent_request(self, tenant):
        """A user can have multiple historical requests (re-request
        after the first one was cancelled). The endpoint surfaces the
        latest one — that's what the user wants to know about."""
        user = JasminUserFactory(roles=["member"])

        # First request — backdated so it's clearly older.
        first = GDPRService.request_deletion(user)
        first.requested_at = timezone.now() - datetime.timedelta(days=10)
        first.state = DeletionRequestState.CANCELLED
        first.save(update_fields=["requested_at", "state"])

        # Second, "now".
        GDPRService.request_deletion(user)

        client = APIClient()
        client.force_authenticate(user=user)
        body = client.get(self.URL).json()

        # The new request is PENDING_EMAIL.
        assert body["state"] == "pending_email"

    def test_includes_rejection_reason_when_last_request_rejected(self, tenant):
        """Critical user-facing field: when the last request was
        rejected, the frontend shows the office's reason in a warning
        banner above the Request-Deletion button so the user
        understands why."""
        user = JasminUserFactory(roles=["member"])
        admin = JasminUserFactory(roles=["admin"])
        req = _land_in_pending_admin(user)
        GDPRService.admin_reject_deletion(
            req, admin_user=admin, reason="Bitte erst CoopShares kündigen."
        )

        client = APIClient()
        client.force_authenticate(user=user)
        body = client.get(self.URL).json()

        assert body["state"] == "rejected"
        assert body["admin_rejection_reason"] == "Bitte erst CoopShares kündigen."
        assert body["admin_confirmed_at"] is not None

    def test_requires_authentication(self, tenant):
        client = APIClient()
        resp = client.get(self.URL)
        assert resp.status_code in (401, 403)


# ``DeletionLog`` import is unused above but kept so a future
# "deletion-log endpoint" test added in this file can grab it without
# updating the import block. Remove on next major test pass if no
# such test materialises.
_ = DeletionLog
