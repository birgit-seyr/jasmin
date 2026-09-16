"""Service seams the onboarding-mode confirm paths use.

The viewsets decide from ``TenantSettings.onboarding_mode`` and pass explicit
arguments; these tests pin each argument's default (today's behaviour) and its
onboarding value: ``confirmation_datetime`` / ``assert_confirmation_not_after_exit``,
``notify`` on trial conversion and member cancellation,
``cancel_coop_shares_of_departed_member``, ``confirm_active_user`` on
``MemberService.link_to_user`` and ``confirm_active_users`` on the CSV import.
"""

from __future__ import annotations

import datetime
from unittest import mock

import pytest
import time_machine
from django.utils import timezone

from apps.commissioning.errors import (
    ConfirmationDateAfterExit,
    ConfirmationDateInFuture,
    ConfirmationDateRequiresOnboardingMode,
)
from apps.commissioning.models import Member
from apps.commissioning.services.data_import import import_rows_from_csv
from apps.commissioning.services.member_cancellation import (
    cancel_coop_shares_of_departed_member,
    cancel_member_with_coop_shares,
)
from apps.commissioning.services.member_service import MemberService
from apps.commissioning.services.onboarding_policy import (
    assert_confirmation_not_after_exit,
    confirmation_datetime,
)
from apps.commissioning.services.trial_conversion import (
    convert_trial_member_on_first_coop_share,
)
from apps.commissioning.tests.factories import (
    CoopShareFactory,
    JasminUserFactory,
    MemberFactory,
)

TODAY = datetime.date(2026, 7, 13)
EXIT_DATE = datetime.date(2024, 12, 31)


@pytest.fixture(autouse=True)
def _frozen_clock():
    # A Monday away from any year boundary.
    with time_machine.travel(datetime.datetime(2026, 7, 13, 12, 0), tick=False):
        yield


@pytest.fixture()
def send_email_mock():
    with mock.patch(
        "apps.shared.tenants.email_service.EmailService.send_email",
        return_value=True,
    ) as send_mock:
        yield send_mock


def _sent_slugs(send_mock) -> list[str]:
    return [call.kwargs["slug"] for call in send_mock.call_args_list]


class TestConfirmationDatetime:
    def test_no_date_gives_none_whatever_the_mode(self):
        assert confirmation_datetime(None, onboarding=False) is None
        assert confirmation_datetime(None, onboarding=True) is None

    def test_date_is_refused_while_off(self):
        with pytest.raises(ConfirmationDateRequiresOnboardingMode):
            confirmation_datetime(datetime.date(2019, 4, 1), onboarding=False)

    def test_future_date_is_refused(self):
        with pytest.raises(ConfirmationDateInFuture):
            confirmation_datetime(TODAY + datetime.timedelta(days=1), onboarding=True)

    @pytest.mark.parametrize(
        "day", [datetime.date(2019, 4, 1), datetime.date(2019, 10, 27), TODAY]
    )
    def test_date_becomes_local_noon(self, day):
        confirmed_at = confirmation_datetime(day, onboarding=True)
        assert confirmed_at is not None
        assert timezone.is_aware(confirmed_at)
        assert timezone.localtime(confirmed_at).time() == datetime.time(12, 0)
        assert timezone.localdate(confirmed_at) == day


@pytest.mark.django_db
class TestAssertConfirmationNotAfterExit:
    def test_member_who_has_not_left_passes(self, tenant):
        member = MemberFactory(cancelled_at=None)
        assert_confirmation_not_after_exit(member, confirmed_at=None)

    def test_confirmation_up_to_the_exit_day_passes(self, tenant):
        member = MemberFactory(
            entry_date=None,
            cancelled_at=timezone.now(),
            cancelled_effective_at=EXIT_DATE,
        )
        exit_noon = timezone.make_aware(datetime.datetime(2024, 12, 31, 12, 0))
        assert_confirmation_not_after_exit(member, confirmed_at=exit_noon)

    def test_confirmation_after_the_exit_day_is_refused(self, tenant):
        member = MemberFactory(
            entry_date=None,
            cancelled_at=timezone.now(),
            cancelled_effective_at=EXIT_DATE,
        )
        with pytest.raises(ConfirmationDateAfterExit):
            assert_confirmation_not_after_exit(
                member,
                confirmed_at=timezone.make_aware(datetime.datetime(2025, 1, 1, 12, 0)),
            )

    def test_without_a_date_today_is_compared(self, tenant):
        past_exit = MemberFactory(
            entry_date=None,
            cancelled_at=timezone.now(),
            cancelled_effective_at=EXIT_DATE,
        )
        with pytest.raises(ConfirmationDateAfterExit):
            assert_confirmation_not_after_exit(past_exit, confirmed_at=None)

        future_exit = MemberFactory(
            entry_date=None,
            cancelled_at=timezone.now(),
            cancelled_effective_at=TODAY + datetime.timedelta(weeks=8),
        )
        assert_confirmation_not_after_exit(future_exit, confirmed_at=None)


@pytest.mark.django_db
class TestTrialConversionNotify:
    def test_email_is_scheduled_by_default(
        self, tenant, send_email_mock, django_capture_on_commit_callbacks
    ):
        member = MemberFactory(is_trial=True, entry_date=None, member_number=None)
        CoopShareFactory(member=member, admin_confirmed=True)

        with django_capture_on_commit_callbacks(execute=True):
            assert convert_trial_member_on_first_coop_share(member) is True

        assert _sent_slugs(send_email_mock) == ["commissioning.trial_converted"]

    def test_notify_false_converts_without_email(
        self, tenant, send_email_mock, django_capture_on_commit_callbacks
    ):
        member = MemberFactory(is_trial=True, entry_date=None, member_number=None)
        CoopShareFactory(member=member, admin_confirmed=True)

        with django_capture_on_commit_callbacks(execute=True):
            assert (
                convert_trial_member_on_first_coop_share(member, notify=False) is True
            )

        member.refresh_from_db()
        assert member.is_trial is False
        assert member.entry_date == TODAY
        assert _sent_slugs(send_email_mock) == []


@pytest.mark.django_db
class TestCancelMemberNotify:
    def test_email_is_scheduled_by_default(
        self, tenant, send_email_mock, django_capture_on_commit_callbacks
    ):
        member = MemberFactory(admin_confirmed=True)

        with django_capture_on_commit_callbacks(execute=True):
            cancel_member_with_coop_shares(member, force=True)

        assert "commissioning.member_cancelled" in _sent_slugs(send_email_mock)

    def test_notify_false_cancels_without_email(
        self, tenant, send_email_mock, django_capture_on_commit_callbacks
    ):
        member = MemberFactory(admin_confirmed=True)
        share = CoopShareFactory(member=member, admin_confirmed=True)

        with django_capture_on_commit_callbacks(execute=True):
            cancel_member_with_coop_shares(member, force=True, notify=False)

        member.refresh_from_db()
        assert member.cancelled_at is not None
        assert member.cancellation_email_sent_at is None
        share.refresh_from_db()
        assert share.cancelled_at is not None
        assert _sent_slugs(send_email_mock) == []


@pytest.mark.django_db
class TestCancelCoopSharesOfDepartedMember:
    def test_no_op_for_a_member_who_has_not_left(self, tenant):
        member = MemberFactory(admin_confirmed=True)
        share = CoopShareFactory(member=member, admin_confirmed=True)

        cancel_coop_shares_of_departed_member(member)

        share.refresh_from_db()
        assert share.cancelled_at is None

    def test_open_shares_take_the_member_exit_stamps(self, tenant):
        leaver = JasminUserFactory(roles=["office"])
        cancelled_at = timezone.make_aware(datetime.datetime(2024, 11, 30, 9, 0))
        member = MemberFactory(
            admin_confirmed=True,
            entry_date=datetime.date(2019, 4, 1),
            cancelled_at=cancelled_at,
            cancelled_effective_at=EXIT_DATE,
            cancelled_by=leaver,
        )
        open_share = CoopShareFactory(member=member, admin_confirmed=True)
        earlier_cancel = timezone.make_aware(datetime.datetime(2022, 3, 1, 9, 0))
        downsized = CoopShareFactory(
            member=member,
            admin_confirmed=True,
            cancelled_at=earlier_cancel,
            cancelled_effective_at=datetime.date(2022, 3, 31),
        )

        cancel_coop_shares_of_departed_member(member)

        open_share.refresh_from_db()
        assert open_share.cancelled_at == cancelled_at
        assert open_share.cancelled_effective_at == EXIT_DATE
        assert open_share.cancelled_by_id == leaver.pk
        assert open_share.payback_due_date is not None
        assert open_share.payback_due_date >= EXIT_DATE
        downsized.refresh_from_db()
        assert downsized.cancelled_at == earlier_cancel
        member.refresh_from_db()
        assert member.cancelled_at == cancelled_at
        assert member.cancellation_email_sent_at is None


@pytest.mark.django_db
class TestLinkToUserConfirmActiveUser:
    def test_active_user_confirms_the_member_by_default(self, tenant):
        member = MemberFactory(admin_confirmed=False)
        login = JasminUserFactory()

        MemberService().link_to_user(member, login, admin_user=None, notify_user=False)

        member.refresh_from_db()
        assert member.user_id == login.pk
        assert member.admin_confirmed is True

    def test_confirm_active_user_false_only_links(self, tenant):
        member = MemberFactory(admin_confirmed=False)
        login = JasminUserFactory()

        MemberService().link_to_user(
            member,
            login,
            admin_user=None,
            notify_user=False,
            confirm_active_user=False,
        )

        member.refresh_from_db()
        assert member.user_id == login.pk
        assert member.admin_confirmed is False


@pytest.mark.django_db
class TestImportConfirmActiveUsers:
    @staticmethod
    def _csv(email: str) -> bytes:
        return (
            b"First,Last,Email\n"
            b"first_name,last_name,email\n"
            b"text,text,email\n"
            b"Imported,Member," + email.encode() + b"\n"
        )

    @pytest.fixture(autouse=True)
    def _no_coop_share_minimum(self, tenant):
        with mock.patch(
            "apps.commissioning.services.coop_share_service.CoopShareService"
            ".assert_member_total_within_bounds"
        ):
            yield

    def test_linked_active_user_is_confirmed_by_default(self, tenant):
        login = JasminUserFactory(email="import.default@example.com")

        result = import_rows_from_csv(
            "member", self._csv("import.default@example.com"), importing_user=login
        )

        assert result.successful == 1, result.errors
        member = Member.objects.get(email="import.default@example.com")
        assert member.user_id == login.pk
        assert member.admin_confirmed is True

    @pytest.mark.parametrize("dry_run", [False, True])
    def test_confirm_active_users_false_only_links(self, tenant, dry_run):
        login = JasminUserFactory(email="import.onboarding@example.com")

        with mock.patch(
            "apps.commissioning.models.Member.confirm", autospec=True
        ) as confirm_mock:
            result = import_rows_from_csv(
                "member",
                self._csv("import.onboarding@example.com"),
                importing_user=login,
                dry_run=dry_run,
                confirm_active_users=False,
            )

        assert result.successful == 1, result.errors
        confirm_mock.assert_not_called()
        if not dry_run:
            member = Member.objects.get(email="import.onboarding@example.com")
            assert member.user_id == login.pk
            assert member.admin_confirmed is False
