"""Tests for the "non-trial admin-confirmed member must hold shares in
``[min, max]``" rule.

Covers two service-layer entry points:

  1. ``CoopShareService.assert_within_min_max`` — fires on CoopShare
     save. Must SKIP trial members and not-yet-confirmed applicants so
     the office can build up their position incrementally. Must
     enforce once they're admitted as full Mitglieder.
  2. ``MemberService.confirm_and_notify`` — must REFUSE to admit a
     non-trial applicant whose total coop shares don't satisfy the
     window. Previously silent: a member with zero shares could be
     confirmed.

Tests deliberately set ``allow_pending_application_email=False``
where notification side-effects would pollute the assertion. Email
suites cover the on_commit dispatch separately.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.commissioning.errors import MemberCoopSharesOutOfRange
from apps.commissioning.models import CoopShare
from apps.commissioning.services.coop_share_service import CoopShareService
from apps.commissioning.services.member_service import MemberService
from apps.commissioning.tests.factories import (
    CoopShareFactory,
    JasminUserFactory,
    MemberFactory,
)
from apps.shared.tenants.models import TenantSettings


def _settings(tenant, **kwargs) -> TenantSettings:
    return TenantSettings.objects.create(
        tenant=tenant,
        valid_from=timezone.now() - datetime.timedelta(seconds=1),
        **kwargs,
    )


@pytest.mark.django_db
class TestAssertWithinMinMaxScope:
    """Verify the new exemption logic on the existing per-share guard."""

    def test_trial_member_can_create_share_below_minimum(self, tenant):
        _settings(tenant, min_number_coop_shares=3, max_number_coop_shares=10)
        member = MemberFactory(is_trial=True, admin_confirmed=False)
        # 1 share is well below min=3 — exemption must apply.
        CoopShareService.assert_within_min_max(
            member=member, new_amount=Decimal(1)
        )  # no raise

    def test_pending_applicant_can_create_share_below_minimum(self, tenant):
        _settings(tenant, min_number_coop_shares=3, max_number_coop_shares=10)
        member = MemberFactory(is_trial=False, admin_confirmed=False)
        CoopShareService.assert_within_min_max(
            member=member, new_amount=Decimal(1)
        )  # no raise

    def test_confirmed_non_trial_below_minimum_raises(self, tenant):
        _settings(tenant, min_number_coop_shares=3, max_number_coop_shares=10)
        member = MemberFactory(is_trial=False, admin_confirmed=True)
        with pytest.raises(MemberCoopSharesOutOfRange):
            CoopShareService.assert_within_min_max(member=member, new_amount=Decimal(1))

    def test_confirmed_non_trial_above_maximum_raises(self, tenant):
        _settings(tenant, min_number_coop_shares=3, max_number_coop_shares=10)
        member = MemberFactory(is_trial=False, admin_confirmed=True)
        with pytest.raises(MemberCoopSharesOutOfRange):
            CoopShareService.assert_within_min_max(
                member=member, new_amount=Decimal(11)
            )

    def test_confirmed_non_trial_within_range_is_ok(self, tenant):
        _settings(tenant, min_number_coop_shares=3, max_number_coop_shares=10)
        member = MemberFactory(is_trial=False, admin_confirmed=True)
        CoopShareService.assert_within_min_max(
            member=member, new_amount=Decimal(5)
        )  # no raise


@pytest.mark.django_db
class TestConfirmTimeBoundsCheck:
    """``MemberService.confirm_and_notify`` must refuse a non-trial
    member whose CURRENT total shares are out of range."""

    def test_confirm_refuses_member_with_no_shares(self, tenant):
        _settings(tenant, min_number_coop_shares=3, max_number_coop_shares=10)
        member = MemberFactory(is_trial=False, admin_confirmed=False)
        admin = JasminUserFactory(roles=["office"])
        with pytest.raises(MemberCoopSharesOutOfRange) as exc:
            MemberService().confirm_and_notify(member, admin_user=admin)
        assert exc.value.code == "member.coop_shares_out_of_range"
        member.refresh_from_db()
        assert member.admin_confirmed is False, (
            "Confirmation must NOT have flipped — service should abort "
            "before mutating state."
        )

    def test_confirm_refuses_member_below_minimum(self, tenant):
        _settings(tenant, min_number_coop_shares=3, max_number_coop_shares=10)
        member = MemberFactory(is_trial=False, admin_confirmed=False)
        # Bypass clean() — the existing per-share guard would also block
        # this if we went through model save() under the new rules.
        CoopShare.objects.create(
            member=member,
            amount_of_coop_shares=Decimal(1),
            value_one_coop_share=100,
        )
        admin = JasminUserFactory(roles=["office"])
        with pytest.raises(MemberCoopSharesOutOfRange):
            MemberService().confirm_and_notify(member, admin_user=admin)

    def test_confirm_refuses_member_above_maximum(self, tenant):
        _settings(tenant, min_number_coop_shares=3, max_number_coop_shares=10)
        member = MemberFactory(is_trial=False, admin_confirmed=False)
        CoopShare.objects.create(
            member=member,
            amount_of_coop_shares=Decimal(11),
            value_one_coop_share=100,
        )
        admin = JasminUserFactory(roles=["office"])
        with pytest.raises(MemberCoopSharesOutOfRange):
            MemberService().confirm_and_notify(member, admin_user=admin)

    def test_confirm_succeeds_when_total_in_range(self, tenant):
        _settings(tenant, min_number_coop_shares=3, max_number_coop_shares=10)
        member = MemberFactory(is_trial=False, admin_confirmed=False)
        CoopShare.objects.create(
            member=member,
            amount_of_coop_shares=Decimal(5),
            value_one_coop_share=100,
        )
        admin = JasminUserFactory(roles=["office"])
        MemberService().confirm_and_notify(member, admin_user=admin)
        member.refresh_from_db()
        assert member.admin_confirmed is True

    def test_confirm_trial_member_skips_bounds_check(self, tenant):
        """Trial members ride straight through — the bounds rule kicks
        in when ``is_trial`` flips later, not at admin-confirm."""
        _settings(tenant, min_number_coop_shares=3, max_number_coop_shares=10)
        member = MemberFactory(is_trial=True, admin_confirmed=False)
        # No coop shares at all — for a real (non-trial) member this
        # would be blocked, but trial members are exempt.
        admin = JasminUserFactory(roles=["office"])
        MemberService().confirm_and_notify(member, admin_user=admin)
        member.refresh_from_db()
        assert member.admin_confirmed is True
        assert member.is_trial is True  # untouched by confirm

    def test_no_settings_no_check(self, tenant):
        """If the tenant has no current TenantSettings row, the rule is
        a no-op — same fail-open posture as the per-share guard."""
        member = MemberFactory(is_trial=False, admin_confirmed=False)
        admin = JasminUserFactory(roles=["office"])
        # Does not raise even though there are no shares.
        MemberService().confirm_and_notify(member, admin_user=admin)
        member.refresh_from_db()
        assert member.admin_confirmed is True


@pytest.mark.django_db
class TestTrialConversionBoundsCheck:
    """A trial member is converted to full when they acquire CONFIRMED equity
    (``CoopShare.confirm``) — that is the moment the GenG min/max window starts
    applying (it exempts trial members). The conversion re-checks bounds, and a
    violation rolls back the confirmation + conversion (leaving the share a
    pending draft). A still-pending (unconfirmed) share never converts."""

    def test_first_share_below_minimum_rolls_back(self, tenant):
        _settings(tenant, min_number_coop_shares=3, max_number_coop_shares=10)
        member = MemberFactory(is_trial=True, member_number=None, entry_date=None)

        share = CoopShare.objects.create(
            member=member,
            amount_of_coop_shares=Decimal(1),
            value_one_coop_share=100,
        )
        # Conversion (+ its bounds check) fires on CONFIRMATION.
        with pytest.raises(MemberCoopSharesOutOfRange):
            share.confirm(admin_user=None)

        member.refresh_from_db()
        share.refresh_from_db()
        # Conversion rolled back: still trial, no number/entry stamped.
        assert member.is_trial is True
        assert member.member_number is None
        assert member.entry_date is None
        # The share stays a pending (unconfirmed) draft.
        assert share.admin_confirmed is False

    def test_first_share_above_maximum_rolls_back(self, tenant):
        _settings(tenant, min_number_coop_shares=3, max_number_coop_shares=10)
        member = MemberFactory(is_trial=True, member_number=None)

        share = CoopShare.objects.create(
            member=member,
            amount_of_coop_shares=Decimal(11),
            value_one_coop_share=100,
        )
        with pytest.raises(MemberCoopSharesOutOfRange):
            share.confirm(admin_user=None)

        member.refresh_from_db()
        share.refresh_from_db()
        assert member.is_trial is True
        assert share.admin_confirmed is False

    def test_first_share_within_range_converts(self, tenant):
        _settings(tenant, min_number_coop_shares=3, max_number_coop_shares=10)
        member = MemberFactory(is_trial=True, member_number=None, entry_date=None)

        CoopShare.objects.create(
            member=member,
            amount_of_coop_shares=Decimal(5),
            value_one_coop_share=100,
        ).confirm(admin_user=None)

        member.refresh_from_db()
        assert member.is_trial is False
        assert member.member_number is not None
        assert CoopShare.objects.filter(member=member).count() == 1

    def test_no_settings_first_share_converts_below_minimum(self, tenant):
        """No TenantSettings row → bounds rule no-ops (fail-open); confirming
        the first share still converts the trial member."""
        member = MemberFactory(is_trial=True, member_number=None)

        CoopShare.objects.create(
            member=member,
            amount_of_coop_shares=Decimal(1),
            value_one_coop_share=100,
        ).confirm(admin_user=None)

        member.refresh_from_db()
        assert member.is_trial is False
        assert CoopShare.objects.filter(member=member).count() == 1

    def test_pending_sibling_share_does_not_count_toward_conversion(self, tenant):
        """BIZ-3: confirming a below-minimum share does NOT convert the trial
        member just because a PENDING sibling would top up the total — only
        confirmed equity counts, so the member isn't admitted on shares that can
        later be rejected/deleted (leaving a full member below the minimum)."""
        _settings(tenant, min_number_coop_shares=5, max_number_coop_shares=10)
        member = MemberFactory(is_trial=True, member_number=None, entry_date=None)
        # A pending sibling that would (wrongly) top the total to 5.
        CoopShare.objects.create(
            member=member,
            amount_of_coop_shares=Decimal(4),
            value_one_coop_share=100,
        )
        small = CoopShare.objects.create(
            member=member,
            amount_of_coop_shares=Decimal(1),
            value_one_coop_share=100,
        )

        # Only 1 confirmed share < min 5 → conversion rolls back.
        with pytest.raises(MemberCoopSharesOutOfRange):
            small.confirm(admin_user=None)

        member.refresh_from_db()
        assert member.is_trial is True  # not admitted on the pending sibling


@pytest.mark.django_db
class TestCancelledSharesExcludedFromBounds:
    """BL-11: cancelled (divested) coop shares are not live equity and must
    not count toward the GenG min/max window."""

    def _confirmed_member_with_shares(self, count):
        # Build the position while exempt (pending applicant), then confirm —
        # the per-share min guard blocks incremental build-up once confirmed.
        member = MemberFactory(is_trial=False, admin_confirmed=False)
        for _ in range(count):
            CoopShareFactory(member=member, amount_of_coop_shares=Decimal(1))
        member.admin_confirmed = True
        member.save()
        return member

    def test_member_total_excludes_cancelled(self, tenant):
        _settings(tenant, min_number_coop_shares=1, max_number_coop_shares=10)
        member = self._confirmed_member_with_shares(3)
        assert CoopShareService.member_total_shares(member) == Decimal(3)

        share = CoopShare.objects.filter(member=member).first()
        share.cancelled_at = timezone.now()
        share.save()  # min=1, drops to 2 live → allowed

        assert CoopShareService.member_total_shares(member) == Decimal(2)

    def test_at_max_cancel_one_then_buy_one_is_allowed(self, tenant):
        # Previously the cancelled row still counted, so buying after
        # cancelling tripped the max. Now the cancelled row is excluded.
        _settings(tenant, min_number_coop_shares=1, max_number_coop_shares=3)
        member = self._confirmed_member_with_shares(3)  # at max

        share = CoopShare.objects.filter(member=member).first()
        share.cancelled_at = timezone.now()
        share.save()  # live total → 2

        CoopShareFactory(member=member, amount_of_coop_shares=Decimal(1))  # → 3
        assert CoopShareService.member_total_shares(member) == Decimal(3)

    def test_cancelling_below_minimum_is_rejected(self, tenant):
        # A confirmed member at the minimum cannot silently divest below it:
        # the cancelled share no longer props up the total.
        _settings(tenant, min_number_coop_shares=3, max_number_coop_shares=10)
        member = self._confirmed_member_with_shares(3)  # exactly at min

        share = CoopShare.objects.filter(member=member).first()
        share.cancelled_at = timezone.now()
        with pytest.raises(MemberCoopSharesOutOfRange):
            share.save()


@pytest.mark.django_db
class TestConfirmEnforcesBounds:
    """BL-21: Member.confirm() itself gates GenG admission on the min/max
    window, so the cascade entry-points (Subscription-confirm, link_to_user,
    accept_invitation) can't admit an out-of-range member into the
    Mitgliederliste."""

    def test_confirm_below_minimum_is_rejected_and_not_half_admitted(self, tenant):
        _settings(tenant, min_number_coop_shares=3, max_number_coop_shares=10)
        member = MemberFactory(is_trial=False, admin_confirmed=False)  # zero shares
        office = JasminUserFactory(roles=["office"])

        with pytest.raises(MemberCoopSharesOutOfRange):
            member.confirm(admin_user=office)

        member.refresh_from_db()
        assert member.admin_confirmed is False  # never half-admitted

    def test_confirm_with_valid_equity_succeeds(self, tenant):
        _settings(tenant, min_number_coop_shares=1, max_number_coop_shares=10)
        member = MemberFactory(is_trial=False, admin_confirmed=False)
        CoopShareFactory(member=member, amount_of_coop_shares=Decimal(3))
        office = JasminUserFactory(roles=["office"])

        member.confirm(admin_user=office)

        member.refresh_from_db()
        assert member.admin_confirmed is True

    def test_trial_member_confirm_is_exempt(self, tenant):
        # Trial members aren't Mitglieder yet — the window doesn't apply.
        _settings(tenant, min_number_coop_shares=3, max_number_coop_shares=10)
        member = MemberFactory(is_trial=True, admin_confirmed=False)  # zero shares
        member.confirm(admin_user=JasminUserFactory(roles=["office"]))
        member.refresh_from_db()
        assert member.admin_confirmed is True
