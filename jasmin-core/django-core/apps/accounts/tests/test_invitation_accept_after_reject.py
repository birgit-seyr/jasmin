"""Accepting an invitation decides on the rows as they are when it writes.

The accept reads the invitation first and checks the password (zxcvbn, slow)
before it writes. A member reject that commits in between cancels the invitation
and deactivates the login; the accept then refuses and leaves the rejection as
it is, instead of writing back what it read.
"""

from __future__ import annotations

from unittest import mock

import pytest
from django.core.exceptions import ValidationError

from apps.authz.roles import Role
from apps.commissioning.models.choices import InvitationStatus
from apps.commissioning.services.member_service import MemberService
from apps.commissioning.tests.factories import JasminUserFactory, MemberFactory
from apps.shared import invitations
from apps.shared.invitations import accept_invitation, create_user_with_invitation

PASSWORD = "N3wPass!Long123"


@pytest.mark.django_db
class TestAcceptingAfterTheMemberWasRejected:
    def test_a_reject_between_reading_and_writing_wins(self, tenant):
        office = JasminUserFactory(roles=[Role.OFFICE])
        member = MemberFactory(
            user=None,
            email="applicant@example.org",
            admin_confirmed=False,
            is_trial=False,
        )
        with mock.patch("apps.shared.invitations._send_invitation_email"):
            user, invitation = create_user_with_invitation(
                email=member.email,
                first_name="Pat",
                last_name="Pending",
                roles=[Role.MEMBER],
                member=member,
                created_by=office,
            )

        # What the accept reads before the password check...
        read_before_the_reject = invitations.get_invitation(str(invitation.token))
        # ...and the reject that commits while that check runs.
        MemberService().reject_and_notify(member, admin_user=office, reason=None)

        with mock.patch.object(
            invitations, "get_invitation", return_value=read_before_the_reject
        ):
            with pytest.raises(ValidationError):
                accept_invitation(token=str(invitation.token), password=PASSWORD)

        member.refresh_from_db()
        user.refresh_from_db()
        invitation.refresh_from_db()
        assert member.admin_rejected_at is not None
        assert member.admin_confirmed is False
        assert user.account_status == "inactive"
        assert invitation.status == InvitationStatus.CANCELLED
