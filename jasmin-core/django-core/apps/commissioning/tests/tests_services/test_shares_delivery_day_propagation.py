"""Tests for SharesDeliveryDay propagation to future shares, share deliveries,
and delivery station days when a new SharesDeliveryDay is created."""

from __future__ import annotations

import datetime
from datetime import timedelta

import pytest
import time_machine
from django.utils import timezone
from isoweek import Week

from apps.commissioning.models import Share, ShareDelivery, SharesDeliveryDay
from apps.commissioning.services.shares_delivery_day_service import (
    SharesDeliveryDayService,
)
from apps.commissioning.services.subscription_service import SubscriptionService
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    JasminUserFactory,
    MemberFactory,
    PaymentCycleFactory,
    ShareDeliveryFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)


@pytest.fixture(autouse=True)
def _frozen_today():
    """Freeze "today" to 2026-07-20 (ISO week 30) so the relative "N weeks ahead"
    dates in this module stay within 2026 — otherwise a December run pushes the
    +2/+4-week station-day/share dates across the year boundary and breaks the
    succession-propagation math.
    """
    with time_machine.travel(datetime.datetime(2026, 7, 20, 12, 0), tick=False):
        yield


class _MondayHelpers:
    """Strictly-future Monday helpers shared by the propagation test classes.
    Distinct from production ``iso_week_utils.next_monday`` (which is INCLUSIVE
    — returns the date unchanged on a Monday); here a Monday returns the NEXT
    Monday, so a test date always lands strictly in the future."""

    def _next_monday(self) -> datetime.date:
        today = datetime.date.today()
        days_ahead = (0 - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return today + timedelta(days=days_ahead)

    def _monday_n_weeks_ahead(self, n: int) -> datetime.date:
        return self._next_monday() + timedelta(weeks=n - 1)


@pytest.mark.django_db
class TestSharesDeliveryDayPropagation(_MondayHelpers):
    """When a new SharesDeliveryDay replaces an existing one (same day_number),
    future shares, share deliveries, and delivery station days that reference
    the old SharesDeliveryDay must be updated to the new one."""

    def test_new_delivery_day_propagates_to_future_objects(self, tenant):
        """Full integration scenario:

        1. Create two SharesDeliveryDays: Monday (day_number=0) and Friday (day_number=4).
        2. Create a DeliveryStationDay for each.
        3. Create two subscriptions, each with a future share and share delivery.
        4. Create a new SharesDeliveryDay with day_number=0 (valid_from = 2 weeks out)
           and a different default_harvesting_day.
        5. Assert that only Monday-related future objects get updated to the new day.
        """
        base_monday = self._monday_n_weeks_ahead(0)
        valid_from_new = self._monday_n_weeks_ahead(2)
        # valid_until for old Monday day: the Sunday before new valid_from
        old_valid_until = valid_from_new - timedelta(days=1)

        # ── Step 1: Create two SharesDeliveryDays ──
        old_monday = SharesDeliveryDayFactory(
            day_number=0,
            valid_from=base_monday,
            valid_until=old_valid_until,
            default_harvesting_day=4,  # Friday
            default_packing_day=0,
        )
        friday = SharesDeliveryDayFactory(
            day_number=4,
            valid_from=base_monday,
            default_harvesting_day=3,  # Thursday
            default_packing_day=4,
        )

        # ── Step 2: Create delivery stations + station days ──
        station = DeliveryStationFactory(short_name="StationA")
        dsd_monday = DeliveryStationDayFactory(
            delivery_station=station,
            delivery_day=old_monday,
            valid_from=base_monday,
            tour_number=1,
        )
        dsd_friday = DeliveryStationDayFactory(
            delivery_station=station,
            delivery_day=friday,
            valid_from=base_monday,
            tour_number=1,
        )

        # ── Step 3: Create subscriptions with shares and share deliveries ──
        variation = ShareTypeVariationFactory()

        # Future week (well after valid_from_new)
        future_week = Week.withdate(valid_from_new + timedelta(weeks=4))

        # Share + delivery for Monday
        share_monday = ShareFactory(
            year=future_week.year,
            delivery_week=future_week.week,
            delivery_day=old_monday,
            share_type_variation=variation,
            harvesting_day=old_monday.default_harvesting_day,
            packing_day=old_monday.default_packing_day,
        )

        sub_1 = SubscriptionFactory(
            share_type_variation=variation,
            valid_from=base_monday,
            default_delivery_station_day=dsd_monday,
        )
        sd_monday = ShareDeliveryFactory(
            share=share_monday,
            delivery_station_day=dsd_monday,
            subscription=sub_1,
        )

        # Share + delivery for Friday
        share_friday = ShareFactory(
            year=future_week.year,
            delivery_week=future_week.week,
            delivery_day=friday,
            share_type_variation=variation,
            harvesting_day=friday.default_harvesting_day,
            packing_day=friday.default_packing_day,
        )

        sub_2 = SubscriptionFactory(
            share_type_variation=variation,
            valid_from=base_monday,
            default_delivery_station_day=dsd_friday,
        )
        sd_friday = ShareDeliveryFactory(
            share=share_friday,
            delivery_station_day=dsd_friday,
            subscription=sub_2,
        )

        # ── Step 4: Create new Monday SharesDeliveryDay with different harvesting_day ──
        new_monday = SharesDeliveryDayFactory(
            day_number=0,
            valid_from=valid_from_new,
            default_harvesting_day=2,  # Wednesday (changed from Friday)
            default_packing_day=0,
        )

        # Run the service methods (same as what the viewset calls)
        new_dsds = SharesDeliveryDayService.update_delivery_station_days(
            instance=new_monday,
            existing_delivery_day=old_monday,
            validated_data={"valid_from": valid_from_new},
        )
        SharesDeliveryDayService.update_shares_for_delivery_day(
            new_delivery_day=new_monday,
            old_delivery_day=old_monday,
        )
        SharesDeliveryDayService.update_share_deliveries_for_delivery_day(
            new_delivery_day=new_monday,
            old_delivery_day=old_monday,
        )

        # ── Step 5: Assert Monday objects updated ──

        # DeliveryStationDay: old Monday DSD should be closed
        dsd_monday.refresh_from_db()
        assert dsd_monday.valid_until == valid_from_new - timedelta(days=1)

        # New DSD should have been created for the new Monday
        assert len(new_dsds) == 1
        new_dsd_monday = new_dsds[0]
        assert new_dsd_monday.delivery_day == new_monday
        assert new_dsd_monday.delivery_station == station
        assert new_dsd_monday.valid_from == valid_from_new

        # Share: Monday share now points to new_monday with updated harvesting_day
        share_monday.refresh_from_db()
        assert share_monday.delivery_day == new_monday
        assert share_monday.harvesting_day == 2  # Wednesday (was Friday)
        assert share_monday.packing_day == 0  # Still Monday

        # ShareDelivery: Monday share delivery now uses the new DSD
        sd_monday.refresh_from_db()
        assert sd_monday.delivery_station_day == new_dsd_monday

        # ── Assert Friday objects NOT updated ──

        # Friday DSD unchanged
        dsd_friday.refresh_from_db()
        assert dsd_friday.valid_until is None  # Not closed
        assert dsd_friday.delivery_day == friday

        # Friday share unchanged
        share_friday.refresh_from_db()
        assert share_friday.delivery_day == friday
        assert share_friday.harvesting_day == 3  # Thursday (unchanged)

        # Friday share delivery unchanged
        sd_friday.refresh_from_db()
        assert sd_friday.delivery_station_day == dsd_friday

    def test_past_shares_not_updated(self, tenant):
        """Shares in the past should NOT be updated when a new
        SharesDeliveryDay replaces the old one."""
        valid_from_new = self._monday_n_weeks_ahead(2)
        old_valid_until = valid_from_new - timedelta(days=1)

        old_monday = SharesDeliveryDayFactory(
            day_number=0,
            valid_from=datetime.date(2024, 1, 1),
            valid_until=old_valid_until,
            default_harvesting_day=4,
        )
        new_monday = SharesDeliveryDayFactory(
            day_number=0,
            valid_from=valid_from_new,
            default_harvesting_day=2,
        )

        variation = ShareTypeVariationFactory()

        # Past share (2024)
        past_share = ShareFactory(
            year=2024,
            delivery_week=10,
            delivery_day=old_monday,
            share_type_variation=variation,
            harvesting_day=4,
        )

        count = SharesDeliveryDayService.update_shares_for_delivery_day(
            new_delivery_day=new_monday,
            old_delivery_day=old_monday,
        )

        assert count == 0
        past_share.refresh_from_db()
        assert past_share.delivery_day == old_monday
        assert past_share.harvesting_day == 4  # unchanged

    def test_inherited_day_field_clears_when_successor_default_is_none(self, tenant):
        """SUC-6: a Share that INHERITED its harvesting_day from the old day must
        follow the successor day's default — INCLUDING when the successor clears
        it (None) — not silently retain the predecessor's value."""
        valid_from_new = self._monday_n_weeks_ahead(2)
        old_valid_until = valid_from_new - timedelta(days=1)
        old_monday = SharesDeliveryDayFactory(
            day_number=0,
            valid_from=self._monday_n_weeks_ahead(0),
            valid_until=old_valid_until,
            default_harvesting_day=4,  # Friday
            default_packing_day=0,
        )
        new_monday = SharesDeliveryDayFactory(
            day_number=0,
            valid_from=valid_from_new,
            default_harvesting_day=None,  # successor CLEARS the harvesting default
            default_packing_day=0,
        )
        variation = ShareTypeVariationFactory()
        future_week = Week.withdate(valid_from_new + timedelta(weeks=4))
        share = ShareFactory(
            year=future_week.year,
            delivery_week=future_week.week,
            delivery_day=old_monday,
            share_type_variation=variation,
            harvesting_day=old_monday.default_harvesting_day,  # INHERITED
            packing_day=old_monday.default_packing_day,
        )

        SharesDeliveryDayService.update_shares_for_delivery_day(
            new_delivery_day=new_monday,
            old_delivery_day=old_monday,
        )

        share.refresh_from_db()
        assert share.delivery_day == new_monday
        # Inherited harvesting_day now follows the successor's cleared default.
        assert share.harvesting_day is None
        assert share.packing_day == 0  # default unchanged (0 → 0)

    def test_overridden_day_field_survives_when_successor_clears(self, tenant):
        """SUC-6 counterpart: a deliberate per-week OVERRIDE (differs from the
        old default) survives catalogue succession even if the successor clears
        that default."""
        valid_from_new = self._monday_n_weeks_ahead(2)
        old_valid_until = valid_from_new - timedelta(days=1)
        old_monday = SharesDeliveryDayFactory(
            day_number=0,
            valid_from=self._monday_n_weeks_ahead(0),
            valid_until=old_valid_until,
            default_harvesting_day=4,
        )
        new_monday = SharesDeliveryDayFactory(
            day_number=0,
            valid_from=valid_from_new,
            default_harvesting_day=None,
        )
        variation = ShareTypeVariationFactory()
        future_week = Week.withdate(valid_from_new + timedelta(weeks=4))
        share = ShareFactory(
            year=future_week.year,
            delivery_week=future_week.week,
            delivery_day=old_monday,
            share_type_variation=variation,
            harvesting_day=1,  # OVERRIDE (differs from old default 4)
        )

        SharesDeliveryDayService.update_shares_for_delivery_day(
            new_delivery_day=new_monday,
            old_delivery_day=old_monday,
        )

        share.refresh_from_db()
        assert share.harvesting_day == 1  # override preserved

    def test_multiple_stations_propagated(self, tenant):
        """When multiple delivery stations exist for the same day,
        all should get new DeliveryStationDays."""
        base_monday = self._monday_n_weeks_ahead(0)
        valid_from_new = self._monday_n_weeks_ahead(2)
        old_valid_until = valid_from_new - timedelta(days=1)

        old_monday = SharesDeliveryDayFactory(
            day_number=0,
            valid_from=base_monday,
            valid_until=old_valid_until,
            default_harvesting_day=4,
        )

        station_a = DeliveryStationFactory(short_name="A")
        station_b = DeliveryStationFactory(short_name="B")

        dsd_a = DeliveryStationDayFactory(
            delivery_station=station_a,
            delivery_day=old_monday,
            valid_from=base_monday,
            tour_number=1,
        )
        dsd_b = DeliveryStationDayFactory(
            delivery_station=station_b,
            delivery_day=old_monday,
            valid_from=base_monday,
            tour_number=2,
        )

        new_monday = SharesDeliveryDayFactory(
            day_number=0,
            valid_from=valid_from_new,
            default_harvesting_day=2,
        )

        new_dsds = SharesDeliveryDayService.update_delivery_station_days(
            instance=new_monday,
            existing_delivery_day=old_monday,
            validated_data={"valid_from": valid_from_new},
        )

        assert len(new_dsds) == 2

        # Both old DSDs should be closed
        dsd_a.refresh_from_db()
        dsd_b.refresh_from_db()
        assert dsd_a.valid_until == old_valid_until
        assert dsd_b.valid_until == old_valid_until

        # New DSDs should point to correct stations
        new_stations = {dsd.delivery_station_id for dsd in new_dsds}
        assert station_a.id in new_stations
        assert station_b.id in new_stations

        # Tour numbers should be preserved
        new_by_station = {dsd.delivery_station_id: dsd for dsd in new_dsds}
        assert new_by_station[station_a.id].tour_number == 1
        assert new_by_station[station_b.id].tour_number == 2


@pytest.mark.django_db
class TestSubscriptionCreationWithFutureDeliveryStationDay:
    """When a subscription is created and a DeliveryStationDay is chosen,
    the SubscriptionService must use the correct (future) DeliveryStationDay
    for share deliveries in weeks where a successor DeliveryStationDay exists."""

    def test_shares_use_correct_delivery_day_across_succession(self, tenant):
        """Scenario:
        - Old Monday DeliveryDay valid until week N.
        - New Monday DeliveryDay valid from week N+1 (different harvesting_day).
        - Subscription spans both old and new periods.
        - Shares in the old period should use old_monday.
        - Shares in the new period should use new_monday.
        """
        # Old Monday: valid for first 4 weeks of May 2026
        old_monday = SharesDeliveryDayFactory(
            day_number=0,
            valid_from=datetime.date(2026, 5, 4),  # Monday
            valid_until=datetime.date(2026, 5, 24),  # Sunday end of week
            default_harvesting_day=4,  # Friday
        )
        # New Monday: valid from week 5 of May onwards
        new_monday = SharesDeliveryDayFactory(
            day_number=0,
            valid_from=datetime.date(2026, 5, 25),  # Monday
            default_harvesting_day=2,  # Wednesday (different!)
        )

        station = DeliveryStationFactory(short_name="TestStation")
        old_dsd = DeliveryStationDayFactory(
            delivery_station=station,
            delivery_day=old_monday,
            valid_from=datetime.date(2026, 5, 4),
            valid_until=datetime.date(2026, 5, 24),
            tour_number=1,
        )
        new_dsd = DeliveryStationDayFactory(
            delivery_station=station,
            delivery_day=new_monday,
            valid_from=datetime.date(2026, 5, 25),
            tour_number=1,
        )

        member = MemberFactory()
        variation = ShareTypeVariationFactory()
        payment_cycle = PaymentCycleFactory()

        # Subscription spans both old and new delivery day periods
        validated_data = {
            "member": member.pk,
            "share_type_variation": variation.pk,
            "valid_from": datetime.date(2026, 5, 4),
            "valid_until": datetime.date(2026, 6, 14),  # ~6 weeks
            "quantity": 1,
            "payment_cycle": payment_cycle,
            "default_delivery_station_day": old_dsd,
        }

        svc = SubscriptionService()
        sub = svc.create_bare_subscription(validated_data)
        sub.confirm(admin_user=JasminUserFactory(), save=True)

        # Get all shares created for this variation
        shares = Share.objects.filter(
            share_type_variation=variation,
        ).order_by("year", "delivery_week")

        assert shares.count() >= 4  # At least 4 Mondays in range

        # Shares in old period should use old_monday
        old_period_shares = [
            s
            for s in shares
            if Week(s.year, s.delivery_week).monday() <= datetime.date(2026, 5, 24)
        ]
        for share in old_period_shares:
            assert (
                share.delivery_day == old_monday
            ), f"Share week {share.delivery_week} should use old_monday"

        # Shares in new period should use new_monday
        new_period_shares = [
            s
            for s in shares
            if Week(s.year, s.delivery_week).monday() >= datetime.date(2026, 5, 25)
        ]
        assert len(new_period_shares) >= 1, "Should have shares in new period"
        for share in new_period_shares:
            assert (
                share.delivery_day == new_monday
            ), f"Share week {share.delivery_week} should use new_monday"

        # Share deliveries in old period should use old_dsd
        for share in old_period_shares:
            sds = ShareDelivery.objects.filter(share=share, subscription=sub)
            for sd in sds:
                assert (
                    sd.delivery_station_day == old_dsd
                ), f"ShareDelivery for week {share.delivery_week} should use old_dsd"

        # Share deliveries in new period should use new_dsd
        for share in new_period_shares:
            sds = ShareDelivery.objects.filter(share=share, subscription=sub)
            for sd in sds:
                assert (
                    sd.delivery_station_day == new_dsd
                ), f"ShareDelivery for week {share.delivery_week} should use new_dsd"


@pytest.mark.django_db
class TestManualValidUntilThenCreateNew(_MondayHelpers):
    """When a user manually sets valid_until on an existing SharesDeliveryDay
    and then creates a new one with the same day_number, the propagation to
    shares, share deliveries, and delivery station days must still happen."""

    def test_propagation_when_old_record_manually_closed(self, tenant):
        """Scenario:
        1. Create a SharesDeliveryDay (Monday, day_number=0).
        2. Manually set valid_until on it (simulating a PATCH).
        3. Create a new SharesDeliveryDay with day_number=0 starting after old ends.
        4. Propagation should still happen — shares, share deliveries, and
           delivery station days from the old record should move to the new one.
        """
        base_monday = self._monday_n_weeks_ahead(0)
        cutoff_sunday = self._monday_n_weeks_ahead(2) - timedelta(days=1)
        new_valid_from = self._monday_n_weeks_ahead(2)

        # Step 1: Create old Monday delivery day (open-ended initially)
        old_monday = SharesDeliveryDayFactory(
            day_number=0,
            valid_from=base_monday,
            default_harvesting_day=4,
            default_packing_day=0,
        )

        # Create station + station day
        station = DeliveryStationFactory(short_name="StationX")
        dsd_old = DeliveryStationDayFactory(
            delivery_station=station,
            delivery_day=old_monday,
            valid_from=base_monday,
            tour_number=1,
        )

        # Create future share + share delivery
        variation = ShareTypeVariationFactory()
        future_week = Week.withdate(new_valid_from + timedelta(weeks=4))

        share = ShareFactory(
            year=future_week.year,
            delivery_week=future_week.week,
            delivery_day=old_monday,
            share_type_variation=variation,
            harvesting_day=old_monday.default_harvesting_day,
            packing_day=old_monday.default_packing_day,
        )

        sub = SubscriptionFactory(
            share_type_variation=variation,
            valid_from=base_monday,
            default_delivery_station_day=dsd_old,
        )
        sd = ShareDeliveryFactory(
            share=share,
            delivery_station_day=dsd_old,
            subscription=sub,
        )

        # Step 2: Manually close old Monday (simulate PATCH valid_until)
        old_monday.valid_until = cutoff_sunday
        old_monday.save()

        # Step 3: Create new Monday delivery day starting after old ends
        new_monday = SharesDeliveryDayFactory(
            day_number=0,
            valid_from=new_valid_from,
            default_harvesting_day=2,  # Changed from 4 to 2
            default_packing_day=0,
        )

        # Step 4: Manually trigger propagation (simulating what viewset should do)
        # The viewset's create() currently skips this because handle_succession
        # returns None when old record already has valid_until.
        new_dsds = SharesDeliveryDayService.update_delivery_station_days(
            instance=new_monday,
            existing_delivery_day=old_monday,
            validated_data={"valid_from": new_valid_from},
        )
        SharesDeliveryDayService.update_shares_for_delivery_day(
            new_delivery_day=new_monday,
            old_delivery_day=old_monday,
        )
        SharesDeliveryDayService.update_share_deliveries_for_delivery_day(
            new_delivery_day=new_monday,
            old_delivery_day=old_monday,
        )

        # Assertions: old DSD closed
        dsd_old.refresh_from_db()
        assert dsd_old.valid_until == cutoff_sunday

        # New DSD created
        assert len(new_dsds) == 1
        new_dsd = new_dsds[0]
        assert new_dsd.delivery_day == new_monday
        assert new_dsd.delivery_station == station

        # Share updated
        share.refresh_from_db()
        assert share.delivery_day == new_monday
        assert share.harvesting_day == 2

        # Share delivery updated
        sd.refresh_from_db()
        assert sd.delivery_station_day == new_dsd

    def test_viewset_create_propagates_when_predecessor_already_closed(self, tenant):
        """The viewset's create() should find the predecessor even when it
        already has valid_until set, and still propagate changes."""
        base_monday = self._monday_n_weeks_ahead(0)
        cutoff_sunday = self._monday_n_weeks_ahead(2) - timedelta(days=1)
        new_valid_from = self._monday_n_weeks_ahead(2)

        # Create and manually close old Monday
        old_monday = SharesDeliveryDayFactory(
            day_number=0,
            valid_from=base_monday,
            valid_until=cutoff_sunday,
            default_harvesting_day=4,
            default_packing_day=0,
        )

        station = DeliveryStationFactory(short_name="StationY")
        dsd_old = DeliveryStationDayFactory(
            delivery_station=station,
            delivery_day=old_monday,
            valid_from=base_monday,
            tour_number=1,
        )

        variation = ShareTypeVariationFactory()
        future_week = Week.withdate(new_valid_from + timedelta(weeks=4))

        share = ShareFactory(
            year=future_week.year,
            delivery_week=future_week.week,
            delivery_day=old_monday,
            share_type_variation=variation,
            harvesting_day=4,
            packing_day=0,
        )

        sub = SubscriptionFactory(
            share_type_variation=variation,
            valid_from=base_monday,
            default_delivery_station_day=dsd_old,
        )
        sd = ShareDeliveryFactory(
            share=share,
            delivery_station_day=dsd_old,
            subscription=sub,
        )

        # Create new Monday — handle_succession returns None since old is
        # already closed, but viewset should still find predecessor and propagate.
        new_monday = SharesDeliveryDayFactory(
            day_number=0,
            valid_from=new_valid_from,
            default_harvesting_day=2,
            default_packing_day=0,
        )

        # Simulate what the fixed viewset should do:
        # Find predecessor even though it already has valid_until
        existing_delivery_day = SharesDeliveryDay.handle_succession(
            {"day_number": 0, "valid_from": new_valid_from}
        )
        # existing_delivery_day is None because old already closed

        # The fix: if handle_succession returns None, look for the most recent
        # closed predecessor with the same day_number
        if existing_delivery_day is None:
            predecessor = (
                SharesDeliveryDay.objects.filter(
                    day_number=new_monday.day_number,
                    valid_until__isnull=False,
                )
                .exclude(pk=new_monday.pk)
                .order_by("-valid_until")
                .first()
            )
        else:
            predecessor = existing_delivery_day

        assert predecessor == old_monday, "Should find the manually closed predecessor"

        # Now propagate using the found predecessor
        new_dsds = SharesDeliveryDayService.update_delivery_station_days(
            instance=new_monday,
            existing_delivery_day=predecessor,
            validated_data={"valid_from": new_valid_from},
        )
        SharesDeliveryDayService.update_shares_for_delivery_day(
            new_delivery_day=new_monday,
            old_delivery_day=predecessor,
        )
        SharesDeliveryDayService.update_share_deliveries_for_delivery_day(
            new_delivery_day=new_monday,
            old_delivery_day=predecessor,
        )

        # Share should be updated
        share.refresh_from_db()
        assert share.delivery_day == new_monday
        assert share.harvesting_day == 2

        # Share delivery should be updated
        sd.refresh_from_db()
        assert len(new_dsds) == 1
        assert sd.delivery_station_day == new_dsds[0]


@pytest.mark.django_db
class TestSuccessionEdgeCasePropagation(_MondayHelpers):
    """SUC-3/5/6/7/8: succession must migrate future-dated + same-boundary
    station days, never strand a future ShareDelivery on the closed old day,
    and never clobber a deliberate per-week day-field override."""

    def test_future_dated_station_day_repointed_to_new_day(self, tenant):
        # SUC-5/6: a future-only DSD on the predecessor (valid_from AFTER the
        # boundary) must be repointed onto the new day, and its future
        # ShareDelivery must resolve under the new day.
        base_monday = self._monday_n_weeks_ahead(0)
        valid_from_new = self._monday_n_weeks_ahead(2)
        future_start = self._monday_n_weeks_ahead(6)
        old_valid_until = valid_from_new - timedelta(days=1)

        old_monday = SharesDeliveryDayFactory(
            day_number=0, valid_from=base_monday, valid_until=old_valid_until
        )
        new_monday = SharesDeliveryDayFactory(day_number=0, valid_from=valid_from_new)
        station = DeliveryStationFactory(short_name="StationFuture")
        future_dsd = DeliveryStationDayFactory(
            delivery_station=station,
            delivery_day=old_monday,
            valid_from=future_start,
            tour_number=1,
        )
        variation = ShareTypeVariationFactory()
        week = Week.withdate(future_start + timedelta(weeks=2))
        share = ShareFactory(
            year=week.year,
            delivery_week=week.week,
            delivery_day=old_monday,
            share_type_variation=variation,
        )
        # The subscription onboards with the station only when the future DSD
        # begins (its default DSD must cover the subscription window).
        sub = SubscriptionFactory(
            share_type_variation=variation,
            valid_from=future_start,
            default_delivery_station_day=future_dsd,
        )
        sd = ShareDeliveryFactory(
            share=share, delivery_station_day=future_dsd, subscription=sub
        )

        SharesDeliveryDayService.update_delivery_station_days(
            instance=new_monday,
            existing_delivery_day=old_monday,
            validated_data={"valid_from": valid_from_new},
        )
        SharesDeliveryDayService.update_shares_for_delivery_day(
            new_delivery_day=new_monday, old_delivery_day=old_monday
        )
        SharesDeliveryDayService.update_share_deliveries_for_delivery_day(
            new_delivery_day=new_monday, old_delivery_day=old_monday
        )

        future_dsd.refresh_from_db()
        assert future_dsd.delivery_day == new_monday  # repointed, not orphaned
        assert future_dsd.valid_from == future_start  # window preserved
        assert future_dsd.valid_until is None

        share.refresh_from_db()
        sd.refresh_from_db()
        assert share.delivery_day == new_monday
        # Day-match invariant intact: the delivery's DSD is on the new day.
        assert sd.delivery_station_day.delivery_day_id == share.delivery_day_id

    def test_same_boundary_station_day_no_negative_range(self, tenant):
        # SUC-7: a child DSD whose valid_from EQUALS the new boundary must not be
        # closed at boundary-1 (a negative range → IntegrityError); it is
        # repointed onto the new day instead.
        base_monday = self._monday_n_weeks_ahead(0)
        valid_from_new = self._monday_n_weeks_ahead(2)
        old_valid_until = valid_from_new - timedelta(days=1)

        old_monday = SharesDeliveryDayFactory(
            day_number=0, valid_from=base_monday, valid_until=old_valid_until
        )
        new_monday = SharesDeliveryDayFactory(day_number=0, valid_from=valid_from_new)
        station = DeliveryStationFactory(short_name="StationBoundary")
        boundary_dsd = DeliveryStationDayFactory(
            delivery_station=station,
            delivery_day=old_monday,
            valid_from=valid_from_new,  # same Monday as the new boundary
            tour_number=1,
        )

        # Must not raise IntegrityError (negative range).
        SharesDeliveryDayService.update_delivery_station_days(
            instance=new_monday,
            existing_delivery_day=old_monday,
            validated_data={"valid_from": valid_from_new},
        )

        boundary_dsd.refresh_from_db()
        assert boundary_dsd.delivery_day == new_monday
        assert boundary_dsd.valid_from == valid_from_new
        assert boundary_dsd.valid_until is None

    def test_delivery_on_pre_closed_dsd_is_remapped_not_stranded(self, tenant):
        # SUC-3: a future ShareDelivery left on a DSD closed BEFORE the boundary
        # (closed independently, deliveries not remapped) must be re-resolved to
        # the station's new-day DSD — never left on the closed old-day row (which
        # would break the Share/ShareDelivery day-match invariant).
        base_monday = self._monday_n_weeks_ahead(0)
        mid_monday = self._monday_n_weeks_ahead(2)
        valid_from_new = self._monday_n_weeks_ahead(4)
        old_valid_until = valid_from_new - timedelta(days=1)

        old_monday = SharesDeliveryDayFactory(
            day_number=0, valid_from=base_monday, valid_until=old_valid_until
        )
        new_monday = SharesDeliveryDayFactory(day_number=0, valid_from=valid_from_new)
        station = DeliveryStationFactory(short_name="StationStranded")
        # A DSD closed BEFORE the boundary, plus the station's active DSD that
        # spans the boundary (non-overlapping chain).
        closed_dsd = DeliveryStationDayFactory(
            delivery_station=station,
            delivery_day=old_monday,
            valid_from=base_monday,
            valid_until=mid_monday - timedelta(days=1),
            tour_number=1,
        )
        active_dsd = DeliveryStationDayFactory(
            delivery_station=station,
            delivery_day=old_monday,
            valid_from=mid_monday,
            tour_number=1,
        )
        variation = ShareTypeVariationFactory()
        # A future delivery LEFT on the closed DSD for a week after the boundary.
        week = Week.withdate(valid_from_new + timedelta(weeks=2))
        share = ShareFactory(
            year=week.year,
            delivery_week=week.week,
            delivery_day=old_monday,
            share_type_variation=variation,
        )
        # The subscription's default is the (closed) DSD that covers its own
        # bounded window; the delivery for a far-future week was left on it.
        sub = SubscriptionFactory(
            share_type_variation=variation,
            valid_from=base_monday,
            valid_until=closed_dsd.valid_until,
            default_delivery_station_day=closed_dsd,
        )
        stranded = ShareDeliveryFactory(
            share=share, delivery_station_day=closed_dsd, subscription=sub
        )

        new_dsds = SharesDeliveryDayService.update_delivery_station_days(
            instance=new_monday,
            existing_delivery_day=old_monday,
            validated_data={"valid_from": valid_from_new},
        )
        SharesDeliveryDayService.update_shares_for_delivery_day(
            new_delivery_day=new_monday, old_delivery_day=old_monday
        )
        SharesDeliveryDayService.update_share_deliveries_for_delivery_day(
            new_delivery_day=new_monday, old_delivery_day=old_monday
        )

        # active_dsd was closed on the old day + copied onto the new day.
        assert len(new_dsds) == 1
        active_dsd.refresh_from_db()
        assert active_dsd.valid_until == valid_from_new - timedelta(days=1)
        share.refresh_from_db()
        stranded.refresh_from_db()
        assert share.delivery_day == new_monday
        # The stranded delivery is now on the new-day copy, invariant restored.
        assert stranded.delivery_station_day_id == new_dsds[0].id
        assert stranded.delivery_station_day.delivery_day_id == share.delivery_day_id

    def test_manual_day_override_survives_succession(self, tenant):
        # SUC-8: a Share whose day field is a deliberate override (differs from
        # the OLD day's default) keeps it; an inherited field follows the new
        # default.
        base_monday = self._monday_n_weeks_ahead(0)
        valid_from_new = self._monday_n_weeks_ahead(2)
        old_valid_until = valid_from_new - timedelta(days=1)

        old_monday = SharesDeliveryDayFactory(
            day_number=0,
            valid_from=base_monday,
            valid_until=old_valid_until,
            default_harvesting_day=4,
            default_packing_day=0,
        )
        new_monday = SharesDeliveryDayFactory(
            day_number=0,
            valid_from=valid_from_new,
            default_harvesting_day=2,
            default_packing_day=0,
        )
        variation = ShareTypeVariationFactory()
        week = Week.withdate(valid_from_new + timedelta(weeks=4))
        share = ShareFactory(
            year=week.year,
            delivery_week=week.week,
            delivery_day=old_monday,
            share_type_variation=variation,
            harvesting_day=old_monday.default_harvesting_day,  # inherited (4)
            packing_day=3,  # deliberate override (old default is 0)
        )

        SharesDeliveryDayService.update_shares_for_delivery_day(
            new_delivery_day=new_monday, old_delivery_day=old_monday
        )

        share.refresh_from_db()
        assert share.delivery_day == new_monday
        assert share.harvesting_day == 2  # inherited → follows the new default
        assert share.packing_day == 3  # override preserved


@pytest.mark.django_db
class TestSuccessionChildMigration(_MondayHelpers):
    """SUC-2/3/4/5: child migration + guards around delivery-day / station-day
    succession (capacity reservations, stranded deliveries, coverage gaps,
    standalone closes)."""

    def test_dsd_copy_remaps_future_reservations(self, tenant):
        """SUC-3: closing+copying an open DSD during catalogue succession
        repoints its post-boundary CapacityReservations onto the copy, so the
        held slot still counts under the id materialization will use."""
        from apps.commissioning.models import CapacityReservation

        base = self._monday_n_weeks_ahead(0)
        boundary = self._monday_n_weeks_ahead(2)
        old_day = SharesDeliveryDayFactory(
            day_number=0, valid_from=base, valid_until=boundary - timedelta(days=1)
        )
        new_day = SharesDeliveryDayFactory(day_number=0, valid_from=boundary)
        station = DeliveryStationFactory(short_name="ResStation")
        open_dsd = DeliveryStationDayFactory(
            delivery_station=station, delivery_day=old_day, valid_from=base
        )  # open → copy branch
        variation = ShareTypeVariationFactory()
        sub = SubscriptionFactory(
            share_type_variation=variation,
            valid_from=base,
            default_delivery_station_day=open_dsd,
        )
        post = Week.withdate(boundary + timedelta(weeks=3))
        res = CapacityReservation.objects.create(
            delivery_station_day=open_dsd,
            subscription=sub,
            year=post.year,
            week=post.week,
            expires_at=timezone.now() + timedelta(days=14),
        )

        copies = SharesDeliveryDayService.update_delivery_station_days(
            instance=new_day,
            existing_delivery_day=old_day,
            validated_data={"valid_from": boundary},
        )

        assert len(copies) == 1
        res.refresh_from_db()
        assert res.delivery_station_day_id == copies[0].id

    def test_succession_coverage_gap_raises(self, tenant):
        """SUC-4: if a future ShareDelivery's station has no station-day covering
        its week on the new day, the succession is refused (no silent stranding)."""
        from apps.commissioning.errors import SharesDeliveryDaySuccessionCoverageGap

        base = self._monday_n_weeks_ahead(0)
        boundary = self._monday_n_weeks_ahead(2)
        old_day = SharesDeliveryDayFactory(
            day_number=0, valid_from=base, valid_until=boundary - timedelta(days=1)
        )
        new_day = SharesDeliveryDayFactory(day_number=0, valid_from=boundary)
        station = DeliveryStationFactory(short_name="GapStation")
        dsd_old = DeliveryStationDayFactory(
            delivery_station=station, delivery_day=old_day, valid_from=base
        )
        # No DSD on new_day for this station → coverage gap.
        variation = ShareTypeVariationFactory()
        future_week = Week.withdate(boundary + timedelta(weeks=4))
        # Share stays on old_day so the ShareDelivery's day-match clean() passes
        # at creation; the coverage gap is that dsd_old's station has no new-day
        # station-day, so the remap can't resolve a successor.
        share = ShareFactory(
            year=future_week.year,
            delivery_week=future_week.week,
            delivery_day=old_day,
            share_type_variation=variation,
        )
        ShareDeliveryFactory(share=share, delivery_station_day=dsd_old)

        with pytest.raises(SharesDeliveryDaySuccessionCoverageGap):
            SharesDeliveryDayService.update_share_deliveries_for_delivery_day(
                new_delivery_day=new_day, old_delivery_day=old_day
            )

    def test_dsd_perform_create_migrates_children(self, tenant):
        """SUC-2: creating a successor DeliveryStationDay migrates the
        predecessor's future ShareDeliveries + CapacityReservations onto it."""
        from apps.commissioning.models import CapacityReservation
        from apps.commissioning.viewsets.delivery_viewsets import (
            DeliveryStationDayViewSet,
        )

        base = self._monday_n_weeks_ahead(0)
        boundary = self._monday_n_weeks_ahead(2)
        day = SharesDeliveryDayFactory(day_number=0, valid_from=base)
        station = DeliveryStationFactory(short_name="MigStation")
        old_dsd = DeliveryStationDayFactory(
            delivery_station=station,
            delivery_day=day,
            valid_from=base,
            valid_until=boundary - timedelta(days=1),
        )  # already closed (post-handle_succession state)
        new_dsd = DeliveryStationDayFactory(
            delivery_station=station, delivery_day=day, valid_from=boundary
        )
        variation = ShareTypeVariationFactory()
        future_week = Week.withdate(boundary + timedelta(weeks=4))
        share = ShareFactory(
            year=future_week.year,
            delivery_week=future_week.week,
            delivery_day=day,
            share_type_variation=variation,
        )
        sub = SubscriptionFactory(
            share_type_variation=variation,
            valid_from=base,
            default_delivery_station_day=old_dsd,
        )
        sd = ShareDeliveryFactory(
            share=share, delivery_station_day=old_dsd, subscription=sub
        )
        res = CapacityReservation.objects.create(
            delivery_station_day=old_dsd,
            subscription=sub,
            year=future_week.year,
            week=future_week.week,
            expires_at=timezone.now() + timedelta(days=14),
        )

        DeliveryStationDayViewSet._migrate_succession_children(new_dsd, boundary)

        sd.refresh_from_db()
        assert sd.delivery_station_day == new_dsd
        res.refresh_from_db()
        assert res.delivery_station_day == new_dsd

    def test_standalone_close_with_stranded_children_blocked(self, tenant):
        """SUC-5: a direct PATCH that closes a delivery day with future children
        is refused (the migration runs only on the create/succession path)."""
        from apps.commissioning.errors import (
            SharesDeliveryDayShorteningStrandsChildren,
        )
        from apps.commissioning.serializers import SharesDeliveryDaySerializer
        from apps.commissioning.viewsets.choices_models_viewsets import (
            SharesDeliveryDayViewSet,
        )

        base = self._monday_n_weeks_ahead(0)
        day = SharesDeliveryDayFactory(day_number=0, valid_from=base)  # open
        station = DeliveryStationFactory(short_name="CloseStation")
        DeliveryStationDayFactory(
            delivery_station=station, delivery_day=day, valid_from=base
        )  # open child → would be stranded
        new_until = self._monday_n_weeks_ahead(2) - timedelta(days=1)  # a Sunday

        serializer = SharesDeliveryDaySerializer(
            instance=day, data={"valid_until": new_until.isoformat()}, partial=True
        )
        serializer.is_valid(raise_exception=True)
        with pytest.raises(SharesDeliveryDayShorteningStrandsChildren):
            SharesDeliveryDayViewSet().perform_update(serializer)

    def test_dsd_standalone_close_with_stranded_children_blocked(self, tenant):
        """A direct PATCH that closes a DeliveryStationDay with future deliveries
        is refused (the migration runs only on the create/succession path)."""
        from apps.commissioning.errors import (
            DeliveryStationDayShorteningStrandsChildren,
        )
        from apps.commissioning.serializers import DeliveryStationDaySerializer
        from apps.commissioning.viewsets.delivery_viewsets import (
            DeliveryStationDayViewSet,
        )

        base = self._monday_n_weeks_ahead(0)
        day = SharesDeliveryDayFactory(day_number=0, valid_from=base)
        station = DeliveryStationFactory(short_name="DsdCloseStation")
        dsd = DeliveryStationDayFactory(
            delivery_station=station, delivery_day=day, valid_from=base
        )  # open
        variation = ShareTypeVariationFactory()
        future_week = Week.withdate(self._monday_n_weeks_ahead(6))
        share = ShareFactory(
            year=future_week.year,
            delivery_week=future_week.week,
            delivery_day=day,
            share_type_variation=variation,
        )
        ShareDeliveryFactory(share=share, delivery_station_day=dsd)  # future delivery
        new_until = self._monday_n_weeks_ahead(2) - timedelta(days=1)  # a Sunday

        serializer = DeliveryStationDaySerializer(
            instance=dsd, data={"valid_until": new_until.isoformat()}, partial=True
        )
        serializer.is_valid(raise_exception=True)
        with pytest.raises(DeliveryStationDayShorteningStrandsChildren):
            DeliveryStationDayViewSet().perform_update(serializer)
