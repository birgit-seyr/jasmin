"""Tests for the two-step deletion flow.

Two-step (optionally three-step) deletion flow:

  1. ``GDPRService.request_deletion(user)`` → ``PENDING_EMAIL``
  2. user clicks emailed link → ``confirm_deletion_token(token)``
     → either executes immediately (no admin gate) OR transitions to
     ``PENDING_ADMIN``
  3. (optional) admin calls ``admin_approve_deletion`` /
     ``admin_reject_deletion`` — which use the
     ``AdminConfirmableMixin``'s ``confirm()`` / ``reject()`` methods
     under the hood (one-way reuse of the commissioning mixin per
     CLAUDE.md).

Admin approval is mandatory for every deletion — no per-tenant
opt-out. Every confirmed request lands in ``PENDING_ADMIN``.

The email send is NOT exercised end-to-end — the existing fixture
stack has no SMTP backend wired. ``send_deletion_confirmation_email``
is a best-effort helper that swallows failures, so tests poke
``GDPRService.request_deletion`` directly.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest import mock

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.commissioning.tests.factories import (
    CoopShareFactory,
    JasminUserFactory,
    MemberFactory,
)
from apps.gdpr.errors import (
    DeletionRequestNotPending,
    DeletionTokenExpired,
    DeletionTokenInvalid,
    RetentionPeriodActive,
)
from apps.gdpr.models import (
    DELETION_TOKEN_TTL,
    DeletionRequest,
    DeletionRequestState,
)
from apps.gdpr.services import GDPRService

# ---------------------------------------------------------------------------
# Service layer — request_deletion
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRequestDeletion:
    def test_member_without_gate_disabled_inherits_default_admin_gate(self, tenant):
        """Default tenant setting is ON, so a fresh request stamps
        ``requires_admin_approval=True`` even for a regular member."""
        user = JasminUserFactory(
            roles=["member"], email="alice@example.com", first_name="Alice"
        )

        deletion_request = GDPRService.request_deletion(user)

        assert deletion_request.state == DeletionRequestState.PENDING_EMAIL
        assert deletion_request.user_id == user.pk
        assert deletion_request.requested_email == "alice@example.com"
        assert deletion_request.requires_admin_approval is True
        assert deletion_request.token is not None
        # Token TTL is ~24h; allow a few seconds of clock slack.
        expected_expiry = timezone.now() + DELETION_TOKEN_TTL
        assert (
            abs((deletion_request.token_expires_at - expected_expiry).total_seconds())
            < 10
        )

        # User row is NOT mutated by the request step.
        user.refresh_from_db()
        assert user.email == "alice@example.com"
        assert user.first_name == "Alice"

    def test_open_retention_does_not_block_request(self, tenant):
        """Retention obligations don't refuse the request — they
        defer its execution. The lodge step succeeds; the admin sees
        the blockers in the inbox and resolves them before approving.
        Matches GDPR Art. 17(3): right not suspended, only execution
        deferred."""
        user = JasminUserFactory(roles=["member"])
        member = MemberFactory(user=user)
        CoopShareFactory(member=member)

        deletion_request = GDPRService.request_deletion(user)

        # Request landed (in PENDING_EMAIL, awaiting the user's click).
        assert deletion_request.state == DeletionRequestState.PENDING_EMAIL
        assert DeletionRequest.objects.filter(user=user).exists()

    def test_re_request_supersedes_previous_open(self, tenant):
        """If the user requests deletion twice, the older PENDING row
        is flipped to CANCELLED and a fresh request is returned. Only
        one live request per user at any time."""
        user = JasminUserFactory(roles=["member"])

        first = GDPRService.request_deletion(user)
        second = GDPRService.request_deletion(user)

        first.refresh_from_db()
        assert first.state == DeletionRequestState.CANCELLED
        assert second.state == DeletionRequestState.PENDING_EMAIL
        assert second.token != first.token
        # The supersede transition is stamped so the Art. 17 paper trail
        # records WHEN the old row was retired, not just a bare state flip.
        assert first.superseded_at is not None
        # The live successor is not marked superseded.
        assert second.superseded_at is None


# ---------------------------------------------------------------------------
# Service layer — confirm_deletion_token
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestConfirmDeletionToken:
    def test_happy_path_with_admin_gate_waits_for_office(self, tenant):
        """Default policy = admin gate on. Confirming the email
        moves the request to PENDING_ADMIN — the user data is NOT
        anonymized yet."""
        user = JasminUserFactory(roles=["member"], email="alice@example.com")
        deletion_request = GDPRService.request_deletion(user)

        result = GDPRService.confirm_deletion_token(
            str(deletion_request.token), ip="10.0.0.1"
        )

        assert result.state == DeletionRequestState.PENDING_ADMIN
        assert result.executed_at is None
        assert result.email_confirmed_at is not None

        user.refresh_from_db()
        # Untouched — admin still has to approve.
        assert user.email == "alice@example.com"

    def test_unknown_token_raises_invalid(self, tenant):
        with pytest.raises(DeletionTokenInvalid):
            GDPRService.confirm_deletion_token(str(uuid.uuid4()))

    def test_malformed_token_raises_invalid(self, tenant):
        """Non-UUID input should hit the same 404 path, not crash
        on a ValueError from the UUID parser."""
        with pytest.raises(DeletionTokenInvalid):
            GDPRService.confirm_deletion_token("not-a-uuid")

    def test_already_consumed_token_raises_invalid(self, tenant):
        """Re-confirming an already-confirmed request must fail —
        first confirm moves the row out of PENDING_EMAIL so the
        second call's state check rejects."""
        user = JasminUserFactory(roles=["member"])
        deletion_request = GDPRService.request_deletion(user)
        GDPRService.confirm_deletion_token(str(deletion_request.token))

        with pytest.raises(DeletionTokenInvalid):
            GDPRService.confirm_deletion_token(str(deletion_request.token))

    def test_expired_token_marks_request_expired_and_raises(self, tenant):
        """A token past its 24h window flips the row to EXPIRED so
        the audit trail captures the lapse, and refuses the confirm."""
        user = JasminUserFactory(roles=["member"])
        deletion_request = GDPRService.request_deletion(user)
        # Backdate the expiry — much simpler than time-machining the test.
        deletion_request.token_expires_at = timezone.now() - timedelta(minutes=1)
        deletion_request.save(update_fields=["token_expires_at"])

        with pytest.raises(DeletionTokenExpired):
            GDPRService.confirm_deletion_token(str(deletion_request.token))

        deletion_request.refresh_from_db()
        assert deletion_request.state == DeletionRequestState.EXPIRED

    def test_late_retention_re_check_refuses_if_user_gained_obligation(self, tenant):
        """Between request and admin-approve the member could have
        signed a new CoopShare. The execute path re-checks at
        admin_approve time, so we never violate Art. 17(3)(b) due to
        a stale pre-flight.

        We use ``amount_of_coop_shares=3`` because the default
        TenantSettings ``min_number_coop_shares=3`` invariant is
        checked per-row at ``CoopShare.save()``; the retention
        check itself counts open rows, so one row is enough to
        trigger the block.
        """
        user = JasminUserFactory(roles=["member"])
        member = MemberFactory(user=user)
        deletion_request = GDPRService.request_deletion(user)
        # Land the request in PENDING_ADMIN (the only path now that
        # admin approval is mandatory).
        GDPRService.confirm_deletion_token(str(deletion_request.token))
        # Simulate the user acquiring an obligation between confirm
        # and admin review.
        CoopShareFactory(member=member, amount_of_coop_shares=3)

        with pytest.raises(RetentionPeriodActive):
            GDPRService.admin_approve_deletion(
                deletion_request, admin_user=JasminUserFactory(roles=["office"])
            )

        # Inside-transaction state changes roll back when
        # ``_execute_deletion`` raises — request stays in
        # PENDING_ADMIN so the office can retry once the obligation
        # is settled.
        deletion_request.refresh_from_db()
        assert deletion_request.state == DeletionRequestState.PENDING_ADMIN
        user.refresh_from_db()
        assert user.is_active


# ---------------------------------------------------------------------------
# Service layer — admin_approve_deletion / admin_reject_deletion
# (Uses the AdminConfirmableMixin under the hood.)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAdminApproveDeletion:
    def test_happy_path_executes_anonymization(self, tenant):
        """Approve → mixin stamps admin_confirmed/_by/_at, state
        moves to EXECUTED, user is anonymized."""
        user = JasminUserFactory(roles=["member"], email="alice@example.com")
        admin = JasminUserFactory(roles=["admin"], email="admin@example.com")
        deletion_request = GDPRService.request_deletion(user)
        GDPRService.confirm_deletion_token(str(deletion_request.token))
        deletion_request.refresh_from_db()
        assert deletion_request.state == DeletionRequestState.PENDING_ADMIN

        result = GDPRService.admin_approve_deletion(deletion_request, admin_user=admin)

        assert result.state == DeletionRequestState.EXECUTED
        # AdminConfirmableMixin fields are stamped by ``.confirm()``.
        assert result.admin_confirmed is True
        assert result.admin_confirmed_by_id == admin.pk
        assert result.admin_confirmed_at is not None
        assert result.executed_at is not None
        assert result.deletion_log_id is not None

        user.refresh_from_db()
        assert user.email == f"deleted_{user.pk}@deleted.invalid"

    def test_approve_rejects_when_not_pending_admin(self, tenant):
        """Approving a PENDING_EMAIL (or already-executed) request
        must error rather than silently advance the state."""
        user = JasminUserFactory(roles=["member"])
        admin = JasminUserFactory(roles=["admin"])
        deletion_request = GDPRService.request_deletion(user)
        # Still PENDING_EMAIL — not PENDING_ADMIN.

        with pytest.raises(DeletionRequestNotPending):
            GDPRService.admin_approve_deletion(deletion_request, admin_user=admin)

    def test_concurrent_double_approve_serialises_on_select_for_update(self, tenant):
        """Two admins clicking Approve on the same request must NOT
        both run anonymisation. The service re-fetches under
        ``select_for_update`` before its state check, so the second
        caller — holding a Python reference whose ``state`` attribute
        still says PENDING_ADMIN — sees the post-execute DB state and
        raises ``DeletionRequestNotPending``. Regression test for the
        race lock added in the 2026-06 audit.
        """
        user = JasminUserFactory(roles=["member"], email="alice@example.com")
        admin_a = JasminUserFactory(roles=["admin"])
        admin_b = JasminUserFactory(roles=["admin"])
        deletion_request = GDPRService.request_deletion(user)
        deletion_request = GDPRService.confirm_deletion_token(
            str(deletion_request.token)
        )
        # Both admins hold a reference to the same PENDING_ADMIN row.
        stale_for_admin_b = DeletionRequest.objects.get(pk=deletion_request.pk)
        assert stale_for_admin_b.state == DeletionRequestState.PENDING_ADMIN

        # Admin A approves — runs to completion.
        GDPRService.admin_approve_deletion(deletion_request, admin_user=admin_a)

        # Admin B's Python object still says PENDING_ADMIN, but the DB
        # row is now EXECUTED. The service's re-fetch must see the
        # fresh state and refuse.
        with pytest.raises(DeletionRequestNotPending):
            GDPRService.admin_approve_deletion(stale_for_admin_b, admin_user=admin_b)

        # Anonymisation ran exactly once — verified by checking the
        # user is anonymised (not anonymised twice in a way that
        # would crash on idempotency).
        user.refresh_from_db()
        assert user.email == f"deleted_{user.pk}@deleted.invalid"

    def test_concurrent_approve_then_reject_blocks_reject(self, tenant):
        """Cross-action race: Admin A approves → state goes EXECUTED.
        Admin B (with their stale PENDING_ADMIN reference) tries to
        Reject. The service re-fetches, sees EXECUTED, raises. Proves
        the lock + state check works across action types, not just
        within Approve."""
        user = JasminUserFactory(roles=["member"], email="alice@example.com")
        admin_a = JasminUserFactory(roles=["admin"])
        admin_b = JasminUserFactory(roles=["admin"])
        deletion_request = GDPRService.request_deletion(user)
        deletion_request = GDPRService.confirm_deletion_token(
            str(deletion_request.token)
        )
        stale_for_admin_b = DeletionRequest.objects.get(pk=deletion_request.pk)

        GDPRService.admin_approve_deletion(deletion_request, admin_user=admin_a)

        with pytest.raises(DeletionRequestNotPending):
            GDPRService.admin_reject_deletion(
                stale_for_admin_b,
                admin_user=admin_b,
                reason="oops, I was about to reject",
            )


@pytest.mark.django_db
class TestAdminRejectDeletion:
    def test_happy_path_records_rejection(self, tenant):
        """Reject → mixin stamps admin_confirmed_by +
        admin_rejection_reason, state moves to REJECTED, user
        untouched."""
        user = JasminUserFactory(roles=["member"], email="alice@example.com")
        admin = JasminUserFactory(roles=["admin"])
        deletion_request = GDPRService.request_deletion(user)
        # Capture the returned (post-confirm) row — the in-memory
        # ``deletion_request`` above is now stale (state was
        # PENDING_EMAIL when it was returned from request_deletion).
        deletion_request = GDPRService.confirm_deletion_token(
            str(deletion_request.token)
        )

        result = GDPRService.admin_reject_deletion(
            deletion_request,
            admin_user=admin,
            reason="Member phoned to cancel the request.",
        )

        assert result.state == DeletionRequestState.REJECTED
        # AdminConfirmableMixin.reject() stamps _by + rejection_reason.
        assert result.admin_confirmed is False
        assert result.admin_confirmed_by_id == admin.pk
        assert "phoned to cancel" in result.admin_rejection_reason
        assert result.executed_at is None
        # ``admin_confirmed_at`` is stamped by ``admin_reject_deletion``
        # itself (NOT by the mixin's ``reject()``). The decided-
        # deletions inbox + the user-facing status banner both use
        # this timestamp as "when did the admin act on this", so
        # rejected rows must carry it. Regression test for the
        # 2026-06 fix that surfaced when the inbox view first
        # tried to display rejected rows.
        assert result.admin_confirmed_at is not None

        # And the user is untouched.
        user.refresh_from_db()
        assert user.email == "alice@example.com"

    def test_reject_rejects_when_not_pending_admin(self, tenant):
        user = JasminUserFactory(roles=["member"])
        admin = JasminUserFactory(roles=["admin"])
        deletion_request = GDPRService.request_deletion(user)

        with pytest.raises(DeletionRequestNotPending):
            GDPRService.admin_reject_deletion(
                deletion_request, admin_user=admin, reason="Anything."
            )

    def test_concurrent_double_reject_serialises_on_select_for_update(self, tenant):
        """Two admins clicking Reject on the same request must NOT
        both run the reject side-effects (rejection-email dispatch,
        REJECTED-state write with the SECOND admin's reason). The
        service re-fetches under ``select_for_update`` before its
        state check, so the second caller sees REJECTED and raises.
        Regression test for the race lock added in the 2026-06 audit.
        """
        user = JasminUserFactory(roles=["member"], email="alice@example.com")
        admin_a = JasminUserFactory(roles=["admin"])
        admin_b = JasminUserFactory(roles=["admin"])
        deletion_request = GDPRService.request_deletion(user)
        deletion_request = GDPRService.confirm_deletion_token(
            str(deletion_request.token)
        )
        stale_for_admin_b = DeletionRequest.objects.get(pk=deletion_request.pk)

        GDPRService.admin_reject_deletion(
            deletion_request,
            admin_user=admin_a,
            reason="Admin A's reason — should stick.",
        )

        with pytest.raises(DeletionRequestNotPending):
            GDPRService.admin_reject_deletion(
                stale_for_admin_b,
                admin_user=admin_b,
                reason="Admin B's reason — should be ignored.",
            )

        # First reject's reason + admin survived; second reject did
        # nothing.
        deletion_request.refresh_from_db()
        assert "Admin A's reason" in deletion_request.admin_rejection_reason
        assert deletion_request.admin_confirmed_by_id == admin_a.pk


# ---------------------------------------------------------------------------
# View layer — smoke tests for the four endpoints
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRequestDeletionView:
    def test_request_deletion_returns_202_and_does_not_anonymize(self, tenant):
        """The endpoint creates the PENDING_EMAIL row and returns 202.
        The user must still be intact afterwards."""
        user = JasminUserFactory(roles=["member"], email="alice@example.com")
        client = APIClient()
        client.force_authenticate(user=user)

        # Mock the email send so the test doesn't depend on SMTP config.
        with mock.patch(
            "apps.gdpr.views.send_deletion_confirmation_email"
        ) as mock_send:
            response = client.post(reverse("gdpr-request-deletion"))

        assert response.status_code == 202
        body = response.json()
        assert "request_id" in body
        # Default policy: admin gate is on.
        assert body["requires_admin_approval"] is True

        # Email helper was invoked exactly once with the new request.
        assert mock_send.call_count == 1
        sent_request = mock_send.call_args.args[1]
        assert sent_request.state == DeletionRequestState.PENDING_EMAIL

        # User row untouched.
        user.refresh_from_db()
        assert user.email == "alice@example.com"


@pytest.mark.django_db
class TestConfirmDeletionView:
    def test_confirm_with_valid_token_lands_in_pending_admin(self, tenant):
        """Admin approval is mandatory — confirming the email token
        moves the request to PENDING_ADMIN and stops there. The user
        row stays intact until the office decides."""
        user = JasminUserFactory(roles=["member"], email="alice@example.com")
        deletion_request = GDPRService.request_deletion(user)

        # AllowAny — no auth header required.
        response = APIClient().post(
            reverse(
                "gdpr-confirm-deletion",
                kwargs={"token": str(deletion_request.token)},
            )
        )

        assert response.status_code == 200
        assert response.json()["state"] == "pending_admin"
        user.refresh_from_db()
        assert user.email == "alice@example.com"

    def test_confirm_with_bad_token_returns_404(self, tenant):
        response = APIClient().post(
            reverse("gdpr-confirm-deletion", kwargs={"token": str(uuid.uuid4())})
        )

        assert response.status_code == 404
        assert response.json()["code"] == "gdpr.deletion_token_invalid"


@pytest.mark.django_db
class TestAdminApproveRejectViews:
    def test_admin_approve_endpoint_executes(self, tenant):
        user = JasminUserFactory(roles=["member"], email="alice@example.com")
        admin = JasminUserFactory(roles=["admin"])
        deletion_request = GDPRService.request_deletion(user)
        GDPRService.confirm_deletion_token(str(deletion_request.token))

        # gdpr-admin-approve-deletion is gated by RequiresStepUp; the
        # admin needs a fresh step-up claim to reach the view body.
        from apps.commissioning.tests.conftest import make_step_up_token

        client = APIClient()
        client.force_authenticate(user=admin, token=make_step_up_token(admin))
        response = client.post(
            reverse(
                "gdpr-admin-approve-deletion",
                kwargs={"request_id": str(deletion_request.pk)},
            )
        )

        assert response.status_code == 200
        assert response.json()["state"] == "executed"
        user.refresh_from_db()
        assert user.email != "alice@example.com"

    def test_admin_reject_requires_reason(self, tenant):
        user = JasminUserFactory(roles=["member"])
        admin = JasminUserFactory(roles=["admin"])
        deletion_request = GDPRService.request_deletion(user)
        GDPRService.confirm_deletion_token(str(deletion_request.token))

        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.post(
            reverse(
                "gdpr-admin-reject-deletion",
                kwargs={"request_id": str(deletion_request.pk)},
            ),
            data={"reason": ""},
            format="json",
        )

        assert response.status_code == 400
        assert response.json()["code"] == "gdpr.missing_rejection_reason"

    def test_admin_endpoints_forbidden_for_non_admin(self, tenant):
        user = JasminUserFactory(roles=["member"])
        not_admin = JasminUserFactory(roles=["member"])
        deletion_request = GDPRService.request_deletion(user)
        GDPRService.confirm_deletion_token(str(deletion_request.token))

        client = APIClient()
        client.force_authenticate(user=not_admin)
        approve = client.post(
            reverse(
                "gdpr-admin-approve-deletion",
                kwargs={"request_id": str(deletion_request.pk)},
            )
        )
        reject = client.post(
            reverse(
                "gdpr-admin-reject-deletion",
                kwargs={"request_id": str(deletion_request.pk)},
            ),
            data={"reason": "no"},
            format="json",
        )

        assert approve.status_code == 403
        assert reject.status_code == 403
