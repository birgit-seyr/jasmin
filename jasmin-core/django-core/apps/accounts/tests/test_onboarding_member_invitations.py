"""Onboarding mode and the invitation emails of Configuration > Users.

While ``TenantSettings.onboarding_mode`` is on, a member's portal invitation is
a member email. Re-sending it from ``auth/admin/users/{id}/resend-invitation/``
is refused before anything changes, as ``members/{id}/send_invitation`` is,
while staff and customer invitations are still re-sent. Accepting an invitation
the office made for a member's portal login sends a suppressed welcome; the
welcome after a staff invitation or a public self-registration still goes out.
The SMTP connection is Django's in-memory backend, below the ``send_email`` mock
other suites use.
"""

from __future__ import annotations

import datetime
from unittest import mock

import pytest
import time_machine
from django.core import mail
from django.core.mail import get_connection
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.authz.roles import Role
from apps.commissioning.models import UserInvitation
from apps.commissioning.models.choices import InvitationStatus
from apps.commissioning.tests.factories import JasminUserFactory, MemberFactory
from apps.notifications.models import EmailLog
from apps.shared.invitations import accept_invitation, create_user_with_invitation
from apps.shared.tenants.email_service import EmailService
from apps.shared.tenants.models import (
    ActionRateLog,
    RateLimitedAction,
    TenantEmailConfig,
    TenantSettings,
)

BLOCKED_CODE = "onboarding_mode.email_action_blocked"
PASSWORD = "N3wPass!Long123"


@pytest.fixture(autouse=True)
def _frozen_clock():
    # A Monday away from any year boundary.
    with time_machine.travel(datetime.datetime(2026, 7, 13, 12, 0), tick=False):
        yield


def _configure_settings(tenant, *, onboarding_mode: bool) -> None:
    """Open settings row with the mode and no coop share minimum, so a member
    can be confirmed when their invitation is accepted."""
    row = TenantSettings.objects.filter(tenant=tenant, valid_until__isnull=True).first()
    if row is None:
        row = TenantSettings.objects.create(
            tenant=tenant, valid_from=timezone.now() - datetime.timedelta(days=365)
        )
    elif row.valid_from > timezone.now():
        # The frozen clock sits before a row opened in real time; move its start
        # back so ``get_current_settings`` sees it.
        row.valid_from = timezone.now() - datetime.timedelta(days=365)
    row.onboarding_mode = onboarding_mode
    row.min_number_coop_shares = 0
    row.save()


@pytest.fixture()
def onboarding_mode(tenant):
    _configure_settings(tenant, onboarding_mode=True)


@pytest.fixture()
def onboarding_mode_off(tenant):
    _configure_settings(tenant, onboarding_mode=False)


@pytest.fixture()
def email_config(tenant):
    return TenantEmailConfig.objects.create(
        tenant=tenant,
        smtp_host="localhost",
        smtp_port=25,
        smtp_use_tls=False,
        from_email="noreply@example.org",
        from_name="Test Farm",
        is_active=True,
        is_verified=True,
    )


@pytest.fixture()
def outbox():
    """The in-memory outbox that stands in for the tenant's SMTP server."""
    mail.outbox.clear()
    in_memory = get_connection(backend="django.core.mail.backends.locmem.EmailBackend")
    with mock.patch.object(EmailService, "_get_connection", return_value=in_memory):
        yield mail.outbox


@pytest.fixture()
def admin_client(tenant):
    client = APIClient()
    client.force_authenticate(user=JasminUserFactory(roles=[Role.ADMIN]))
    return client


def _statuses(slug: str) -> list[str]:
    return list(EmailLog.objects.filter(template=slug).values_list("status", flat=True))


def _quota_used() -> int:
    return ActionRateLog.objects.filter(action=RateLimitedAction.USER_CREATION).count()


def _pending_login(email: str, *, roles: list[str], member=None, created_by=None):
    """A login waiting for its invitation, created without sending the email."""
    with mock.patch("apps.shared.invitations._send_invitation_email"):
        return create_user_with_invitation(
            email=email,
            first_name="Pat",
            last_name="Pending",
            roles=roles,
            member=member,
            created_by=created_by,
        )


def _resend(client, user):
    return client.post(
        f"/api/auth/admin/users/{user.id}/resend-invitation/", data={}, format="json"
    )


@pytest.mark.django_db
class TestAdminResendInvitation:
    def test_a_member_resend_is_refused_while_on_before_anything_changes(
        self, admin_client, onboarding_mode, email_config, outbox
    ):
        member = MemberFactory(user=None, email="pending.member@example.org")
        user, open_invitation = _pending_login(
            member.email, roles=[Role.MEMBER], member=member
        )
        quota_used = _quota_used()

        resp = _resend(admin_client, user)

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == BLOCKED_CODE
        open_invitation.refresh_from_db()
        assert open_invitation.status == InvitationStatus.SENT
        assert UserInvitation.objects.filter(user=user).count() == 1
        assert _quota_used() == quota_used
        assert outbox == []
        assert EmailLog.objects.count() == 0

    def test_a_member_resend_is_sent_while_off(
        self,
        admin_client,
        onboarding_mode_off,
        email_config,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        member = MemberFactory(user=None, email="pending.member@example.org")
        user, open_invitation = _pending_login(
            member.email, roles=[Role.MEMBER], member=member
        )

        with django_capture_on_commit_callbacks(execute=True):
            resp = _resend(admin_client, user)

        assert resp.status_code == status.HTTP_200_OK, resp.data
        open_invitation.refresh_from_db()
        assert open_invitation.status == InvitationStatus.CANCELLED
        assert UserInvitation.objects.filter(
            user=user, status=InvitationStatus.SENT
        ).exists()
        assert len(outbox) == 1
        assert _statuses("accounts.invitation") == ["sent"]

    @pytest.mark.parametrize(
        ("roles", "with_member_profile"),
        [
            ([Role.OFFICE], False),
            ([Role.GARDENER], False),
            ([Role.CUSTOMER], False),
            ([Role.OFFICE, Role.MEMBER], True),
        ],
    )
    def test_a_staff_or_customer_resend_is_sent_while_on(
        self,
        admin_client,
        onboarding_mode,
        email_config,
        outbox,
        django_capture_on_commit_callbacks,
        roles,
        with_member_profile,
    ):
        email = "pending.login@example.org"
        member = MemberFactory(user=None, email=email) if with_member_profile else None
        user, _open_invitation = _pending_login(email, roles=roles, member=member)

        with django_capture_on_commit_callbacks(execute=True):
            resp = _resend(admin_client, user)

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert len(outbox) == 1
        assert outbox[0].to == [email]
        assert _statuses("accounts.invitation") == ["sent"]


@pytest.mark.django_db
class TestWelcomeAfterAcceptingWhileOn:
    def test_the_welcome_after_an_office_member_invitation_is_suppressed(
        self,
        tenant,
        onboarding_mode,
        email_config,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        office = JasminUserFactory(roles=[Role.OFFICE])
        member = MemberFactory(
            user=None,
            email="invited.member@example.org",
            admin_confirmed=False,
            is_trial=False,
        )
        user, invitation = _pending_login(
            member.email, roles=[Role.MEMBER], member=member, created_by=office
        )

        with django_capture_on_commit_callbacks(execute=True):
            accept_invitation(token=str(invitation.token), password=PASSWORD)

        user.refresh_from_db()
        member.refresh_from_db()
        assert user.account_status == "active"
        assert member.admin_confirmed is True
        assert outbox == []
        row = EmailLog.objects.get(template="accounts.welcome_user")
        assert (row.status, row.recipient) == (
            "suppressed",
            "invited.member@example.org",
        )

    def test_the_welcome_after_a_staff_invitation_is_sent(
        self,
        tenant,
        onboarding_mode,
        email_config,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        admin = JasminUserFactory(roles=[Role.ADMIN])
        _user, invitation = _pending_login(
            "new.gardener@example.org", roles=[Role.GARDENER], created_by=admin
        )

        with django_capture_on_commit_callbacks(execute=True):
            accept_invitation(token=str(invitation.token), password=PASSWORD)

        assert [message.to for message in outbox] == [["new.gardener@example.org"]]
        assert _statuses("accounts.welcome_user") == ["sent"]

    def test_the_welcome_after_a_self_registration_is_sent(
        self,
        tenant,
        onboarding_mode,
        email_config,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        # Public self-registration creates the invitation with neither a member
        # nor an inviter and links the member it creates afterwards.
        user, invitation = _pending_login("applicant@example.org", roles=[Role.MEMBER])
        MemberFactory(user=user, email=user.email, admin_confirmed=False)

        with django_capture_on_commit_callbacks(execute=True):
            accept_invitation(token=str(invitation.token), password=PASSWORD)

        assert [message.to for message in outbox] == [["applicant@example.org"]]
        assert _statuses("accounts.welcome_user") == ["sent"]
