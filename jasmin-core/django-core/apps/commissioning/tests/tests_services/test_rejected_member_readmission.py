"""A rejected member stays rejected until the office re-invites them.

A member, subscription or coop-share confirm refuses a rejected member, also when
the caller still holds the row from before the reject; a member already
re-admitted keeps getting subscriptions confirmed. The office re-admits a
rejected member by sending a new invitation: accepting it confirms the member
and lifts the rejection, while an invitation from before the rejection stays
refused. Re-sending a login email repeats the invitation it replaces, so a
public self-registration's re-sent email confirms nobody.
"""

from __future__ import annotations

from unittest import mock

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.authz.roles import Role
from apps.commissioning.errors import MemberAlreadyRejected
from apps.commissioning.models import Member, UserInvitation
from apps.commissioning.models.choices import InvitationStatus
from apps.commissioning.services.member_service import MemberService
from apps.commissioning.tests.factories import (
    CoopShareFactory,
    JasminUserFactory,
    MemberFactory,
    SubscriptionFactory,
)
from apps.shared.invitations import (
    accept_invitation,
    create_user_with_invitation,
    resend_invitation,
)

PASSWORD = "N3wPass!Long123"


def _invited_applicant(office, *, names_member: bool):
    """An applicant with a login waiting for its invitation. An office
    invitation names the member; a public self-registration's names none."""
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
            member=member if names_member else None,
            created_by=office if names_member else None,
        )
    if not names_member:
        member.user = user
        member.save(update_fields=["user"])
    return member, user, invitation


@pytest.mark.django_db
class TestConfirmingARejectedMember:
    def test_a_member_confirm_is_refused(self, tenant):
        office = JasminUserFactory(roles=[Role.OFFICE])
        member, _user, _invitation = _invited_applicant(office, names_member=True)
        read_before_the_reject = Member.objects.get(pk=member.pk)
        MemberService().reject_and_notify(member, admin_user=office, reason=None)

        with pytest.raises(MemberAlreadyRejected):
            MemberService().confirm_and_notify(
                read_before_the_reject, admin_user=office
            )

        member.refresh_from_db()
        assert member.admin_confirmed is False
        assert member.admin_rejected_at is not None

    def test_a_subscription_confirm_does_not_admit_the_member(self, tenant):
        office = JasminUserFactory(roles=[Role.OFFICE])
        member, _user, _invitation = _invited_applicant(office, names_member=True)
        MemberService().reject_and_notify(member, admin_user=office, reason=None)
        subscription = SubscriptionFactory(member=member)

        with pytest.raises(MemberAlreadyRejected):
            with transaction.atomic():
                subscription.confirm(admin_user=office, save=True)

        subscription.refresh_from_db()
        member.refresh_from_db()
        assert subscription.admin_confirmed is False
        assert member.admin_confirmed is False

    def test_a_coop_share_confirm_is_refused(self, api_client, tenant):
        office = JasminUserFactory(roles=[Role.OFFICE])
        member, _user, _invitation = _invited_applicant(office, names_member=True)
        MemberService().reject_and_notify(member, admin_user=office, reason=None)
        share = CoopShareFactory(member=member, admin_confirmed=False)

        response = api_client.post(
            reverse("coop_shares-confirm", kwargs={"pk": share.pk})
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data["code"] == "member.already_rejected"
        share.refresh_from_db()
        member.refresh_from_db()
        assert share.admin_confirmed is False
        assert member.admin_confirmed is False

    def test_a_re_admitted_member_still_gets_subscriptions_confirmed(self, tenant):
        """A confirm keeps an earlier ``admin_rejected_at``; the member it
        re-admitted is a member like any other."""
        office = JasminUserFactory(roles=[Role.OFFICE])
        member = MemberFactory(admin_confirmed=True, admin_rejected_at=timezone.now())
        subscription = SubscriptionFactory(member=member)

        with transaction.atomic():
            subscription.confirm(admin_user=office, save=True)

        subscription.refresh_from_db()
        assert subscription.admin_confirmed is True


@pytest.mark.django_db
class TestReInvitingARejectedMember:
    def test_accepting_the_re_invite_re_admits_without_the_rejection(self, tenant):
        office = JasminUserFactory(roles=[Role.OFFICE])
        member, _user, _invitation = _invited_applicant(office, names_member=True)
        MemberService().reject_and_notify(member, admin_user=office, reason=None)

        with mock.patch("apps.shared.invitations._send_invitation_email"):
            MemberService().send_invitation(member, admin_user=office)
        re_invite = member.user.invitations.order_by("-created_at").first()
        accept_invitation(token=str(re_invite.token), password=PASSWORD)

        member.refresh_from_db()
        assert member.admin_confirmed is True
        assert member.admin_rejected_at is None

    def test_an_invitation_from_before_the_rejection_is_refused(self, tenant):
        office = JasminUserFactory(roles=[Role.OFFICE])
        member, user, invitation = _invited_applicant(office, names_member=True)
        MemberService().reject_and_notify(member, admin_user=office, reason=None)
        UserInvitation.objects.filter(pk=invitation.pk).update(
            status=InvitationStatus.SENT
        )

        with pytest.raises(ValidationError):
            accept_invitation(token=str(invitation.token), password=PASSWORD)

        member.refresh_from_db()
        user.refresh_from_db()
        assert member.admin_confirmed is False
        assert member.admin_rejected_at is not None
        assert user.account_status == "inactive"

    def test_accepting_after_the_login_was_unlinked_confirms_nobody(self, tenant):
        office = JasminUserFactory(roles=[Role.OFFICE])
        member, user, invitation = _invited_applicant(office, names_member=True)
        Member.objects.filter(pk=member.pk).update(user=None)

        accept_invitation(token=str(invitation.token), password=PASSWORD)

        member.refresh_from_db()
        user.refresh_from_db()
        assert user.account_status == "active"
        assert member.admin_confirmed is False


@pytest.mark.django_db
class TestReSendingALoginEmail:
    def test_a_self_registrations_re_sent_email_confirms_nobody(self, tenant):
        office = JasminUserFactory(roles=[Role.OFFICE])
        member, user, _invitation = _invited_applicant(office, names_member=False)

        with mock.patch("apps.shared.invitations._send_invitation_email"):
            re_sent = resend_invitation(user=user, created_by=office)
        accept_invitation(token=str(re_sent.token), password=PASSWORD)

        member.refresh_from_db()
        assert re_sent.member_id is None
        assert member.admin_confirmed is False

    def test_an_office_member_invitation_stays_one(self, tenant):
        office = JasminUserFactory(roles=[Role.OFFICE])
        member, user, _invitation = _invited_applicant(office, names_member=True)

        with mock.patch("apps.shared.invitations._send_invitation_email"):
            re_sent = resend_invitation(user=user, created_by=office)
        accept_invitation(token=str(re_sent.token), password=PASSWORD)

        member.refresh_from_db()
        assert re_sent.member_id == member.pk
        assert member.admin_confirmed is True
