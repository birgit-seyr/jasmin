"""Onboarding mode and member emails on the commissioning paths.

While ``TenantSettings.onboarding_mode`` is on, ``EmailService.send_email``
suppresses member emails. ``members/{id}/send_invitation`` and
``abos/{id}/offer_spot``, whose whole purpose is the email, are refused before
they change anything. Member flows mark the invitation and welcome emails they
share with login flows, so a member's portal invitation is suppressed while a
staff invitation still goes out. An office cancellation and the renewal digest
still run; only their emails are suppressed. The SMTP connection is Django's
in-memory backend, below the ``send_email`` mock other suites use.
"""

from __future__ import annotations

import datetime
from unittest import mock

import pytest
import time_machine
from django.core import mail
from django.core.mail import get_connection
from django.urls import reverse
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework import status

from apps.accounts.models import JasminUser
from apps.commissioning import tasks
from apps.commissioning.models import Subscription, UserInvitation
from apps.commissioning.models.choices import InvitationStatus
from apps.commissioning.services.member_service import MemberService
from apps.commissioning.services.waiting_list_offer_service import (
    WaitingListOfferService,
)
from apps.commissioning.tests.factories import (
    CoopShareFactory,
    DeliveryStationDayFactory,
    JasminUserFactory,
    MemberFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)
from apps.notifications.models import EmailLog
from apps.shared.invitations import create_user_with_invitation
from apps.shared.tenants.email_service import EmailService
from apps.shared.tenants.models import (
    ActionRateLog,
    RateLimitedAction,
    TenantEmailConfig,
    TenantSettings,
)

BLOCKED_CODE = "onboarding_mode.email_action_blocked"


@pytest.fixture(autouse=True)
def _frozen_clock():
    # A Monday away from any year boundary.
    with time_machine.travel(datetime.datetime(2026, 7, 13, 12, 0), tick=False):
        yield


def _configure_settings(tenant, *, onboarding_mode: bool) -> None:
    """Open settings row with the mode and no coop share minimum, so members
    without shares can be confirmed."""
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


def _statuses(slug: str) -> list[str]:
    return list(EmailLog.objects.filter(template=slug).values_list("status", flat=True))


def _invitation_url(member) -> str:
    return reverse("member-send-invitation", kwargs={"pk": member.pk})


@pytest.mark.django_db
class TestSendInvitationEndpoint:
    def test_refused_while_on_before_anything_changes(
        self, api_client, onboarding_mode
    ):
        member = MemberFactory(user=None, email="new.member@example.org")
        quota_used = ActionRateLog.objects.filter(
            action=RateLimitedAction.USER_CREATION
        ).count()

        resp = api_client.post(_invitation_url(member))

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == BLOCKED_CODE
        member.refresh_from_db()
        assert member.user_id is None
        assert not JasminUser.objects.filter(email__iexact=member.email).exists()
        assert not UserInvitation.objects.filter(email=member.email).exists()
        assert (
            ActionRateLog.objects.filter(action=RateLimitedAction.USER_CREATION).count()
            == quota_used
        )

    def test_resend_refused_while_on_keeps_the_open_invitation(
        self, api_client, onboarding_mode
    ):
        member = MemberFactory(user=None, email="pending.member@example.org")
        with mock.patch("apps.shared.invitations._send_invitation_email"):
            user, open_invitation = create_user_with_invitation(
                email=member.email,
                first_name="Paula",
                last_name="Pending",
                roles=["member"],
                member=member,
            )

        resp = api_client.post(_invitation_url(member))

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == BLOCKED_CODE
        open_invitation.refresh_from_db()
        assert open_invitation.status == InvitationStatus.SENT
        assert UserInvitation.objects.filter(user=user).count() == 1

    def test_invitation_sent_while_off(
        self,
        api_client,
        onboarding_mode_off,
        email_config,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        member = MemberFactory(user=None, email="new.member@example.org")

        with django_capture_on_commit_callbacks(execute=True):
            resp = api_client.post(_invitation_url(member))

        assert resp.status_code == status.HTTP_200_OK, resp.data
        member.refresh_from_db()
        assert member.user is not None
        assert UserInvitation.objects.filter(
            user=member.user, status=InvitationStatus.SENT
        ).exists()
        assert len(outbox) == 1
        assert _statuses("accounts.invitation") == ["sent"]


@pytest.mark.django_db
class TestSharedLoginSlugsWhileOn:
    def test_a_member_invitation_is_suppressed(
        self,
        tenant,
        onboarding_mode,
        email_config,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        member = MemberFactory(user=None, email="new.member@example.org")
        office = JasminUserFactory(roles=["office"])

        with django_capture_on_commit_callbacks(execute=True):
            MemberService().send_invitation(member, admin_user=office)

        assert outbox == []
        row = EmailLog.objects.get(template="accounts.invitation")
        assert (row.status, row.recipient) == ("suppressed", "new.member@example.org")

    def test_a_member_invitation_resend_is_suppressed(
        self,
        tenant,
        onboarding_mode,
        email_config,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        member = MemberFactory(user=None, email="pending.member@example.org")
        office = JasminUserFactory(roles=["office"])
        with mock.patch("apps.shared.invitations._send_invitation_email"):
            user, open_invitation = create_user_with_invitation(
                email=member.email,
                first_name="Paula",
                last_name="Pending",
                roles=["member"],
                member=member,
                created_by=office,
            )

        with django_capture_on_commit_callbacks(execute=True):
            MemberService().send_invitation(member, admin_user=office)

        open_invitation.refresh_from_db()
        assert open_invitation.status == InvitationStatus.CANCELLED
        assert UserInvitation.objects.filter(
            user=user, status=InvitationStatus.SENT
        ).exists()
        assert outbox == []
        row = EmailLog.objects.get(template="accounts.invitation")
        assert (row.status, row.recipient) == (
            "suppressed",
            "pending.member@example.org",
        )

    def test_a_staff_invitation_is_sent(
        self,
        tenant,
        onboarding_mode,
        email_config,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        office = JasminUserFactory(roles=["office"])

        with django_capture_on_commit_callbacks(execute=True):
            create_user_with_invitation(
                email="new.office@example.org",
                first_name="Olga",
                last_name="Office",
                roles=["office"],
                created_by=office,
            )

        assert len(outbox) == 1
        assert _statuses("accounts.invitation") == ["sent"]

    def test_the_welcome_on_linking_a_member_to_an_active_user_is_suppressed(
        self,
        tenant,
        onboarding_mode,
        email_config,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        user = JasminUserFactory(
            email="active.user@example.org", account_status="active"
        )
        member = MemberFactory(
            user=None,
            email="active.user@example.org",
            admin_confirmed=False,
            is_trial=False,
        )
        office = JasminUserFactory(roles=["office"])

        with django_capture_on_commit_callbacks(execute=True):
            MemberService().link_to_user(
                member, user, admin_user=office, notify_user=True
            )

        member.refresh_from_db()
        assert member.admin_confirmed is True
        assert outbox == []
        assert _statuses("accounts.welcome_user") == ["suppressed"]


@pytest.mark.django_db
class TestOfferSpotEndpoint:
    @pytest.fixture()
    def pending_entry(self, tenant):
        return SubscriptionFactory(
            share_type_variation=ShareTypeVariationFactory(capacity=5),
            default_delivery_station_day=DeliveryStationDayFactory(),
            admin_confirmed=False,
            on_waiting_list=True,
            waiting_list_status=Subscription.WaitingListStatus.PENDING,
            valid_from=datetime.date(2026, 1, 5),  # Monday
            valid_until=datetime.date(2027, 1, 3),  # Sunday
        )

    @pytest.fixture()
    def hold_and_email(self):
        """The station-day hold and the offer email, covered by their own
        suites; here they only show whether the offer got that far."""
        with (
            mock.patch(
                "apps.commissioning.services.waiting_list_offer_service."
                "CapacityReservationService.reserve_for_subscription",
                return_value=None,
            ) as reserve,
            mock.patch.object(
                WaitingListOfferService, "_send_offer_email", return_value=None
            ) as send_offer,
        ):
            yield reserve, send_offer

    def test_refused_while_on_before_anything_changes(
        self, api_client, onboarding_mode, pending_entry, hold_and_email
    ):
        reserve, send_offer = hold_and_email

        resp = api_client.post(
            reverse("abos-offer-spot", kwargs={"pk": pending_entry.pk}),
            {},
            format="json",
        )

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == BLOCKED_CODE
        pending_entry.refresh_from_db()
        assert pending_entry.waiting_list_status == (
            Subscription.WaitingListStatus.PENDING
        )
        assert pending_entry.notification_token is None
        assert pending_entry.notification_expires_at is None
        reserve.assert_not_called()
        send_offer.assert_not_called()

    def test_offered_while_off(
        self, api_client, onboarding_mode_off, pending_entry, hold_and_email
    ):
        reserve, send_offer = hold_and_email

        resp = api_client.post(
            reverse("abos-offer-spot", kwargs={"pk": pending_entry.pk}),
            {},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        pending_entry.refresh_from_db()
        assert pending_entry.waiting_list_status == (
            Subscription.WaitingListStatus.SPOT_AVAILABLE
        )
        assert pending_entry.notification_token is not None
        reserve.assert_called_once()
        send_offer.assert_called_once()


def _cancel(api_client, member):
    return api_client.post(
        reverse("member-cancel", kwargs={"pk": member.pk}),
        {"effective_at": "2026-06-29"},
        format="json",
    )


def _leaving_member():
    member = MemberFactory(
        admin_confirmed=True,
        email="leaving.member@example.org",
        entry_date=datetime.date(2026, 1, 5),
    )
    CoopShareFactory(member=member)
    return member


@pytest.mark.django_db
class TestOfficeCancelEmail:
    def test_cancel_runs_while_on_without_the_email_or_its_stamp(
        self,
        api_client,
        onboarding_mode,
        email_config,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        member = _leaving_member()

        with django_capture_on_commit_callbacks(execute=True):
            resp = _cancel(api_client, member)

        assert resp.status_code == status.HTTP_200_OK, resp.data
        member.refresh_from_db()
        assert member.cancelled_at is not None
        assert member.cancellation_email_sent_at is None
        assert outbox == []
        assert _statuses("commissioning.member_cancelled") == ["suppressed"]

    def test_cancel_sends_the_email_while_off(
        self,
        api_client,
        onboarding_mode_off,
        email_config,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        member = _leaving_member()

        with django_capture_on_commit_callbacks(execute=True):
            resp = _cancel(api_client, member)

        assert resp.status_code == status.HTTP_200_OK, resp.data
        member.refresh_from_db()
        assert member.cancellation_email_sent_at is not None
        assert len(outbox) == 1
        assert _statuses("commissioning.member_cancelled") == ["sent"]


@pytest.mark.django_db
class TestRenewalDigestInWorker:
    def test_the_digest_is_suppressed_and_logged_at_info(
        self, tenant, onboarding_mode, email_config, outbox
    ):
        failed = [
            {
                "id": "abc",
                "label": "17",
                "reason": "no_variation",
                "member_id": "m1",
                "member_name": "Lukas Meyer",
                "member_number": "204",
            }
        ]

        with (
            mock.patch.object(tenant, "email", "office@example.org"),
            mock.patch.object(tasks, "ops_log") as ops_log,
            schema_context(tenant.schema_name),
        ):
            tasks._notify_office_of_renewal_failures(
                tenant, failed, datetime.date(2026, 7, 13)
            )

        ops_log.error.assert_not_called()
        ops_log.info.assert_called_once_with(
            "%s %s reason=onboarding_mode",
            "renewal.digest_failed",
            f"tenant={tenant.schema_name}",
        )
        assert outbox == []
        row = EmailLog.objects.get()
        assert (row.template, row.status, row.recipient) == (
            "commissioning.subscription_renewal_failures_office",
            "suppressed",
            "office@example.org",
        )
