"""A member whose linked user was deactivated (e.g. via
``reject_and_notify``) must be re-invitable through ``send_invitation`` —
it should resend instead of dead-ending with the misleading
``MemberUserAlreadyActive`` ("already has an active user account") for a user
that is in fact INACTIVE.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.commissioning.errors import (
    MemberEmailHeldByNonMemberLogin,
    MemberUserAlreadyActive,
)
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
        """send_invitation must provision the user + invitation for a member
        without a linked user (every brand-new member invite).
        ``create_user_with_invitation`` only accepts ``user_language=`` — passing
        ``language=`` raises TypeError."""
        member = MemberFactory(user=None, email="newmember@example.com")
        office = JasminUserFactory(roles=["office"])

        with patch("apps.shared.invitations._send_invitation_email"):
            MemberService().send_invitation(member, admin_user=office)

        member.refresh_from_db()
        assert member.user is not None
        assert UserInvitation.objects.filter(user=member.user, status="sent").exists()


@pytest.mark.django_db
class TestSendInvitationDoesNotTakeOverANonMemberLogin:
    """An unlinked member whose address matches a login with NO member profile
    must be refused rather than re-provisioned.

    ``create_user_with_invitation`` reuses ``inactive`` / ``pending_invitation``
    rows, so without this the office would hand an existing account — its
    primary key, and every ``created_by`` reference pointing at it — to a
    different person. ``send_invitation`` is office-gated, not admin-gated,
    which is what makes it worth pinning.
    """

    def _office(self):
        return JasminUserFactory(roles=["office"])

    def test_a_deactivated_staff_login_is_not_taken_over(self, tenant):
        staff = JasminUserFactory(
            email="ex.staff@example.com",
            first_name="Former",
            last_name="Employee",
            roles=["office"],
            account_status="inactive",
        )
        member = MemberFactory(
            user=None,
            email="ex.staff@example.com",
            first_name="New",
            last_name="Member",
        )

        with pytest.raises(MemberEmailHeldByNonMemberLogin):
            MemberService().send_invitation(member, admin_user=self._office())

        staff.refresh_from_db()
        member.refresh_from_db()
        # Untouched on every axis the reuse branch would have rewritten.
        assert staff.first_name == "Former"
        assert staff.roles == ["office"]
        assert staff.account_status == "inactive"
        assert member.user is None
        assert not UserInvitation.objects.filter(user=staff).exists()

    def test_a_staff_invitation_in_flight_is_not_hijacked(self, tenant):
        staff = JasminUserFactory(
            email="pending.staff@example.com",
            roles=["office"],
            account_status="pending_invitation",
        )
        member = MemberFactory(user=None, email="pending.staff@example.com")

        with pytest.raises(MemberEmailHeldByNonMemberLogin):
            MemberService().send_invitation(member, admin_user=self._office())

        staff.refresh_from_db()
        assert staff.roles == ["office"]
        assert staff.account_status == "pending_invitation"
