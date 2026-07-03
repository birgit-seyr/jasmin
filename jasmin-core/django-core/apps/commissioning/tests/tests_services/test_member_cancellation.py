"""Tests for ``apps.commissioning.services.member_cancellation``.

The service has two jobs:

  1. Stamp ``cancelled_at`` / ``cancelled_effective_at`` /
     ``cancelled_by`` on the Member row (the GenG §30 Austrittsdatum).
  2. Cascade those timestamps to every still-OPEN CoopShare for that
     member, so the equity history and the member record never
     disagree about whether the member has exited or when.

"Open" = ``cancelled_at IS NULL``. Shares that were already cancelled
previously (e.g. the member voluntarily downsized two years ago)
MUST be left at their existing date — overwriting them would falsify
the per-share equity history that GenG §31 requires to be
reconstructable for 10 years after exit.

The cascade runs inside ``@transaction.atomic`` — either both writes
land or neither does. We don't simulate DB failures here (overkill
for unit tests), but we DO verify the lock on the "open" status so
the cascade is a single bulk UPDATE rather than per-share .save()
calls (which would re-fire CoopShare.clean()'s pricing constraints
and break the cascade).
"""

from __future__ import annotations

import datetime

import pytest
import time_machine
from django.db import DatabaseError
from django.utils import timezone

from apps.commissioning.models import CoopShare
from apps.commissioning.services.member_cancellation import (
    cancel_member_with_coop_shares,
)
from apps.commissioning.services.subscription_service import SubscriptionService
from apps.commissioning.tests.factories import (
    CoopShareFactory,
    DeliveryStationDayFactory,
    JasminUserFactory,
    MemberFactory,
    PaymentCycleFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
)


@pytest.mark.django_db
class TestCancelMemberWithShares:
    def test_stamps_member_and_all_open_shares(self, tenant):
        """Happy path: member + every open CoopShare get the same
        timestamp set in one transaction."""
        member = MemberFactory()
        share_a = CoopShareFactory(member=member)
        share_b = CoopShareFactory(member=member)
        officer = JasminUserFactory(roles=["admin"])
        before = timezone.now()

        result = cancel_member_with_coop_shares(member, cancelled_by=officer)

        assert result.pk == member.pk
        member.refresh_from_db()
        assert member.cancelled_at is not None
        assert member.cancelled_at >= before
        # Effective date defaults to the tenant-LOCAL date of the cancellation
        # instant (not the UTC ``cancelled_at.date()``) — see member_cancellation.
        assert member.cancelled_effective_at == timezone.localdate(member.cancelled_at)
        assert member.cancelled_by_id == officer.pk

        share_a.refresh_from_db()
        share_b.refresh_from_db()
        # All three rows share the SAME timestamps — that's the
        # whole point of the "single transaction" guarantee.
        assert share_a.cancelled_at == member.cancelled_at
        assert share_a.cancelled_effective_at == member.cancelled_effective_at
        assert share_a.cancelled_by_id == officer.pk
        assert share_b.cancelled_at == member.cancelled_at

    def test_leaves_already_cancelled_shares_untouched(self, tenant):
        """The crux of the soft-retention rule: a member who
        voluntarily downsized 2 years ago keeps that 2-year-old
        cancellation date on the affected share. Cancelling the
        member today MUST NOT rewrite the historical date."""
        member = MemberFactory()
        old_cancelled_at = timezone.now() - datetime.timedelta(days=730)
        old_effective = (old_cancelled_at - datetime.timedelta(days=0)).date()
        already_cancelled = CoopShareFactory(member=member)
        # Bypass any "clean()" pricing logic by going through update().
        CoopShare.objects.filter(pk=already_cancelled.pk).update(
            cancelled_at=old_cancelled_at,
            cancelled_effective_at=old_effective,
        )

        still_open = CoopShareFactory(member=member)

        cancel_member_with_coop_shares(member)

        already_cancelled.refresh_from_db()
        # Historical date preserved — GenG §31 audit trail intact.
        assert already_cancelled.cancelled_at.replace(microsecond=0) == (
            old_cancelled_at.replace(microsecond=0)
        )
        assert already_cancelled.cancelled_effective_at == old_effective

        still_open.refresh_from_db()
        # Today's open share got today's cancellation.
        assert still_open.cancelled_at is not None
        assert still_open.cancelled_at > old_cancelled_at

    def test_explicit_effective_date_overrides_today(self, tenant):
        """End-of-year exits after a notice period need a future
        ``cancelled_effective_at`` (the legal exit date) while
        ``cancelled_at`` is the timestamp the office recorded it.
        Both must reflect what the caller passed."""
        member = MemberFactory()
        share = CoopShareFactory(member=member)
        future_effective = datetime.date(2027, 12, 31)
        recorded_at = timezone.now()

        cancel_member_with_coop_shares(
            member,
            cancelled_at=recorded_at,
            cancelled_effective_at=future_effective,
        )

        member.refresh_from_db()
        share.refresh_from_db()
        assert member.cancelled_effective_at == future_effective
        assert share.cancelled_effective_at == future_effective
        # And the recorded timestamp is also exact (not "now").
        assert member.cancelled_at.replace(microsecond=0) == (
            recorded_at.replace(microsecond=0)
        )

    def test_cancelled_by_optional(self, tenant):
        """Cascades from anonymisation flows (no human admin) pass
        ``cancelled_by=None``. The field is nullable on both Member
        and CoopShare; the service must not require it."""
        member = MemberFactory()
        share = CoopShareFactory(member=member)

        cancel_member_with_coop_shares(member)

        member.refresh_from_db()
        share.refresh_from_db()
        assert member.cancelled_by_id is None
        assert share.cancelled_by_id is None
        # But the dates are still set.
        assert member.cancelled_at is not None
        assert share.cancelled_at is not None

    def test_no_shares_at_all_still_cancels_member(self, tenant):
        """Edge case: a brand-new member with no CoopShare rows yet
        (somewhere between admin_confirmed and the first coop-share
        being written). Cascade must still stamp the Member without
        crashing on the empty CoopShare queryset."""
        member = MemberFactory()
        assert not CoopShare.objects.filter(member=member).exists()

        cancel_member_with_coop_shares(member)

        member.refresh_from_db()
        assert member.cancelled_at is not None


@pytest.mark.django_db
class TestMemberCancellationEndsSubscriptions:
    """MEM-10: cancelling a member also ends their active subscriptions
    (truncate term + drop future deliveries), not just the equity records."""

    @time_machine.travel(datetime.date(2026, 3, 30), tick=False)  # Monday
    def test_active_subscription_is_cancelled(self, tenant):
        member = MemberFactory()
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2)  # Wednesday
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
        payment_cycle = PaymentCycleFactory()
        svc = SubscriptionService()
        sub = svc.create_bare_subscription(
            {
                "member": member.pk,
                "share_type_variation": variation.pk,
                "valid_from": datetime.date(2026, 4, 6),  # Monday
                "valid_until": datetime.date(2026, 4, 26),  # Sunday
                "quantity": 1,
                "payment_cycle": payment_cycle,
                "default_delivery_station_day": station_day,
            }
        )
        sub.confirm(admin_user=JasminUserFactory(), save=True)

        # force=True: an active subscription would otherwise REFUSE the cancel
        # (MemberHasActiveSubscriptions). Force-cancel ends it as part of the
        # cascade.
        result = cancel_member_with_coop_shares(
            member,
            cancelled_effective_at=datetime.date(2026, 4, 12),  # Sunday in term
            cancelled_by=JasminUserFactory(),
            force=True,
        )

        sub.refresh_from_db()
        assert sub.cancelled_at is not None
        assert sub.valid_until == datetime.date(2026, 4, 12)
        # The force-cancel reports it as ended (no live mandate left behind).
        assert sub.id in result.cancellation_result["subscriptions_ended"]
        assert result.cancellation_result["subscriptions_not_ended"] == []

    @time_machine.travel(datetime.date(2026, 3, 30), tick=False)  # Monday
    def test_active_subscription_refuses_cancel_without_force(self, tenant):
        # MEM-10: the default cancel is REFUSED while an active subscription
        # remains — the office must end it first or force-cancel.
        from apps.commissioning.errors import MemberHasActiveSubscriptions

        member = MemberFactory()
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
        payment_cycle = PaymentCycleFactory()
        svc = SubscriptionService()
        sub = svc.create_bare_subscription(
            {
                "member": member.pk,
                "share_type_variation": variation.pk,
                "valid_from": datetime.date(2026, 4, 6),
                "valid_until": datetime.date(2026, 4, 26),
                "quantity": 1,
                "payment_cycle": payment_cycle,
                "default_delivery_station_day": station_day,
            }
        )
        sub.confirm(admin_user=JasminUserFactory(), save=True)

        with pytest.raises(MemberHasActiveSubscriptions):
            cancel_member_with_coop_shares(
                member,
                cancelled_effective_at=datetime.date(2026, 4, 12),
                cancelled_by=JasminUserFactory(),
            )
        # Nothing was written — the member is NOT cancelled.
        member.refresh_from_db()
        assert member.cancelled_at is None
        sub.refresh_from_db()
        assert sub.cancelled_at is None

    @time_machine.travel(datetime.date(2026, 3, 30), tick=False)  # Monday
    def test_force_ends_subscription_that_has_not_started_yet(self, tenant):
        # MEM-10: a confirmed subscription whose term begins AFTER the exit date
        # can't be Sunday-truncated by cancel_subscription (CancellationBefore-
        # ValidFrom, e.g. a future-dated trial). A force-cancel must still END it
        # (lenient fallback), not leave it active / in subscriptions_not_ended.
        member = MemberFactory()
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
        payment_cycle = PaymentCycleFactory()
        svc = SubscriptionService()
        sub = svc.create_bare_subscription(
            {
                "member": member.pk,
                "share_type_variation": variation.pk,
                "valid_from": datetime.date(2026, 4, 13),  # Monday, AFTER the exit
                "valid_until": datetime.date(2026, 12, 27),  # Sunday
                "quantity": 1,
                "payment_cycle": payment_cycle,
                "default_delivery_station_day": station_day,
            }
        )
        sub.confirm(admin_user=JasminUserFactory(), save=True)

        result = cancel_member_with_coop_shares(
            member,
            cancelled_effective_at=datetime.date(
                2026, 4, 5
            ),  # Sunday, BEFORE valid_from
            cancelled_by=JasminUserFactory(),
            force=True,
        )

        sub.refresh_from_db()
        # Ended leniently — stamped cancelled, reported as ended (NOT a silent
        # failure), and its future deliveries dropped.
        assert sub.cancelled_at is not None
        assert sub.id in result.cancellation_result["subscriptions_ended"]
        assert result.cancellation_result["subscriptions_not_ended"] == []

    @time_machine.travel(datetime.date(2026, 3, 30), tick=False)  # Monday
    def test_draft_subscription_is_wound_down(self, tenant):
        # MEM-1: an unconfirmed (draft) subscription has no deliveries/charges
        # but may hold a CapacityReservation. Member exit must stamp it
        # cancelled and release any reservation, so the slot frees and the draft
        # can never be confirmed into live deliveries/charges later.
        from apps.commissioning.models.days import CapacityReservation

        member = MemberFactory()
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2)  # Wednesday
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
        payment_cycle = PaymentCycleFactory()
        sub = SubscriptionService().create_bare_subscription(
            {
                "member": member.pk,
                "share_type_variation": variation.pk,
                "valid_from": datetime.date(2026, 4, 6),  # Monday
                "valid_until": datetime.date(2026, 4, 26),  # Sunday
                "quantity": 1,
                "payment_cycle": payment_cycle,
                "default_delivery_station_day": station_day,
            }
        )
        assert not sub.admin_confirmed  # draft

        cancel_member_with_coop_shares(
            member,
            cancelled_effective_at=datetime.date(2026, 4, 12),  # Sunday in term
            cancelled_by=JasminUserFactory(),
        )

        sub.refresh_from_db()
        assert sub.cancelled_at is not None
        assert sub.cancelled_effective_at == datetime.date(2026, 4, 12)
        # Any capacity hold is released.
        assert not CapacityReservation.objects.filter(subscription=sub).exists()

    @pytest.mark.parametrize(
        "error",
        [
            DatabaseError("db"),
            ValueError("logic error in regen"),
            IndexError("smoothed split out of range"),
        ],
        ids=["DatabaseError", "ValueError", "IndexError"],
    )
    @time_machine.travel(datetime.date(2026, 3, 30), tick=False)  # Monday
    def test_subscription_error_does_not_abort_member_exit(self, tenant, error):
        """MEM-5: a non-JasminError raised while ending ONE subscription must NOT
        roll back the whole member exit — neither a DatabaseError nor an
        unexpected logic error (ValueError / IndexError) from the billing regen.
        The per-subscription savepoint isolates it; the Member + CoopShare stamps
        still commit and the service returns instead of propagating."""
        from unittest.mock import patch

        member = MemberFactory()
        share = CoopShareFactory(member=member)
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2)  # Wednesday
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
        payment_cycle = PaymentCycleFactory()
        svc = SubscriptionService()
        sub = svc.create_bare_subscription(
            {
                "member": member.pk,
                "share_type_variation": variation.pk,
                "valid_from": datetime.date(2026, 4, 6),  # Monday
                "valid_until": datetime.date(2026, 4, 26),  # Sunday
                "quantity": 1,
                "payment_cycle": payment_cycle,
                "default_delivery_station_day": station_day,
            }
        )
        sub.confirm(admin_user=JasminUserFactory(), save=True)

        with patch.object(
            SubscriptionService,
            "cancel_subscription",
            side_effect=error,
        ) as cancel_mock:
            # Must NOT raise — the error is caught at the savepoint and logged.
            # force=True to reach the cascade (the active sub would otherwise
            # refuse the cancel up front).
            result = cancel_member_with_coop_shares(
                member,
                cancelled_effective_at=datetime.date(2026, 4, 12),  # Sunday in term
                cancelled_by=JasminUserFactory(),
                force=True,
            )

        cancel_mock.assert_called_once()  # the subscription WAS attempted
        member.refresh_from_db()
        share.refresh_from_db()
        # The member exit committed despite the subscription's failure.
        assert member.cancelled_at is not None
        assert share.cancelled_at is not None
        # The subscription itself stayed un-cancelled (its cancel rolled back),
        # but that failure did not poison the member/equity exit.
        sub.refresh_from_db()
        assert sub.cancelled_at is None
        # BIZ-1: the failure is surfaced, not silent — the office can see this
        # subscription still holds a live mandate.
        assert sub.id in result.cancellation_result["subscriptions_not_ended"]


@pytest.mark.django_db(transaction=True)
class TestCancellationConfirmationEmail:
    """P2-3: cancelling a member schedules a
    ``commissioning.member_cancelled`` confirmation email via
    ``on_commit`` and stamps
    ``Member.cancellation_email_sent_at`` after a successful send.
    Skipped silently for members with no email — most importantly,
    the GDPR anonymisation path, which has already scrubbed
    ``member.email`` to ``None`` before reaching this service.
    """

    def _patch_send(self, return_value=True):
        from unittest.mock import patch

        # EmailService is imported lazily inside
        # ``_send_cancellation_email``; patch the real class location.
        return patch(
            "apps.shared.tenants.email_service.EmailService.send_email",
            return_value=return_value,
        )

    def test_send_dispatches_after_commit_and_stamps_tracker(self, tenant):
        from django.test import TestCase

        member = MemberFactory(email="austritt-happy@example.org")
        assert member.cancellation_email_sent_at is None

        with self._patch_send() as send_mock:
            with TestCase.captureOnCommitCallbacks(execute=True):
                cancel_member_with_coop_shares(member)

        send_mock.assert_called_once()
        assert send_mock.call_args.kwargs["slug"] == "commissioning.member_cancelled"

        member.refresh_from_db()
        assert member.cancelled_at is not None
        assert member.cancellation_email_sent_at is not None

    def test_failed_send_does_not_stamp_tracker(self, tenant):
        """``EmailService.send_email`` returning ``False`` means the
        SMTP layer rejected the message. The tracker stays NULL so
        a future manual re-send remains obviously unsent.
        """
        from django.test import TestCase

        member = MemberFactory(email="austritt-failed@example.org")

        with self._patch_send(return_value=False) as send_mock:
            with TestCase.captureOnCommitCallbacks(execute=True):
                cancel_member_with_coop_shares(member)

        send_mock.assert_called_once()
        member.refresh_from_db()
        # Cancellation still committed — the send failure is best-effort.
        assert member.cancelled_at is not None
        # But the tracker did NOT advance.
        assert member.cancellation_email_sent_at is None

    def test_member_without_email_does_not_dispatch(self, tenant):
        """The GDPR path scrubs ``member.email`` before calling this
        service. We must NOT try to send a cancellation confirmation
        in that case — the user explicitly asked to be forgotten.
        """
        from django.test import TestCase

        member = MemberFactory(email=None)

        with self._patch_send() as send_mock:
            with TestCase.captureOnCommitCallbacks(execute=True):
                cancel_member_with_coop_shares(member)

        send_mock.assert_not_called()
        member.refresh_from_db()
        assert member.cancelled_at is not None
        assert member.cancellation_email_sent_at is None

    def test_outer_rollback_discards_scheduled_email(self, tenant):
        """If the caller wraps this in their own atomic block and then
        raises, the on_commit callback must be discarded — no ghost
        email for a cancellation that never persisted.
        """
        from django.db import transaction as django_transaction
        from django.test import TestCase

        member = MemberFactory(email="austritt-rollback@example.org")

        with self._patch_send() as send_mock:
            with TestCase.captureOnCommitCallbacks(execute=True):
                try:
                    with django_transaction.atomic():
                        cancel_member_with_coop_shares(member)
                        raise RuntimeError("simulated downstream failure")
                except RuntimeError:
                    pass

        send_mock.assert_not_called()
        member.refresh_from_db()
        # State change rolled back too.
        assert member.cancelled_at is None
        assert member.cancellation_email_sent_at is None
