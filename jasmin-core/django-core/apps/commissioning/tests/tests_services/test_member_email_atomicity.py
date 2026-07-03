"""Atomicity contract for member lifecycle emails (P1-3).

`MemberService.confirm_and_notify` / `reject_and_notify` schedule
their notification email via ``transaction.on_commit``. The contract
this test pins down:

  * the email is dispatched only AFTER the surrounding atomic block
    commits, so a rollback elsewhere in the request cycle does NOT
    leave the applicant with a "confirmed" mail for a Member whose
    confirmation never persisted.
  * the same path still works for the happy case (commit → email
    fires).

Pytest-django wraps every test in a transaction that rolls back at
teardown, so ``transaction.on_commit`` callbacks NEVER fire on their
own here. We use Django's ``TestCase.captureOnCommitCallbacks`` (with
``execute=True`` for the happy path) and a manual savepoint for the
rollback case.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.db import transaction
from django.test import TestCase

from apps.commissioning.services.member_service import MemberService
from apps.commissioning.tests.factories import JasminUserFactory, MemberFactory


@pytest.mark.django_db(transaction=True)
class TestConfirmAndNotifyAtomicity:
    """``confirm_and_notify`` is the canonical state-change-then-email
    flow — if either half fails, neither side-effect must persist."""

    def test_email_fires_after_commit_on_happy_path(self, tenant):
        admin = JasminUserFactory(roles=["office"])
        # ``Member.email`` has unique=True and we run under
        # ``transaction=True`` (each test commits) — so every test in
        # this class needs its own email address to avoid a constraint
        # collision with a sibling test's persisted row.
        member = MemberFactory(
            email="confirm-happy@example.org",
            admin_confirmed=False,
        )

        with patch(
            "apps.shared.tenants.email_service.EmailService.send_email",
            return_value=True,
        ) as send_mock:
            with TestCase.captureOnCommitCallbacks(execute=True):
                MemberService().confirm_and_notify(member, admin_user=admin)

        # The persistent state change committed.
        member.refresh_from_db()
        assert member.admin_confirmed is True
        # AND the email fired exactly once with the expected slug.
        send_mock.assert_called_once()
        assert send_mock.call_args.kwargs["slug"] == "accounts.application_approved"

    def test_email_does_not_fire_when_outer_transaction_rolls_back(self, tenant):
        """If the caller wraps the service call in its own atomic block
        and then raises, the on_commit callback must be discarded — no
        ghost email for a non-existent confirmation.
        """
        admin = JasminUserFactory(roles=["office"])
        member = MemberFactory(
            email="confirm-rollback@example.org",
            admin_confirmed=False,
        )

        with patch(
            "apps.shared.tenants.email_service.EmailService.send_email",
            return_value=True,
        ) as send_mock:
            with TestCase.captureOnCommitCallbacks(execute=True):
                try:
                    with transaction.atomic():
                        MemberService().confirm_and_notify(member, admin_user=admin)
                        raise RuntimeError("simulated downstream failure")
                except RuntimeError:
                    pass

        # State change rolled back.
        member.refresh_from_db()
        assert member.admin_confirmed is False
        # AND the email never fired.
        send_mock.assert_not_called()


@pytest.mark.django_db(transaction=True)
class TestRejectAndNotifyAtomicity:
    def test_email_fires_after_commit_on_happy_path(self, tenant):
        admin = JasminUserFactory(roles=["office"])
        member = MemberFactory(
            email="reject-happy@example.org",
            admin_confirmed=False,
        )

        with patch(
            "apps.shared.tenants.email_service.EmailService.send_email",
            return_value=True,
        ) as send_mock:
            with TestCase.captureOnCommitCallbacks(execute=True):
                MemberService().reject_and_notify(
                    member, admin_user=admin, reason="incomplete"
                )

        send_mock.assert_called_once()
        assert send_mock.call_args.kwargs["slug"] == "accounts.application_rejected"

    def test_email_does_not_fire_when_outer_transaction_rolls_back(self, tenant):
        admin = JasminUserFactory(roles=["office"])
        member = MemberFactory(
            email="reject-rollback@example.org",
            admin_confirmed=False,
        )

        with patch(
            "apps.shared.tenants.email_service.EmailService.send_email",
            return_value=True,
        ) as send_mock:
            with TestCase.captureOnCommitCallbacks(execute=True):
                try:
                    with transaction.atomic():
                        MemberService().reject_and_notify(
                            member, admin_user=admin, reason="incomplete"
                        )
                        raise RuntimeError("simulated downstream failure")
                except RuntimeError:
                    pass

        send_mock.assert_not_called()


@pytest.mark.django_db(transaction=True)
class TestRejectDeactivatesLinkedUser:
    """Rejecting a member also flips the linked JasminUser to
    ``inactive`` so the rejected applicant can no longer log into the
    portal. Same transaction as the reject stamp — a rolled-back
    rejection leaves the user account untouched.
    """

    def test_rejection_deactivates_active_user(self, tenant):
        from apps.commissioning.tests.factories import JasminUserFactory, MemberFactory

        admin = JasminUserFactory(roles=["office"])
        active_user = JasminUserFactory(account_status="active", roles=["member"])
        member = MemberFactory(
            email="deactivate-active@example.org",
            admin_confirmed=False,
            user=active_user,
        )
        assert active_user.is_active is True

        with patch(
            "apps.shared.tenants.email_service.EmailService.send_email",
            return_value=True,
        ):
            with TestCase.captureOnCommitCallbacks(execute=True):
                MemberService().reject_and_notify(
                    member, admin_user=admin, reason="not this season"
                )

        active_user.refresh_from_db()
        assert active_user.account_status == "inactive"
        assert active_user.is_active is False

    def test_rejection_cancels_pending_invitation(self, tenant):
        """An accepted invitation link MUST stop working once the
        application is rejected — otherwise the applicant could still
        activate the account post-rejection.
        """
        from apps.commissioning.models import UserInvitation
        from apps.commissioning.tests.factories import JasminUserFactory, MemberFactory

        admin = JasminUserFactory(roles=["office"])
        pending_user = JasminUserFactory(
            account_status="pending_invitation", roles=["member"]
        )
        invitation = UserInvitation.objects.create(
            user=pending_user,
            email=pending_user.email,
            status="sent",
            expires_at=__import__("django").utils.timezone.now()
            + __import__("datetime").timedelta(days=7),
            created_by=admin,
        )
        member = MemberFactory(
            email="deactivate-pending@example.org",
            admin_confirmed=False,
            user=pending_user,
        )

        with patch(
            "apps.shared.tenants.email_service.EmailService.send_email",
            return_value=True,
        ):
            with TestCase.captureOnCommitCallbacks(execute=True):
                MemberService().reject_and_notify(member, admin_user=admin, reason=None)

        pending_user.refresh_from_db()
        invitation.refresh_from_db()
        assert pending_user.account_status == "inactive"
        assert invitation.status == "cancelled"

    def test_rejection_without_linked_user_is_noop(self, tenant):
        from apps.commissioning.tests.factories import JasminUserFactory, MemberFactory

        admin = JasminUserFactory(roles=["office"])
        member = MemberFactory(
            email="deactivate-no-user@example.org",
            admin_confirmed=False,
            user=None,
        )

        with patch(
            "apps.shared.tenants.email_service.EmailService.send_email",
            return_value=True,
        ):
            with TestCase.captureOnCommitCallbacks(execute=True):
                # Should not raise even when there's no linked user.
                MemberService().reject_and_notify(member, admin_user=admin, reason=None)

        member.refresh_from_db()
        assert member.admin_rejected_at is not None

    def test_rollback_leaves_user_active(self, tenant):
        """If the surrounding transaction rolls back, the user must
        stay active — same atomicity guarantee as the email send.
        """
        from apps.commissioning.tests.factories import JasminUserFactory, MemberFactory

        admin = JasminUserFactory(roles=["office"])
        active_user = JasminUserFactory(account_status="active", roles=["member"])
        member = MemberFactory(
            email="deactivate-rollback@example.org",
            admin_confirmed=False,
            user=active_user,
        )

        with patch(
            "apps.shared.tenants.email_service.EmailService.send_email",
            return_value=True,
        ):
            with TestCase.captureOnCommitCallbacks(execute=True):
                try:
                    with transaction.atomic():
                        MemberService().reject_and_notify(
                            member, admin_user=admin, reason="oops"
                        )
                        raise RuntimeError("simulated downstream failure")
                except RuntimeError:
                    pass

        active_user.refresh_from_db()
        assert active_user.account_status == "active"
        assert active_user.is_active is True
