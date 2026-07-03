"""COR-25: a member whose linked user was deactivated (e.g. via
``reject_and_notify``) must be re-invitable through ``send_invitation`` —
it should resend instead of dead-ending with the misleading
``MemberUserAlreadyActive`` ("already has an active user account") for a user
that is in fact INACTIVE.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.commissioning.errors import MemberUserAlreadyActive
from apps.commissioning.models import UserInvitation
from apps.commissioning.services.member_service import MemberService
from apps.commissioning.tests.factories import JasminUserFactory, MemberFactory


@pytest.mark.django_db
class TestSendInvitationReinvite:
    def test_inactive_linked_user_is_reinvited(self, tenant):
        user = JasminUserFactory(
            email="reinvite@example.com", account_status="inactive"
        )
        member = MemberFactory(user=user, email="reinvite@example.com")
        office = JasminUserFactory(roles=["office"])

        # Mock only the email side-effect; the re-invitation logic (status
        # flip + fresh UserInvitation) runs for real.
        with patch("apps.shared.invitations._send_invitation_email"):
            MemberService().send_invitation(member, admin_user=office)

        user.refresh_from_db()
        # resend_invitation re-provisioned the inactive user back to pending.
        assert user.account_status == "pending_invitation"
        assert UserInvitation.objects.filter(user=user, status="sent").exists()

    def test_active_linked_user_still_conflicts(self, tenant):
        """The guard still fires for a genuinely active account — only
        inactive/pending get the resend path."""
        user = JasminUserFactory(email="active@example.com", account_status="active")
        member = MemberFactory(user=user, email="active@example.com")
        office = JasminUserFactory(roles=["office"])

        with pytest.raises(MemberUserAlreadyActive):
            MemberService().send_invitation(member, admin_user=office)

    def test_unlinked_member_with_email_is_invited(self, tenant):
        """Regression: send_invitation passed ``language=`` to
        ``create_user_with_invitation`` (which only accepts ``user_language=``),
        raising TypeError for any member without a linked user — i.e. every
        brand-new member invite. It must now provision the user + invitation."""
        member = MemberFactory(user=None, email="newmember@example.com")
        office = JasminUserFactory(roles=["office"])

        with patch("apps.shared.invitations._send_invitation_email"):
            MemberService().send_invitation(member, admin_user=office)

        member.refresh_from_db()
        assert member.user is not None
        assert UserInvitation.objects.filter(user=member.user, status="sent").exists()
