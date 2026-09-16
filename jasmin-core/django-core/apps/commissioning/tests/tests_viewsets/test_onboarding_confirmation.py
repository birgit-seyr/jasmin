"""Onboarding mode on the member and coop share confirm paths.

While ``TenantSettings.onboarding_mode`` is on, ``members/{id}/confirm`` and
``coop_shares/{id}/confirm`` accept an optional ``confirmed_at`` date, send no
email, and admit a member who has already left (their open coop shares are then
cancelled with the exit date). Office-created coop shares convert trial members
without the welcome email and take a historical ``paid_at``, and the CSV member
import links an active user without confirming the member. With the mode off
every one of these paths keeps its normal behaviour.
"""

from __future__ import annotations

import datetime
from unittest import mock

import pytest
import time_machine
from dateutil.relativedelta import relativedelta
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.commissioning.models import CoopShare, Member
from apps.commissioning.serializers import (
    CoopShareOnboardingSerializer,
    CoopShareSerializer,
)
from apps.commissioning.tests.factories import (
    CoopShareFactory,
    JasminUserFactory,
    MemberFactory,
)
from apps.commissioning.viewsets.members_viewsets import CoopShareViewSet
from apps.shared.tenants.models import TenantSettings

TODAY = datetime.date(2026, 7, 13)
HISTORICAL_CONFIRMATION = datetime.date(2019, 4, 1)
EXIT_DATE = datetime.date(2024, 12, 31)
RETENTION_MONTHS = 24


@pytest.fixture(autouse=True)
def _frozen_clock():
    # A Monday away from any year boundary.
    with time_machine.travel(datetime.datetime(2026, 7, 13, 12, 0), tick=False):
        yield


def _configure_settings(
    tenant, *, onboarding_mode: bool, min_number_coop_shares: int = 0
) -> None:
    """Open settings row with the mode, a coop share minimum (none by default,
    so members without shares can be confirmed) and a known payback
    retention."""
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
    row.min_number_coop_shares = min_number_coop_shares
    row.max_number_coop_shares = 100
    row.retention_period_cancelled_members_coop_shares_in_months = RETENTION_MONTHS
    row.save()


@pytest.fixture()
def onboarding_mode(tenant):
    _configure_settings(tenant, onboarding_mode=True)


@pytest.fixture()
def onboarding_mode_off(tenant):
    _configure_settings(tenant, onboarding_mode=False)


@pytest.fixture()
def send_email_mock():
    with mock.patch(
        "apps.shared.tenants.email_service.EmailService.send_email",
        return_value=True,
    ) as send_mock:
        yield send_mock


def _sent_slugs(send_mock) -> list[str]:
    return [call.kwargs["slug"] for call in send_mock.call_args_list]


def _noon(day: datetime.date) -> datetime.datetime:
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time(12, 0)))


def _member_confirm_url(member: Member) -> str:
    return reverse("member-confirm", kwargs={"pk": member.pk})


def _share_confirm_url(share: CoopShare) -> str:
    return reverse("coop_shares-confirm", kwargs={"pk": share.pk})


def _departed_member(**overrides) -> Member:
    """A member who left before Jasmin was used: exit stamps set, never
    confirmed, a login still waiting for approval."""
    fields = {
        "admin_confirmed": False,
        "is_trial": False,
        "entry_date": None,
        "member_number": None,
        "user": JasminUserFactory(account_status="pending_approval"),
        "cancelled_at": timezone.make_aware(datetime.datetime(2024, 11, 30, 9, 0)),
        "cancelled_effective_at": EXIT_DATE,
        "cancelled_by": JasminUserFactory(roles=["office"]),
    }
    fields.update(overrides)
    return MemberFactory(**fields)


@pytest.mark.django_db
class TestMemberConfirmFlagOff:
    def test_confirm_sends_the_approval_email(
        self,
        api_client,
        onboarding_mode_off,
        send_email_mock,
        django_capture_on_commit_callbacks,
    ):
        member = MemberFactory(admin_confirmed=False, is_trial=False, entry_date=None)
        CoopShareFactory(member=member, admin_confirmed=False)

        with django_capture_on_commit_callbacks(execute=True):
            resp = api_client.post(_member_confirm_url(member))

        assert resp.status_code == status.HTTP_200_OK, resp.data
        member.refresh_from_db()
        assert member.admin_confirmed is True
        assert timezone.localdate(member.admin_confirmed_at) == TODAY
        assert member.entry_date == TODAY
        assert "accounts.application_approved" in _sent_slugs(send_email_mock)

    def test_confirmed_at_is_refused(self, api_client, onboarding_mode_off):
        member = MemberFactory(admin_confirmed=False)

        resp = api_client.post(
            _member_confirm_url(member),
            {"confirmed_at": HISTORICAL_CONFIRMATION.isoformat()},
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "member.confirmation_date_requires_onboarding_mode"
        member.refresh_from_db()
        assert member.admin_confirmed is False

    def test_departed_member_is_still_refused(self, api_client, onboarding_mode_off):
        member = _departed_member()

        resp = api_client.post(_member_confirm_url(member))

        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data["code"] == "member.already_cancelled"
        member.refresh_from_db()
        assert member.admin_confirmed is False


@pytest.mark.django_db
class TestMemberConfirmFlagOn:
    def test_confirmed_at_dates_confirmation_entry_and_pending_shares(
        self,
        api_client,
        onboarding_mode,
        send_email_mock,
        django_capture_on_commit_callbacks,
    ):
        member = MemberFactory(
            admin_confirmed=False, is_trial=False, entry_date=None, member_number=None
        )
        share = CoopShareFactory(member=member, admin_confirmed=False)

        with django_capture_on_commit_callbacks(execute=True):
            resp = api_client.post(
                _member_confirm_url(member),
                {"confirmed_at": HISTORICAL_CONFIRMATION.isoformat()},
                format="json",
            )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        member.refresh_from_db()
        assert member.admin_confirmed is True
        assert member.admin_confirmed_at == _noon(HISTORICAL_CONFIRMATION)
        assert member.entry_date == HISTORICAL_CONFIRMATION
        assert member.member_number is not None
        share.refresh_from_db()
        assert share.admin_confirmed is True
        assert share.admin_confirmed_at == _noon(HISTORICAL_CONFIRMATION)
        assert _sent_slugs(send_email_mock) == []

    def test_entry_date_already_set_is_kept(self, api_client, onboarding_mode):
        typed_entry = datetime.date(2018, 1, 15)
        member = MemberFactory(admin_confirmed=False, entry_date=typed_entry)

        resp = api_client.post(
            _member_confirm_url(member),
            {"confirmed_at": HISTORICAL_CONFIRMATION.isoformat()},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        member.refresh_from_db()
        assert member.entry_date == typed_entry
        assert member.admin_confirmed_at == _noon(HISTORICAL_CONFIRMATION)

    def test_without_a_date_confirms_now_and_sends_no_email(
        self,
        api_client,
        onboarding_mode,
        send_email_mock,
        django_capture_on_commit_callbacks,
    ):
        member = MemberFactory(admin_confirmed=False, is_trial=False, entry_date=None)

        with django_capture_on_commit_callbacks(execute=True):
            resp = api_client.post(_member_confirm_url(member))

        assert resp.status_code == status.HTTP_200_OK, resp.data
        member.refresh_from_db()
        assert timezone.localdate(member.admin_confirmed_at) == TODAY
        assert member.entry_date == TODAY
        assert _sent_slugs(send_email_mock) == []

    def test_trial_member_converts_on_the_date_without_emails(
        self,
        api_client,
        onboarding_mode,
        send_email_mock,
        django_capture_on_commit_callbacks,
    ):
        member = MemberFactory(
            admin_confirmed=False, is_trial=True, entry_date=None, member_number=None
        )
        CoopShareFactory(member=member, admin_confirmed=False)

        with django_capture_on_commit_callbacks(execute=True):
            resp = api_client.post(
                _member_confirm_url(member),
                {"confirmed_at": HISTORICAL_CONFIRMATION.isoformat()},
                format="json",
            )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        member.refresh_from_db()
        assert member.is_trial is False
        assert member.trial_converted_at is not None
        assert member.entry_date == HISTORICAL_CONFIRMATION
        assert _sent_slugs(send_email_mock) == []

    def test_today_is_accepted(self, api_client, onboarding_mode):
        member = MemberFactory(admin_confirmed=False, entry_date=None)

        resp = api_client.post(
            _member_confirm_url(member),
            {"confirmed_at": TODAY.isoformat()},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data

    def test_future_date_is_refused(self, api_client, onboarding_mode):
        member = MemberFactory(admin_confirmed=False, entry_date=None)

        resp = api_client.post(
            _member_confirm_url(member),
            {"confirmed_at": (TODAY + datetime.timedelta(days=1)).isoformat()},
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "member.confirmation_date_in_future"
        member.refresh_from_db()
        assert member.admin_confirmed is False

    def test_malformed_date_is_refused(self, api_client, onboarding_mode):
        member = MemberFactory(admin_confirmed=False)

        resp = api_client.post(
            _member_confirm_url(member), {"confirmed_at": "01.04.2019"}, format="json"
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        member.refresh_from_db()
        assert member.admin_confirmed is False


@pytest.mark.django_db
class TestAdmitAndExit:
    def test_confirms_then_cancels_open_shares_with_the_exit_date(
        self,
        api_client,
        onboarding_mode,
        send_email_mock,
        django_capture_on_commit_callbacks,
    ):
        member = _departed_member()
        shares = [
            CoopShareFactory(member=member, admin_confirmed=False) for _ in range(2)
        ]
        exit_stamps = (
            member.cancelled_at,
            member.cancelled_effective_at,
            member.cancelled_by_id,
        )

        with django_capture_on_commit_callbacks(execute=True):
            resp = api_client.post(
                _member_confirm_url(member),
                {"confirmed_at": HISTORICAL_CONFIRMATION.isoformat()},
                format="json",
            )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        member.refresh_from_db()
        assert member.admin_confirmed is True
        assert member.entry_date == HISTORICAL_CONFIRMATION
        assert (
            member.cancelled_at,
            member.cancelled_effective_at,
            member.cancelled_by_id,
        ) == exit_stamps
        assert member.cancellation_email_sent_at is None
        for share in shares:
            share.refresh_from_db()
            assert share.admin_confirmed is True
            assert share.admin_confirmed_at == _noon(HISTORICAL_CONFIRMATION)
            assert share.cancelled_at == member.cancelled_at
            assert share.cancelled_effective_at == EXIT_DATE
            assert share.cancelled_by_id == member.cancelled_by_id
            assert share.payback_due_date == EXIT_DATE + relativedelta(
                months=RETENTION_MONTHS
            )
        assert _sent_slugs(send_email_mock) == []

    def test_pending_login_is_not_activated(self, api_client, onboarding_mode):
        member = _departed_member()

        resp = api_client.post(
            _member_confirm_url(member),
            {"confirmed_at": HISTORICAL_CONFIRMATION.isoformat()},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        member.user.refresh_from_db()
        assert member.user.account_status == "pending_approval"

    def test_exit_day_itself_is_accepted(self, api_client, onboarding_mode):
        member = _departed_member()

        resp = api_client.post(
            _member_confirm_url(member),
            {"confirmed_at": EXIT_DATE.isoformat()},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        member.refresh_from_db()
        assert member.entry_date == EXIT_DATE

    def test_date_after_exit_is_refused(self, api_client, onboarding_mode):
        member = _departed_member()
        share = CoopShareFactory(member=member, admin_confirmed=False)

        resp = api_client.post(
            _member_confirm_url(member),
            {"confirmed_at": (EXIT_DATE + datetime.timedelta(days=1)).isoformat()},
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "member.confirmation_date_after_exit"
        assert resp.data["details"] == {"exit_date": EXIT_DATE.isoformat()}
        member.refresh_from_db()
        assert member.admin_confirmed is False
        share.refresh_from_db()
        assert share.admin_confirmed is False
        assert share.cancelled_at is None

    def test_without_a_date_a_past_exit_is_refused(self, api_client, onboarding_mode):
        member = _departed_member()

        resp = api_client.post(_member_confirm_url(member))

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "member.confirmation_date_after_exit"
        member.refresh_from_db()
        assert member.admin_confirmed is False


@pytest.mark.django_db
class TestCoopShareConfirm:
    def test_confirmed_at_is_refused_while_off(self, api_client, onboarding_mode_off):
        share = CoopShareFactory(
            member=MemberFactory(admin_confirmed=True), admin_confirmed=False
        )

        resp = api_client.post(
            _share_confirm_url(share),
            {"confirmed_at": HISTORICAL_CONFIRMATION.isoformat()},
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "member.confirmation_date_requires_onboarding_mode"
        share.refresh_from_db()
        assert share.admin_confirmed is False

    def test_member_cascade_sends_the_approval_email_while_off(
        self,
        api_client,
        onboarding_mode_off,
        send_email_mock,
        django_capture_on_commit_callbacks,
    ):
        member = MemberFactory(admin_confirmed=False, is_trial=False)
        share = CoopShareFactory(member=member, admin_confirmed=False)

        with django_capture_on_commit_callbacks(execute=True):
            resp = api_client.post(_share_confirm_url(share))

        assert resp.status_code == status.HTTP_200_OK, resp.data
        member.refresh_from_db()
        assert member.admin_confirmed is True
        assert "accounts.application_approved" in _sent_slugs(send_email_mock)

    def test_trial_conversion_email_while_off(
        self,
        api_client,
        onboarding_mode_off,
        send_email_mock,
        django_capture_on_commit_callbacks,
    ):
        member = MemberFactory(admin_confirmed=True, is_trial=True, entry_date=None)
        share = CoopShareFactory(member=member, admin_confirmed=False)

        with django_capture_on_commit_callbacks(execute=True):
            resp = api_client.post(_share_confirm_url(share))

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert "commissioning.trial_converted" in _sent_slugs(send_email_mock)

    def test_confirmed_at_dates_the_share(
        self,
        api_client,
        onboarding_mode,
        send_email_mock,
        django_capture_on_commit_callbacks,
    ):
        share = CoopShareFactory(
            member=MemberFactory(admin_confirmed=True), admin_confirmed=False
        )

        with django_capture_on_commit_callbacks(execute=True):
            resp = api_client.post(
                _share_confirm_url(share),
                {"confirmed_at": HISTORICAL_CONFIRMATION.isoformat()},
                format="json",
            )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        share.refresh_from_db()
        assert share.admin_confirmed is True
        assert share.admin_confirmed_at == _noon(HISTORICAL_CONFIRMATION)
        assert _sent_slugs(send_email_mock) == []

    def test_future_date_is_refused(self, api_client, onboarding_mode):
        share = CoopShareFactory(
            member=MemberFactory(admin_confirmed=True), admin_confirmed=False
        )

        resp = api_client.post(
            _share_confirm_url(share),
            {"confirmed_at": (TODAY + datetime.timedelta(days=1)).isoformat()},
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "member.confirmation_date_in_future"
        share.refresh_from_db()
        assert share.admin_confirmed is False

    def test_cascade_admits_a_trial_member_on_the_date_without_emails(
        self,
        api_client,
        onboarding_mode,
        send_email_mock,
        django_capture_on_commit_callbacks,
    ):
        member = MemberFactory(
            admin_confirmed=False, is_trial=True, entry_date=None, member_number=None
        )
        share = CoopShareFactory(member=member, admin_confirmed=False)

        with django_capture_on_commit_callbacks(execute=True):
            resp = api_client.post(
                _share_confirm_url(share),
                {"confirmed_at": HISTORICAL_CONFIRMATION.isoformat()},
                format="json",
            )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        member.refresh_from_db()
        assert member.admin_confirmed is True
        assert member.is_trial is False
        assert member.entry_date == HISTORICAL_CONFIRMATION
        assert member.admin_confirmed_at == _noon(HISTORICAL_CONFIRMATION)
        assert _sent_slugs(send_email_mock) == []

    def test_share_of_an_admitted_departed_member_is_confirmed_then_cancelled(
        self,
        api_client,
        onboarding_mode,
        send_email_mock,
        django_capture_on_commit_callbacks,
    ):
        member = _departed_member(
            admin_confirmed=True, entry_date=datetime.date(2019, 1, 7)
        )
        share = CoopShareFactory(member=member, admin_confirmed=False)

        with django_capture_on_commit_callbacks(execute=True):
            resp = api_client.post(
                _share_confirm_url(share),
                {"confirmed_at": HISTORICAL_CONFIRMATION.isoformat()},
                format="json",
            )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["admin_confirmed"] is True
        assert resp.data["cancelled_effective_at"] == EXIT_DATE.isoformat()
        share.refresh_from_db()
        assert share.cancelled_at == member.cancelled_at
        assert share.payback_due_date == EXIT_DATE + relativedelta(
            months=RETENTION_MONTHS
        )
        assert _sent_slugs(send_email_mock) == []

    def test_share_of_a_departed_applicant_admits_and_cancels(
        self, api_client, onboarding_mode
    ):
        member = _departed_member()
        share = CoopShareFactory(member=member, admin_confirmed=False)
        sibling = CoopShareFactory(member=member, admin_confirmed=False)

        resp = api_client.post(
            _share_confirm_url(share),
            {"confirmed_at": HISTORICAL_CONFIRMATION.isoformat()},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        member.refresh_from_db()
        assert member.admin_confirmed is True
        assert member.entry_date == HISTORICAL_CONFIRMATION
        member.user.refresh_from_db()
        assert member.user.account_status == "pending_approval"
        for row in (share, sibling):
            row.refresh_from_db()
            assert row.admin_confirmed is True
            assert row.cancelled_effective_at == EXIT_DATE

    def test_share_of_a_departed_member_is_refused_after_exit(
        self, api_client, onboarding_mode
    ):
        member = _departed_member(admin_confirmed=True, entry_date=None)
        share = CoopShareFactory(member=member, admin_confirmed=False)

        resp = api_client.post(_share_confirm_url(share))

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "member.confirmation_date_after_exit"
        share.refresh_from_db()
        assert share.admin_confirmed is False


EARLIER_CONFIRMATION = timezone.make_aware(datetime.datetime(2023, 5, 2, 9, 0))


@pytest.mark.django_db
class TestCoopShareConfirmOnlyPendingWhileOn:
    def test_confirmed_share_is_restamped_while_off(
        self, api_client, user, onboarding_mode_off
    ):
        share = CoopShareFactory(
            member=MemberFactory(admin_confirmed=True),
            admin_confirmed=True,
            admin_confirmed_at=EARLIER_CONFIRMATION,
            admin_confirmed_by=JasminUserFactory(roles=["office"]),
        )

        resp = api_client.post(_share_confirm_url(share))

        assert resp.status_code == status.HTTP_200_OK, resp.data
        share.refresh_from_db()
        assert share.admin_confirmed_at == timezone.now()
        assert share.admin_confirmed_by_id == user.pk

    def test_confirmed_cancelled_share_of_a_departed_member_is_refused(
        self, api_client, onboarding_mode
    ):
        member = _departed_member(
            admin_confirmed=True, entry_date=datetime.date(2019, 1, 7)
        )
        original_confirmer = JasminUserFactory(roles=["office"])
        share = CoopShareFactory(
            member=member,
            admin_confirmed=True,
            admin_confirmed_at=EARLIER_CONFIRMATION,
            admin_confirmed_by=original_confirmer,
            cancelled_at=member.cancelled_at,
            cancelled_effective_at=EXIT_DATE,
            cancelled_by=member.cancelled_by,
        )

        resp = api_client.post(
            _share_confirm_url(share),
            {"confirmed_at": "2021-01-04"},
            format="json",
        )

        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data["code"] == "coop_share.not_pending"
        share.refresh_from_db()
        assert share.admin_confirmed_at == EARLIER_CONFIRMATION
        assert share.admin_confirmed_by_id == original_confirmer.pk

    def test_confirmed_share_of_an_admitted_member_is_refused(
        self, api_client, onboarding_mode
    ):
        share = CoopShareFactory(
            member=MemberFactory(admin_confirmed=True),
            admin_confirmed=True,
            admin_confirmed_at=EARLIER_CONFIRMATION,
        )

        resp = api_client.post(_share_confirm_url(share))

        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data["code"] == "coop_share.not_pending"
        share.refresh_from_db()
        assert share.admin_confirmed_at == EARLIER_CONFIRMATION

    def test_cancelled_unconfirmed_share_is_refused(self, api_client, onboarding_mode):
        share = CoopShareFactory(
            member=MemberFactory(admin_confirmed=True),
            admin_confirmed=False,
            cancelled_at=timezone.make_aware(datetime.datetime(2026, 6, 1, 9, 0)),
            cancelled_effective_at=datetime.date(2026, 6, 30),
        )

        resp = api_client.post(
            _share_confirm_url(share),
            {"confirmed_at": HISTORICAL_CONFIRMATION.isoformat()},
            format="json",
        )

        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data["code"] == "coop_share.not_pending"
        share.refresh_from_db()
        assert share.admin_confirmed is False


@pytest.mark.django_db
class TestCoopShareConfirmBelowMinimum:
    @pytest.fixture()
    def onboarding_mode_min_two(self, tenant):
        _configure_settings(tenant, onboarding_mode=True, min_number_coop_shares=2)

    @pytest.fixture()
    def onboarding_mode_off_min_two(self, tenant):
        _configure_settings(tenant, onboarding_mode=False, min_number_coop_shares=2)

    def test_share_of_a_departed_member_who_cant_be_admitted_is_refused(
        self, api_client, onboarding_mode_min_two, send_email_mock
    ):
        member = _departed_member()
        share = CoopShareFactory(
            member=member, admin_confirmed=False, amount_of_coop_shares=1
        )

        resp = api_client.post(
            _share_confirm_url(share),
            {"confirmed_at": HISTORICAL_CONFIRMATION.isoformat()},
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"].startswith("member.coop_shares_out_of_range")
        share.refresh_from_db()
        assert share.admin_confirmed is False
        assert share.admin_confirmed_at is None
        assert share.cancelled_at is None
        assert share.payback_due_date is None
        member.refresh_from_db()
        assert member.admin_confirmed is False
        assert _sent_slugs(send_email_mock) == []

    def test_share_of_a_pending_member_below_minimum_is_still_confirmed(
        self, api_client, onboarding_mode_min_two
    ):
        member = MemberFactory(admin_confirmed=False, is_trial=False)
        share = CoopShareFactory(
            member=member, admin_confirmed=False, amount_of_coop_shares=1
        )

        resp = api_client.post(
            _share_confirm_url(share),
            {"confirmed_at": HISTORICAL_CONFIRMATION.isoformat()},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        share.refresh_from_db()
        assert share.admin_confirmed is True
        member.refresh_from_db()
        assert member.admin_confirmed is False

    def test_share_of_a_departed_member_is_refused_while_off(
        self, api_client, onboarding_mode_off_min_two
    ):
        member = _departed_member()
        share = CoopShareFactory(
            member=member, admin_confirmed=False, amount_of_coop_shares=1
        )

        resp = api_client.post(_share_confirm_url(share))

        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data["code"] == "member.already_cancelled"
        share.refresh_from_db()
        assert share.admin_confirmed is False


@pytest.mark.django_db
class TestCoopShareCreateAndPaidAt:
    URL = reverse("coop_shares-list")

    @staticmethod
    def _payload(member: Member, **overrides) -> dict:
        payload = {
            "member": str(member.id),
            "amount_of_coop_shares": 1,
            "value_one_coop_share": 100,
        }
        payload.update(overrides)
        return payload

    def test_trial_conversion_email_while_off(
        self,
        api_client,
        onboarding_mode_off,
        send_email_mock,
        django_capture_on_commit_callbacks,
    ):
        member = MemberFactory(is_trial=True, entry_date=None)

        with django_capture_on_commit_callbacks(execute=True):
            resp = api_client.post(self.URL, self._payload(member), format="json")

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert "commissioning.trial_converted" in _sent_slugs(send_email_mock)

    def test_no_trial_conversion_email_while_on(
        self,
        api_client,
        onboarding_mode,
        send_email_mock,
        django_capture_on_commit_callbacks,
    ):
        member = MemberFactory(is_trial=True, entry_date=None)

        with django_capture_on_commit_callbacks(execute=True):
            resp = api_client.post(self.URL, self._payload(member), format="json")

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert resp.data["admin_confirmed"] is True
        member.refresh_from_db()
        assert member.is_trial is False
        assert _sent_slugs(send_email_mock) == []

    def test_paid_at_is_dropped_on_create_while_off(
        self, api_client, onboarding_mode_off
    ):
        member = MemberFactory()

        resp = api_client.post(
            self.URL,
            self._payload(member, paid_at=HISTORICAL_CONFIRMATION.isoformat()),
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert CoopShare.objects.get(pk=resp.data["id"]).paid_at is None

    def test_paid_at_is_stored_as_local_midnight_on_create_while_on(
        self, api_client, onboarding_mode
    ):
        member = MemberFactory()

        resp = api_client.post(
            self.URL,
            self._payload(member, paid_at=HISTORICAL_CONFIRMATION.isoformat()),
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        paid_at = CoopShare.objects.get(pk=resp.data["id"]).paid_at
        assert paid_at == timezone.make_aware(
            datetime.datetime.combine(HISTORICAL_CONFIRMATION, datetime.time.min)
        )

    def test_paid_at_is_dropped_on_patch_while_off(
        self, api_client, onboarding_mode_off
    ):
        share = CoopShareFactory(
            member=MemberFactory(admin_confirmed=True), admin_confirmed=True
        )

        resp = api_client.patch(
            reverse("coop_shares-detail", kwargs={"pk": share.pk}),
            {"paid_at": HISTORICAL_CONFIRMATION.isoformat()},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        share.refresh_from_db()
        assert share.paid_at is None

    def test_paid_at_datetime_is_normalised_on_patch_while_on(
        self, api_client, onboarding_mode
    ):
        share = CoopShareFactory(
            member=MemberFactory(admin_confirmed=True), admin_confirmed=True
        )

        resp = api_client.patch(
            reverse("coop_shares-detail", kwargs={"pk": share.pk}),
            {"paid_at": "2020-02-03T15:30:00+01:00"},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        share.refresh_from_db()
        assert share.paid_at == timezone.make_aware(datetime.datetime(2020, 2, 3))


@pytest.mark.django_db
class TestCoopShareSerializerSelection:
    @staticmethod
    def _view(action: str, *, schema: bool = False) -> CoopShareViewSet:
        view = CoopShareViewSet()
        view.action = action
        view.request = mock.Mock(user=None)
        if schema:
            view.swagger_fake_view = True
        return view

    @pytest.mark.parametrize("action", ["create", "update", "partial_update"])
    def test_writes_use_onboarding_serializer_when_on(self, onboarding_mode, action):
        assert (
            self._view(action).get_serializer_class() is CoopShareOnboardingSerializer
        )

    @pytest.mark.parametrize("action", ["create", "update", "partial_update"])
    def test_writes_use_coop_share_serializer_when_off(
        self, onboarding_mode_off, action
    ):
        assert self._view(action).get_serializer_class() is CoopShareSerializer

    @pytest.mark.parametrize("action", ["list", "retrieve", "confirm"])
    def test_other_actions_keep_coop_share_serializer_when_on(
        self, onboarding_mode, action
    ):
        assert self._view(action).get_serializer_class() is CoopShareSerializer

    def test_schema_generation_keeps_coop_share_serializer(self, onboarding_mode):
        view = self._view("partial_update", schema=True)
        assert view.get_serializer_class() is CoopShareSerializer


@pytest.mark.django_db
class TestMemberImportLinkToActiveUser:
    URL = reverse("data_import")

    def _upload(self, api_client, email: str):
        csv_bytes = (
            b"First,Last,Email\n"
            b"first_name,last_name,email\n"
            b"text,text,email\n"
            b"Linked,Member," + email.encode() + b"\n"
        )
        return api_client.post(
            self.URL,
            {
                "model_name": "member",
                "file": SimpleUploadedFile(
                    "members.csv", csv_bytes, content_type="text/csv"
                ),
            },
            format="multipart",
        )

    def test_linked_member_is_confirmed_while_off(
        self, api_client, onboarding_mode_off
    ):
        login = JasminUserFactory(email="linked.off@example.com")

        resp = self._upload(api_client, "linked.off@example.com")

        assert resp.status_code == status.HTTP_200_OK, resp.content
        assert resp.json()["successful"] == 1, resp.json()["errors"]
        member = Member.objects.get(email="linked.off@example.com")
        assert member.user_id == login.pk
        assert member.admin_confirmed is True

    def test_linked_member_stays_unconfirmed_while_on(
        self, api_client, onboarding_mode
    ):
        login = JasminUserFactory(email="linked.on@example.com")

        resp = self._upload(api_client, "linked.on@example.com")

        assert resp.status_code == status.HTTP_200_OK, resp.content
        assert resp.json()["successful"] == 1, resp.json()["errors"]
        member = Member.objects.get(email="linked.on@example.com")
        assert member.user_id == login.pk
        assert member.admin_confirmed is False
        assert member.entry_date is None
