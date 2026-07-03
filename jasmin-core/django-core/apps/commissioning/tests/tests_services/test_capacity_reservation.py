"""Tests for delivery-station-day capacity enforcement via CapacityReservation.

Covers the whole behaviour:
  * occupancy = confirmed deliveries + active (non-expired) reservations
  * reserve_for_subscription: success / over-capacity / no-op cases / re-reserve
  * confirm-time backstop (assert_capacity_available_for_confirm)
  * release + CASCADE on subscription delete + TTL expiry
  * assert_share_delivery_fits (the per-week move check)
  * end-to-end: create_bare_subscription reserves, confirm materialises +
    releases (no double-count)
"""

from __future__ import annotations

import datetime

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.commissioning.errors import DeliveryStationOverCapacity
from apps.commissioning.models import CapacityReservation, ShareDelivery
from apps.commissioning.services.capacity_reservation_service import (
    CapacityReservationService,
)
from apps.commissioning.services.share_demand_service import ShareDemandService
from apps.commissioning.services.subscription_service import SubscriptionService
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    MemberFactory,
    ShareDeliveryFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)
from apps.commissioning.tests.factories.members import PaymentCycleFactory

HARVEST = ["HARVEST_SHARE", "HARVEST_SHARE_FRUIT"]
DAY_NUMBER = 2  # Wednesday — matches SharesDeliveryDayFactory default


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #
def _future():
    return timezone.now() + datetime.timedelta(days=1)


def _past():
    return timezone.now() - datetime.timedelta(days=1)


def _make_dsd(*, capacity=None, day_number=DAY_NUMBER):
    dd = SharesDeliveryDayFactory(day_number=day_number)
    return DeliveryStationDayFactory(delivery_day=dd, capacity=capacity)


def _make_subscription(
    *,
    dsd,
    valid_from=datetime.date(2026, 1, 5),
    valid_until=datetime.date(2026, 1, 11),
    share_option="HARVEST_SHARE",
):
    """A draft (unconfirmed) subscription whose default station-day is ``dsd``."""
    share_type = ShareTypeFactory(share_option=share_option)
    variation = ShareTypeVariationFactory(share_type=share_type)
    return SubscriptionFactory(
        share_type_variation=variation,
        default_delivery_station_day=dsd,
        valid_from=valid_from,
        valid_until=valid_until,
    )


def _fill_one_slot(dsd, year, week):
    """Create one confirmed harvest ShareDelivery occupying ``dsd`` that week."""
    share_type = ShareTypeFactory(share_option="HARVEST_SHARE")
    variation = ShareTypeVariationFactory(share_type=share_type)
    share = ShareFactory(
        year=year,
        delivery_week=week,
        share_type_variation=variation,
        delivery_day=dsd.delivery_day,
    )
    return ShareDeliveryFactory(share=share, delivery_station_day=dsd)


def _occupy(dsd, year, week, quantity):
    """Occupy ``quantity`` slots at ``dsd`` for ``(year, week)`` via ONE active
    reservation. A single quantity-weighted hold (vs ``quantity`` separate
    ``_fill_one_slot`` deliveries) avoids the ShareTypeVariation
    one-open-per-(type,size) constraint: the factory get_or_creates a single
    HARVEST_SHARE ShareType and cycles ``size``, so many variations collide."""
    sub = _make_subscription(dsd=dsd)
    sub.quantity = quantity
    sub.save(update_fields=["quantity"])
    CapacityReservation.objects.create(
        subscription=sub,
        delivery_station_day=dsd,
        year=year,
        week=week,
        expires_at=_future(),
    )
    return sub


def _period_weeks(sub):
    return SubscriptionService._get_delivery_weeks(
        sub.valid_from,
        sub.valid_until,
        sub.default_delivery_station_day.delivery_day.day_number,
    )


# --------------------------------------------------------------------------- #
# Occupancy counting                                                          #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestOccupancyCountsReservations:
    def test_active_reservation_counts_toward_occupancy(self, tenant):
        dsd = _make_dsd(capacity=10)
        sub = _make_subscription(dsd=dsd)
        CapacityReservation.objects.create(
            subscription=sub,
            delivery_station_day=dsd,
            year=2026,
            week=2,
            expires_at=_future(),
        )
        assert (
            ShareDemandService.share_option_capacity_count(
                delivery_station_day_id=dsd.id,
                year=2026,
                delivery_week=2,
                share_options=HARVEST,
            )
            == 1
        )

    def test_expired_reservation_does_not_count(self, tenant):
        dsd = _make_dsd(capacity=10)
        sub = _make_subscription(dsd=dsd)
        CapacityReservation.objects.create(
            subscription=sub,
            delivery_station_day=dsd,
            year=2026,
            week=2,
            expires_at=_past(),  # lapsed
        )
        assert (
            ShareDemandService.share_option_capacity_count(
                delivery_station_day_id=dsd.id,
                year=2026,
                delivery_week=2,
                share_options=HARVEST,
            )
            == 0
        )

    def test_deliveries_plus_reservations_sum(self, tenant):
        dsd = _make_dsd(capacity=10)
        sub = _make_subscription(dsd=dsd)
        _fill_one_slot(dsd, 2026, 2)  # 1 confirmed delivery
        CapacityReservation.objects.create(
            subscription=sub,
            delivery_station_day=dsd,
            year=2026,
            week=2,
            expires_at=_future(),
        )
        assert (
            ShareDemandService.share_option_capacity_count(
                delivery_station_day_id=dsd.id,
                year=2026,
                delivery_week=2,
                share_options=HARVEST,
            )
            == 2
        )

    def test_batched_counts_include_reservations(self, tenant):
        dsd = _make_dsd(capacity=10)
        sub = _make_subscription(dsd=dsd)
        _fill_one_slot(dsd, 2026, 2)
        CapacityReservation.objects.create(
            subscription=sub,
            delivery_station_day=dsd,
            year=2026,
            week=2,
            expires_at=_future(),
        )
        counts = ShareDemandService.capacity_counts_by_week(
            station_day_ids=[dsd.id],
            year_weeks=[(2026, 2)],
            share_options=HARVEST,
        )
        assert counts.get((dsd.id, 2026, 2)) == 2


# --------------------------------------------------------------------------- #
# reserve_for_subscription                                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestReserveForSubscription:
    def test_reserves_one_row_per_period_week(self, tenant):
        dsd = _make_dsd(capacity=10)
        sub = _make_subscription(
            dsd=dsd, valid_until=datetime.date(2026, 1, 25)
        )  # ~3 Wednesdays
        weeks = _period_weeks(sub)
        assert len(weeks) >= 2

        CapacityReservationService.reserve_for_subscription(sub)

        rows = CapacityReservation.objects.filter(subscription=sub)
        assert rows.count() == len(weeks)
        assert {(r.year, r.week) for r in rows} == set(weeks)

    def test_full_week_raises_and_creates_nothing(self, tenant):
        dsd = _make_dsd(capacity=1)
        sub = _make_subscription(dsd=dsd)  # single week (2026, 2)
        year, week = _period_weeks(sub)[0]
        _fill_one_slot(dsd, year, week)  # capacity now 1/1 = full

        with pytest.raises(DeliveryStationOverCapacity):
            CapacityReservationService.reserve_for_subscription(sub)

        assert not CapacityReservation.objects.filter(subscription=sub).exists()

    def test_reserve_rejects_multi_quantity_that_overfills(self, tenant):
        # capacity 10, 9 already taken; a quantity=3 sub needs 3 slots, so
        # 9 + 3 = 12 > 10 — must be refused and reserve nothing (pre-fix the
        # check was occupied >= capacity, i.e. 9 >= 10 False, so it slipped in).
        dsd = _make_dsd(capacity=10)
        sub = _make_subscription(dsd=dsd)
        sub.quantity = 3
        sub.save(update_fields=["quantity"])
        year, week = _period_weeks(sub)[0]
        _occupy(dsd, year, week, 9)

        with pytest.raises(DeliveryStationOverCapacity):
            CapacityReservationService.reserve_for_subscription(sub)
        assert not CapacityReservation.objects.filter(subscription=sub).exists()

    def test_noop_when_no_capacity_limit(self, tenant):
        dsd = _make_dsd(capacity=None)  # unlimited
        sub = _make_subscription(dsd=dsd)
        CapacityReservationService.reserve_for_subscription(sub)
        assert not CapacityReservation.objects.filter(subscription=sub).exists()

    def test_reserves_against_per_week_successor_dsd(self, tenant):
        # MEM-5: a time-bounded default DSD hands off to a successor mid-term;
        # reservations must land on the per-week DSD materialization will write
        # to, not all on the default (so the successor's capacity is enforced).
        from apps.commissioning.tests.factories import DeliveryStationFactory

        station = DeliveryStationFactory()
        day = SharesDeliveryDayFactory(day_number=DAY_NUMBER)
        default_dsd = DeliveryStationDayFactory(
            delivery_station=station,
            delivery_day=day,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 1, 18),  # Sunday — covers wks 2,3
            capacity=10,
        )
        successor_dsd = DeliveryStationDayFactory(
            delivery_station=station,
            delivery_day=day,
            valid_from=datetime.date(2026, 1, 19),  # Monday — covers wks 4,5
            capacity=10,
        )
        sub = _make_subscription(
            dsd=default_dsd,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 2, 1),  # Sunday
        )

        CapacityReservationService.reserve_for_subscription(sub)

        dsd_ids = set(
            CapacityReservation.objects.filter(subscription=sub).values_list(
                "delivery_station_day_id", flat=True
            )
        )
        # Early weeks reserved the default; the handoff weeks reserved the
        # successor (pre-fix everything was pinned to the default DSD).
        assert default_dsd.id in dsd_ids
        assert successor_dsd.id in dsd_ids

    def test_noop_for_non_harvest_share_option(self, tenant):
        dsd = _make_dsd(capacity=1)
        sub = _make_subscription(dsd=dsd, share_option="CHICKEN_SHARE")
        CapacityReservationService.reserve_for_subscription(sub)
        assert not CapacityReservation.objects.filter(subscription=sub).exists()

    def test_re_reserve_replaces_old_rows(self, tenant):
        dsd_a = _make_dsd(capacity=10)
        sub = _make_subscription(dsd=dsd_a)
        CapacityReservationService.reserve_for_subscription(sub)
        assert CapacityReservation.objects.filter(
            subscription=sub, delivery_station_day=dsd_a
        ).exists()

        # Move to a different station-day and re-reserve. Use a distinct
        # ``day_number`` so the second SharesDeliveryDay doesn't trip the
        # time-bound overlap guard (which is scoped per day_number).
        dsd_b = _make_dsd(capacity=10, day_number=3)
        sub.default_delivery_station_day = dsd_b
        sub.save(update_fields=["default_delivery_station_day"])
        CapacityReservationService.reserve_for_subscription(sub)

        assert not CapacityReservation.objects.filter(
            subscription=sub, delivery_station_day=dsd_a
        ).exists()
        assert CapacityReservation.objects.filter(
            subscription=sub, delivery_station_day=dsd_b
        ).exists()

    def test_own_prior_reservation_does_not_block_re_reserve(self, tenant):
        # capacity 1: the sub's own existing hold must not count against it.
        dsd = _make_dsd(capacity=1)
        sub = _make_subscription(dsd=dsd)
        CapacityReservationService.reserve_for_subscription(sub)
        # Re-reserve (same DSD/period) — should succeed, not see itself as full.
        CapacityReservationService.reserve_for_subscription(sub)
        assert CapacityReservation.objects.filter(subscription=sub).count() == 1


# --------------------------------------------------------------------------- #
# Confirm-time backstop                                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestConfirmBackstop:
    def test_passes_when_own_hold_is_active(self, tenant):
        dsd = _make_dsd(capacity=1)
        sub = _make_subscription(dsd=dsd)
        CapacityReservationService.reserve_for_subscription(sub)
        # Our hold holds the only slot → confirm check passes.
        CapacityReservationService.assert_capacity_available_for_confirm(sub)

    def test_raises_when_hold_lapsed_and_slot_taken(self, tenant):
        dsd = _make_dsd(capacity=1)
        sub = _make_subscription(dsd=dsd)
        year, week = _period_weeks(sub)[0]
        # Our hold expired; someone else's delivery took the slot.
        CapacityReservation.objects.create(
            subscription=sub,
            delivery_station_day=dsd,
            year=year,
            week=week,
            expires_at=_past(),
        )
        _fill_one_slot(dsd, year, week)

        with pytest.raises(DeliveryStationOverCapacity):
            CapacityReservationService.assert_capacity_available_for_confirm(sub)

    def test_multi_quantity_own_hold_discounted_by_quantity(self, tenant):
        # A quantity=3 subscription holds ONE reservation row but contributes 3
        # to the quantity-weighted occupancy, so the own-hold discount must be 3
        # (not the row count 1). capacity 10, 6 other occupants + our quantity=3
        # hold: others(6) + quantity(3) = 9 <= 10 → fits. With a row-count
        # discount the check over-counts to (9-1)+3 = 11 > 10 and falsely refuses.
        dsd = _make_dsd(capacity=10)
        sub = _make_subscription(dsd=dsd)
        sub.quantity = 3
        sub.save(update_fields=["quantity"])
        year, week = _period_weeks(sub)[0]
        _occupy(dsd, year, week, 6)

        CapacityReservationService.reserve_for_subscription(sub)
        # Must not raise: others(6) + our quantity(3) = 9 fits in capacity 10.
        CapacityReservationService.assert_capacity_available_for_confirm(sub)

    def test_confirm_rejects_multi_quantity_when_hold_lapsed(self, tenant):
        # Our reservation lapsed (own=0) and others now fill 9 of 10. A
        # quantity=3 confirm needs 3 slots → others(9) + 3 = 12 > 10. Pre-fix the
        # check was (total - own) >= capacity, i.e. 9 >= 10 False → admitted.
        dsd = _make_dsd(capacity=10)
        sub = _make_subscription(dsd=dsd)
        sub.quantity = 3
        sub.save(update_fields=["quantity"])
        year, week = _period_weeks(sub)[0]
        CapacityReservation.objects.create(
            subscription=sub,
            delivery_station_day=dsd,
            year=year,
            week=week,
            expires_at=_past(),  # lapsed → not our own active hold
        )
        _occupy(dsd, year, week, 9)

        with pytest.raises(DeliveryStationOverCapacity):
            CapacityReservationService.assert_capacity_available_for_confirm(sub)


# --------------------------------------------------------------------------- #
# Release / CASCADE / TTL                                                     #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestReleaseAndLifecycle:
    def test_release_deletes_reservations(self, tenant):
        dsd = _make_dsd(capacity=10)
        sub = _make_subscription(dsd=dsd)
        CapacityReservationService.reserve_for_subscription(sub)
        assert CapacityReservation.objects.filter(subscription=sub).exists()

        CapacityReservationService.release_for_subscription(sub)
        assert not CapacityReservation.objects.filter(subscription=sub).exists()

    def test_deleting_subscription_cascades_reservations(self, tenant):
        dsd = _make_dsd(capacity=10)
        sub = _make_subscription(dsd=dsd)
        CapacityReservationService.reserve_for_subscription(sub)
        sub_id = sub.id
        sub.delete()
        assert not CapacityReservation.objects.filter(subscription_id=sub_id).exists()


# --------------------------------------------------------------------------- #
# assert_share_delivery_fits (per-week move check)                            #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestAssertShareDeliveryFits:
    def test_raises_when_target_full(self, tenant):
        dsd = _make_dsd(capacity=1)
        _fill_one_slot(dsd, 2026, 2)
        with pytest.raises(DeliveryStationOverCapacity):
            CapacityReservationService.assert_share_delivery_fits(
                delivery_station_day_id=dsd.id,
                year=2026,
                week=2,
                share_option="HARVEST_SHARE",
            )

    def test_passes_with_room(self, tenant):
        dsd = _make_dsd(capacity=2)
        _fill_one_slot(dsd, 2026, 2)  # 1/2
        # Should not raise.
        CapacityReservationService.assert_share_delivery_fits(
            delivery_station_day_id=dsd.id,
            year=2026,
            week=2,
            share_option="HARVEST_SHARE",
        )

    def test_noop_for_non_harvest(self, tenant):
        dsd = _make_dsd(capacity=1)
        _fill_one_slot(dsd, 2026, 2)
        # Non-harvest never blocks (capacity is harvest-only).
        CapacityReservationService.assert_share_delivery_fits(
            delivery_station_day_id=dsd.id,
            year=2026,
            week=2,
            share_option="CHICKEN_SHARE",
        )

    def test_noop_when_no_capacity_limit(self, tenant):
        dsd = _make_dsd(capacity=None)
        _fill_one_slot(dsd, 2026, 2)
        CapacityReservationService.assert_share_delivery_fits(
            delivery_station_day_id=dsd.id,
            year=2026,
            week=2,
            share_option="HARVEST_SHARE",
        )

    def test_moving_delivery_already_here_is_discounted(self, tenant):
        # capacity 1, the only occupant IS the delivery being "moved" (a
        # no-op re-save onto the same DSD) → must not block.
        dsd = _make_dsd(capacity=1)
        delivery = _fill_one_slot(dsd, 2026, 2)
        CapacityReservationService.assert_share_delivery_fits(
            delivery_station_day_id=dsd.id,
            year=2026,
            week=2,
            share_option="HARVEST_SHARE",
            moving_delivery_id=delivery.id,
        )

    def test_rejects_multi_quantity_move_that_overfills(self, tenant):
        # Target has 8 occupants (cap 10); moving in a quantity=3 delivery from
        # another station-day needs 3 slots → 8 + 3 = 11 > 10. Pre-fix the check
        # was occupied >= capacity (8 >= 10 False) with a flat -1 self-discount.
        target = _make_dsd(capacity=10)
        _occupy(target, 2026, 2, 8)
        source = _make_dsd(capacity=100, day_number=3)
        sub = _make_subscription(dsd=source)
        sub.quantity = 3
        sub.save(update_fields=["quantity"])
        share = ShareFactory(
            year=2026,
            delivery_week=2,
            share_type_variation=sub.share_type_variation,
            delivery_day=source.delivery_day,
        )
        moving = ShareDeliveryFactory(share=share, delivery_station_day=source)
        moving.subscription = sub
        moving.save(update_fields=["subscription"])

        with pytest.raises(DeliveryStationOverCapacity):
            CapacityReservationService.assert_share_delivery_fits(
                delivery_station_day_id=target.id,
                year=2026,
                week=2,
                share_option="HARVEST_SHARE",
                moving_delivery_id=moving.id,
            )


# --------------------------------------------------------------------------- #
# End-to-end through the SubscriptionService                                  #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestEndToEnd:
    def test_create_bare_subscription_reserves(self, tenant):
        dsd = _make_dsd(capacity=10)
        share_type = ShareTypeFactory(share_option="HARVEST_SHARE")
        variation = ShareTypeVariationFactory(share_type=share_type)
        member = MemberFactory()

        # Build validated_data the way the serializer hands it over.
        validated = {
            "member": member.id,
            "share_type_variation": variation.id,
            "valid_from": datetime.date(2026, 1, 5),
            "valid_until": datetime.date(2026, 1, 11),
            "default_delivery_station_day": dsd,
            "quantity": 1,
            "payment_cycle": PaymentCycleFactory(),
        }
        sub = SubscriptionService().create_bare_subscription(validated)
        assert CapacityReservation.objects.filter(subscription=sub).exists()

    def test_confirm_materialises_and_releases_without_double_count(self, tenant):
        dsd = _make_dsd(capacity=1)
        sub = _make_subscription(dsd=dsd)
        CapacityReservationService.reserve_for_subscription(sub)
        year, week = _period_weeks(sub)[0]

        # While reserved: occupancy is 1 (the hold).
        assert (
            ShareDemandService.share_option_capacity_count(
                delivery_station_day_id=dsd.id,
                year=year,
                delivery_week=week,
                share_options=HARVEST,
            )
            == 1
        )

        SubscriptionService().materialize_confirmed_subscription(sub)

        # Reservation released; the real delivery now holds the slot — still 1,
        # not 2 (no double count).
        assert not CapacityReservation.objects.filter(subscription=sub).exists()
        assert ShareDelivery.objects.filter(subscription=sub).exists()
        assert (
            ShareDemandService.share_option_capacity_count(
                delivery_station_day_id=dsd.id,
                year=year,
                delivery_week=week,
                share_options=HARVEST,
            )
            == 1
        )

    def test_second_draft_refused_when_first_filled_last_slot(self, tenant):
        # The A/B scenario: capacity 1. Sub A reserves the slot; sub B's
        # reserve is then refused.
        dsd = _make_dsd(capacity=1)
        sub_a = _make_subscription(dsd=dsd)
        sub_b = _make_subscription(dsd=dsd)

        CapacityReservationService.reserve_for_subscription(sub_a)
        with pytest.raises(DeliveryStationOverCapacity):
            CapacityReservationService.reserve_for_subscription(sub_b)
        assert not CapacityReservation.objects.filter(subscription=sub_b).exists()


# --------------------------------------------------------------------------- #
# Query-count locks (PERF-3): the confirm/reserve capacity checks must NOT     #
# scale their query count with the number of period weeks — they run inside a #
# held ``select_for_update`` lock, so a per-week N+1 serializes concurrent    #
# confirms. The batched ``capacity_counts_by_week`` keeps it constant.        #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestCapacityCheckQueryCounts:
    @staticmethod
    def _queries(fn, sub) -> int:
        with CaptureQueriesContext(connection) as ctx:
            fn(sub)
        return len(ctx.captured_queries)

    def test_confirm_check_is_scale_invariant_in_weeks(self, tenant):
        short = _make_subscription(
            dsd=_make_dsd(capacity=100),
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 1, 11),  # ~1 week
        )
        long_ = _make_subscription(
            # Distinct day_number so the 2nd SharesDeliveryDay doesn't overlap
            # the short one (overlap_unique_fields=("day_number",)).
            dsd=_make_dsd(capacity=100, day_number=3),
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 12, 27),  # ~50 weeks
        )
        fn = CapacityReservationService.assert_capacity_available_for_confirm
        small = self._queries(fn, short)
        large = self._queries(fn, long_)
        assert large - small <= 2, (
            f"confirm capacity check scales with weeks: ~1 week -> {small} "
            f"queries, ~50 weeks -> {large} (delta {large - small})."
        )

    def test_reserve_is_scale_invariant_in_weeks(self, tenant):
        short = _make_subscription(
            dsd=_make_dsd(capacity=100),
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 1, 11),  # ~1 week
        )
        long_ = _make_subscription(
            # Distinct day_number so the 2nd SharesDeliveryDay doesn't overlap
            # the short one (overlap_unique_fields=("day_number",)).
            dsd=_make_dsd(capacity=100, day_number=3),
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 12, 27),  # ~50 weeks
        )
        fn = CapacityReservationService.reserve_for_subscription
        small = self._queries(fn, short)
        large = self._queries(fn, long_)
        # ``reserve`` also does N inserts (bulk_create is one statement, but
        # delete + the counts are the scaling risk) — allow a little more slack
        # than the read-only confirm check.
        assert large - small <= 3, (
            f"reserve capacity check scales with weeks: ~1 week -> {small} "
            f"queries, ~50 weeks -> {large} (delta {large - small})."
        )


@pytest.mark.django_db
class TestCapacityExcludesNonShippingDeliveries:
    """BL-5: capacity occupancy must use the same 'this delivery actually ships'
    predicate as demand — a jokered (joker_taken=True) or opted-out
    (requires_optin + not opted in) delivery does NOT ship that week and must not
    consume a physical pickup slot, else a capped station-day reports phantom
    occupancy and falsely rejects new subscribers/moves."""

    def _dsd(self):
        return DeliveryStationDayFactory(
            delivery_day=SharesDeliveryDayFactory(day_number=DAY_NUMBER), capacity=10
        )

    def _harvest_delivery(
        self, dsd, *, joker=False, requires_optin=False, default_optin_state=False
    ):
        # Distinct variation per call so the (year, week, day, variation) Share
        # uniqueness constraint is satisfied while all count under HARVEST_SHARE.
        variation = ShareTypeVariationFactory(
            share_type=ShareTypeFactory(share_option="HARVEST_SHARE"),
            requires_optin=requires_optin,
            default_optin_state=default_optin_state,
        )
        share = ShareFactory(
            year=2026,
            delivery_week=2,
            share_type_variation=variation,
            delivery_day=dsd.delivery_day,
        )
        return ShareDeliveryFactory(
            share=share, delivery_station_day=dsd, joker_taken=joker
        )

    def _count(self, dsd):
        return ShareDemandService.share_option_capacity_count(
            delivery_station_day_id=dsd.id,
            year=2026,
            delivery_week=2,
            share_options=HARVEST,
        )

    def test_normal_delivery_counts(self, tenant):
        dsd = self._dsd()
        self._harvest_delivery(dsd)
        assert self._count(dsd) == 1

    def test_jokered_delivery_excluded(self, tenant):
        dsd = self._dsd()
        self._harvest_delivery(dsd)  # ships → counts
        self._harvest_delivery(dsd, joker=True)  # jokered → must NOT count
        assert self._count(dsd) == 1

    def test_opted_out_delivery_excluded(self, tenant):
        dsd = self._dsd()
        self._harvest_delivery(dsd)  # ships → counts
        # requires_optin + default_optin_state=False → is_opted_in=False → opted out
        self._harvest_delivery(dsd, requires_optin=True, default_optin_state=False)
        assert self._count(dsd) == 1

    def test_batched_and_peak_also_exclude(self, tenant):
        dsd = self._dsd()
        self._harvest_delivery(dsd)
        self._harvest_delivery(dsd, joker=True)
        self._harvest_delivery(dsd, requires_optin=True, default_optin_state=False)
        by_week = ShareDemandService.capacity_counts_by_week(
            station_day_ids=[dsd.id],
            year_weeks=[(2026, 2)],
            share_options=HARVEST,
        )
        assert by_week.get((dsd.id, 2026, 2)) == 1
        peak, _y, _w = ShareDemandService.peak_occupied_from_week(
            delivery_station_day_id=dsd.id,
            from_year=2026,
            from_week=1,
            share_options=HARVEST,
        )
        assert peak == 1


@pytest.mark.django_db
class TestAssertRestoreFits:
    """BIZ-6: un-pausing a DeliveryExceptionPeriod re-materialises paused
    deliveries — but the freed slots may have been taken by new confirmed
    subscriptions while the pause was active, so the restore must not silently
    overbook. ``assert_restore_fits`` raises instead."""

    def test_over_capacity_restore_raises(self, tenant):
        dsd = _make_dsd(capacity=1)
        _fill_one_slot(dsd, 2026, 3)  # slot taken while the variation was paused
        with pytest.raises(DeliveryStationOverCapacity):
            CapacityReservationService.assert_restore_fits(
                delivery_station_day_id=dsd.id,
                year=2026,
                week=3,
                share_option="HARVEST_SHARE",
                quantity=1,
            )

    def test_restore_within_capacity_ok(self, tenant):
        dsd = _make_dsd(capacity=2)
        _fill_one_slot(dsd, 2026, 3)  # occupied 1 of 2
        # Restoring one more fits exactly (2 <= 2) — no raise.
        CapacityReservationService.assert_restore_fits(
            delivery_station_day_id=dsd.id,
            year=2026,
            week=3,
            share_option="HARVEST_SHARE",
            quantity=1,
        )

    def test_unlimited_dsd_never_raises(self, tenant):
        dsd = _make_dsd(capacity=None)
        CapacityReservationService.assert_restore_fits(
            delivery_station_day_id=dsd.id,
            year=2026,
            week=3,
            share_option="HARVEST_SHARE",
            quantity=99,
        )

    def test_non_harvest_option_is_noop(self, tenant):
        dsd = _make_dsd(capacity=1)
        _fill_one_slot(dsd, 2026, 3)
        # A non-capacity-managed share option isn't station-day-limited.
        CapacityReservationService.assert_restore_fits(
            delivery_station_day_id=dsd.id,
            year=2026,
            week=3,
            share_option="COOP_SHARE",
            quantity=5,
        )


# --------------------------------------------------------------------------- #
# Lock-presence (the SOLE concurrency guard)                                   #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestStationDayLockPresence:
    """``select_for_update()`` on the DeliveryStationDay row is the ONLY thing
    stopping two DIFFERENT subscriptions from over-filling a station-day: the
    single DB constraint (``capres_unique_sub_dsd_week``) is per-subscription
    dedup, and reserve/confirm are check-then-insert. Every other capacity test
    is strictly serial and would stay green if the lock were dropped, so these
    assert ``FOR UPDATE`` on the station-day table in the emitted SQL — lock
    removal then fails CI."""

    @staticmethod
    def _station_day_locking_queries(ctx):
        from apps.commissioning.models import DeliveryStationDay

        table = DeliveryStationDay._meta.db_table
        return [
            q["sql"]
            for q in ctx.captured_queries
            if table in q["sql"] and "FOR UPDATE" in q["sql"].upper()
        ]

    def test_reserve_for_subscription_locks_the_station_day(self, tenant):
        dsd = _make_dsd(capacity=10)
        sub = _make_subscription(dsd=dsd, valid_until=datetime.date(2026, 1, 25))

        with CaptureQueriesContext(connection) as ctx:
            CapacityReservationService.reserve_for_subscription(sub)

        assert self._station_day_locking_queries(ctx), (
            "reserve_for_subscription must SELECT ... FOR UPDATE the "
            "DeliveryStationDay row — no such lock found in the emitted SQL. "
            "Without it two subscriptions can both read the last free slot and "
            "both materialise, overbooking the station-day."
        )

    def test_confirm_backstop_locks_the_station_day(self, tenant):
        dsd = _make_dsd(capacity=10)
        sub = _make_subscription(dsd=dsd, valid_until=datetime.date(2026, 1, 25))

        with CaptureQueriesContext(connection) as ctx:
            CapacityReservationService.assert_capacity_available_for_confirm(sub)

        assert self._station_day_locking_queries(ctx), (
            "assert_capacity_available_for_confirm must SELECT ... FOR UPDATE "
            "the DeliveryStationDay row (the confirm-time capacity backstop) — "
            "no such lock found in the emitted SQL."
        )
