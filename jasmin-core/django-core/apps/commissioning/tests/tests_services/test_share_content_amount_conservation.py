"""Amount-conservation tests for ShareContent → Movements / Theoreticals.

These tests fix the formula that turned out to be ambiguous in production:

    SHARECONTENT movement.amount     = -(sc.amount * total_quantity)
    TheoreticalHarvest.amount        =  sc.amount * total_quantity
    TheoreticalPurchase.amount       =  sc.amount * total_quantity
    TheoreticalWashAmount.amount     =  sc.amount * total_quantity
    TheoreticalCleanAmount.amount    =  sc.amount * total_quantity

where ``total_quantity`` is **the sum of subscription.quantity across all
matching ShareDeliveries on the (day, variation)**, NOT the number of
ShareDelivery rows. A bug here looks like:

    sc.amount = 2, one subscription with quantity = 5
      expected: movement -10, theoreticals 10
      buggy:    movement  -5 (treats subscription as a row count, ignoring
                              quantity)

Unlike the rest of this test suite, this file **does not** patch
``batch_get_physical_variation_totals_for_week`` — it builds real
Subscription / ShareDelivery rows so the demand-aggregation SQL is
exercised end-to-end.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from apps.commissioning.models import (
    MovementShareArticle,
    Share,
    ShareContent,
    TheoreticalCleanAmount,
    TheoreticalHarvest,
    TheoreticalPurchase,
    TheoreticalWashAmount,
)
from apps.commissioning.services.share_content_service import ShareContentService
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    ForecastFactory,
    MemberFactory,
    PaymentCycleFactory,
    ShareArticleFactory,
    ShareContentFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
    StorageFactory,
    SubscriptionFactory,
)

# ── Shared fixture builder ──────────────────────────────────────────────
#
# Builds a realistic share-content scenario with the requested subscription
# quantities. Each entry in ``subscription_quantities`` becomes one
# (Subscription, ShareDelivery) pair attached to the same Share — so the
# demand query at `batch_get_physical_variation_totals_for_week` sums them.
#
# The factories require a Storage marked as the short-term harvest storage
# (movement allocation), an article with a forecast (so harvest theoreticals
# fire), and a payment cycle (so the subscription validates).


def _build_scenario(
    *,
    sc_amount: Decimal,
    subscription_quantities: list[int],
    washing: bool = False,
    cleaning: bool = False,
    with_forecast: bool = True,
    year: int = 2026,
    delivery_week: int = 30,
    delivery_day_number: int = 5,  # Saturday
) -> tuple[ShareContent, list[int]]:
    """Set up Share + ShareContent + ShareDeliveries; return (share_content,
    quantities) so the caller can assert against expected totals."""
    storage = StorageFactory(is_short_term_harvest_storage=True)
    article = ShareArticleFactory()
    sdd = SharesDeliveryDayFactory(day_number=delivery_day_number)
    variation = ShareTypeVariationFactory()
    share = ShareFactory(
        year=year,
        delivery_week=delivery_week,
        delivery_day=sdd,
        share_type_variation=variation,
        harvesting_day=1,
        washing_day=1 if washing else None,
        cleaning_day=1 if cleaning else None,
        packing_day=delivery_day_number,
    )
    station = DeliveryStationFactory()
    station_day = DeliveryStationDayFactory(delivery_station=station, delivery_day=sdd)

    forecast = None
    if with_forecast:
        forecast = ForecastFactory(
            share_article=article,
            year=year,
            delivery_week=delivery_week,
            size="M",
            storage=storage,
        )

    # One Subscription + one ShareDelivery per requested quantity.
    payment_cycle = PaymentCycleFactory()
    for qty in subscription_quantities:
        subscription = SubscriptionFactory(
            member=MemberFactory(),
            share_type_variation=variation,
            quantity=qty,
            payment_cycle=payment_cycle,
            default_delivery_station_day=station_day,
            valid_from=datetime.date(year, 1, 5),
        )
        # ShareDelivery row — this is what the demand backend aggregates.
        from apps.commissioning.models import ShareDelivery

        ShareDelivery.objects.create(
            share=share,
            subscription=subscription,
            delivery_station_day=station_day,
        )

    sc = ShareContentFactory(
        share=share,
        share_article=article,
        delivery_station=station,
        amount=sc_amount,
        unit="KG",
        size="M",
        forecast=forecast,
        washing=washing,
        cleaning=cleaning,
    )
    sc = ShareContent.objects.select_related(
        "share__share_type_variation",
        "share__delivery_day",
        "share_article",
        "forecast",
        "seller",
    ).get(pk=sc.pk)
    return sc, subscription_quantities


def _expected_total(sc_amount: Decimal, quantities: list[int]) -> Decimal:
    """The arithmetic the production code is meant to do, expressed once."""
    return Decimal(str(sc_amount)) * Decimal(sum(quantities))


# ── 1) SHARECONTENT movement amount ─────────────────────────────────────
@pytest.mark.django_db
class TestShareContentMovementAmount:
    """The negative SHARECONTENT movement that is created on packing day."""

    def test_single_subscription_with_quantity_5(self, tenant):
        # The exact case the user described: 1 subscription buying 5 shares,
        # ShareContent amount = 2. The bug would show up as -5 (row count)
        # instead of -10 (quantity-aware sum).
        sc, qty = _build_scenario(sc_amount=Decimal("2"), subscription_quantities=[5])
        ShareContentService().create_movements([sc])

        movements = MovementShareArticle.objects.filter(
            share_content=sc, movement_type="SHARECONTENT"
        )
        total = sum(m.amount for m in movements)
        assert total == -_expected_total(Decimal("2"), qty), (
            f"SHARECONTENT movement total wrong for 1 subscription × qty=5. "
            f"Got {total}, expected -{_expected_total(Decimal('2'), qty)}. "
            f"If this is -5, the bug is: subscription.quantity is being "
            f"treated as a row count."
        )

    def test_five_subscriptions_each_quantity_1(self, tenant):
        # Equivalent population — sum is still 5 — but as 5 ShareDelivery rows.
        # If this passes but the previous one fails, the bug is confirmed:
        # the code counts rows, not quantity.
        sc, qty = _build_scenario(
            sc_amount=Decimal("2"), subscription_quantities=[1, 1, 1, 1, 1]
        )
        ShareContentService().create_movements([sc])

        total = sum(
            m.amount
            for m in MovementShareArticle.objects.filter(
                share_content=sc, movement_type="SHARECONTENT"
            )
        )
        assert total == -_expected_total(Decimal("2"), qty)

    def test_mixed_quantities_sum_to_five(self, tenant):
        # 2 + 3 = 5 — independent confirmation of the Sum() semantics.
        sc, qty = _build_scenario(
            sc_amount=Decimal("2"), subscription_quantities=[2, 3]
        )
        ShareContentService().create_movements([sc])

        total = sum(
            m.amount
            for m in MovementShareArticle.objects.filter(
                share_content=sc, movement_type="SHARECONTENT"
            )
        )
        assert total == -_expected_total(Decimal("2"), qty)

    def test_decimal_amount_preserved(self, tenant):
        # sc.amount = 2.5, total = 4 → expected -10.0
        sc, qty = _build_scenario(sc_amount=Decimal("2.5"), subscription_quantities=[4])
        ShareContentService().create_movements([sc])

        total = sum(
            m.amount
            for m in MovementShareArticle.objects.filter(
                share_content=sc, movement_type="SHARECONTENT"
            )
        )
        assert total == -_expected_total(Decimal("2.5"), qty)

    def test_no_subscriptions_means_no_demand(self, tenant):
        # No subscriptions → total_quantity is 0 → no demand. The current
        # implementation still creates a movement with amount 0 (formula
        # falls through). Lock that behavior so we notice if it changes.
        sc, _qty = _build_scenario(sc_amount=Decimal("2"), subscription_quantities=[])
        ShareContentService().create_movements([sc])

        total = sum(
            m.amount
            for m in MovementShareArticle.objects.filter(
                share_content=sc, movement_type="SHARECONTENT"
            )
        )
        assert total == Decimal(
            "0"
        ), f"Expected 0 movement when nobody subscribed; got {total}."


# ── 2) TheoreticalHarvest amount ────────────────────────────────────────
@pytest.mark.django_db
class TestTheoreticalHarvestAmount:
    """The harvest target that drives the harvesting list."""

    def test_quantity_five_single_subscription(self, tenant):
        sc, qty = _build_scenario(sc_amount=Decimal("2"), subscription_quantities=[5])
        ShareContentService().create_all_theoretical_objects([sc])
        ths = list(TheoreticalHarvest.objects.filter(share_content=sc))
        assert len(ths) == 1
        assert Decimal(str(ths[0].amount)) == _expected_total(Decimal("2"), qty)

    def test_quantity_aggregated_across_subscriptions(self, tenant):
        sc, qty = _build_scenario(
            sc_amount=Decimal("3"), subscription_quantities=[2, 3, 4]
        )
        ShareContentService().create_all_theoretical_objects([sc])
        th = TheoreticalHarvest.objects.get(share_content=sc)
        assert Decimal(str(th.amount)) == _expected_total(Decimal("3"), qty)


# ── 3) TheoreticalPurchase amount (purchased articles) ──────────────────
@pytest.mark.django_db
class TestTheoreticalPurchaseAmount:
    """Purchased articles (no forecast) get a TheoreticalPurchase row."""

    def test_quantity_five_single_subscription(self, tenant):
        # No forecast → article must be flagged purchased so the
        # theoretical-purchase branch fires.
        storage = StorageFactory(is_short_term_harvest_storage=True)
        article = ShareArticleFactory(is_purchased=True)
        sdd = SharesDeliveryDayFactory(day_number=5)
        variation = ShareTypeVariationFactory()
        share = ShareFactory(
            year=2026,
            delivery_week=30,
            delivery_day=sdd,
            share_type_variation=variation,
            packing_day=5,
        )
        station = DeliveryStationFactory()
        station_day = DeliveryStationDayFactory(
            delivery_station=station, delivery_day=sdd
        )
        pc = PaymentCycleFactory()
        subscription = SubscriptionFactory(
            member=MemberFactory(),
            share_type_variation=variation,
            quantity=5,
            payment_cycle=pc,
            default_delivery_station_day=station_day,
            valid_from=datetime.date(2026, 1, 5),
        )
        from apps.commissioning.models import ShareDelivery

        ShareDelivery.objects.create(
            share=share, subscription=subscription, delivery_station_day=station_day
        )
        sc = ShareContentFactory(
            share=share,
            share_article=article,
            delivery_station=station,
            amount=Decimal("2"),
            unit="KG",
            size="M",
            forecast=None,
            washing=False,
            cleaning=False,
        )
        sc = ShareContent.objects.select_related(
            "share__share_type_variation",
            "share__delivery_day",
            "share_article",
        ).get(pk=sc.pk)
        # mark storage so storage allocator doesn't choke
        _ = storage

        ShareContentService().create_all_theoretical_objects([sc])

        tp = TheoreticalPurchase.objects.get(share_content=sc)
        assert Decimal(str(tp.amount)) == Decimal("10")


# ── 4) TheoreticalWashAmount + TheoreticalCleanAmount ───────────────────
@pytest.mark.django_db
class TestTheoreticalWashAmount:
    def test_quantity_propagates(self, tenant):
        sc, qty = _build_scenario(
            sc_amount=Decimal("2"), subscription_quantities=[5], washing=True
        )
        ShareContentService().create_all_theoretical_objects([sc])
        tw = TheoreticalWashAmount.objects.get(share_content=sc)
        assert Decimal(str(tw.amount)) == _expected_total(Decimal("2"), qty)


@pytest.mark.django_db
class TestTheoreticalCleanAmount:
    def test_quantity_propagates(self, tenant):
        sc, qty = _build_scenario(
            sc_amount=Decimal("2"), subscription_quantities=[5], cleaning=True
        )
        ShareContentService().create_all_theoretical_objects([sc])
        tc = TheoreticalCleanAmount.objects.get(share_content=sc)
        assert Decimal(str(tc.amount)) == _expected_total(Decimal("2"), qty)


# ── 5) End-to-end: all four objects on one ShareContent ─────────────────
@pytest.mark.django_db
class TestEndToEndOneShareContent:
    """For a washing+cleaning, forecasted article, every downstream object
    should report the same total amount (sc.amount * subscription_qty)."""

    def test_movement_and_all_theoreticals_agree(self, tenant):
        sc, qty = _build_scenario(
            sc_amount=Decimal("2"),
            subscription_quantities=[5],
            washing=True,
            cleaning=True,
        )
        svc = ShareContentService()
        svc.create_all_theoretical_objects([sc])
        svc.create_movements([sc])

        expected = _expected_total(Decimal("2"), qty)

        movement_total = sum(
            m.amount
            for m in MovementShareArticle.objects.filter(
                share_content=sc, movement_type="SHARECONTENT"
            )
        )
        th = TheoreticalHarvest.objects.get(share_content=sc)
        tw = TheoreticalWashAmount.objects.get(share_content=sc)
        tc = TheoreticalCleanAmount.objects.get(share_content=sc)

        assert movement_total == -expected
        assert Decimal(str(th.amount)) == expected
        assert Decimal(str(tw.amount)) == expected
        assert Decimal(str(tc.amount)) == expected


# ── 6) Multiple Share variations in the same week ───────────────────────
#
# Demand from a different variation must NOT bleed into this variation's
# ShareContent. Verifies the (day, variation) keying in
# `batch_get_physical_variation_totals_for_week`.
@pytest.mark.django_db
class TestVariationIsolation:
    def test_other_variation_demand_does_not_leak(self, tenant):
        storage = StorageFactory(is_short_term_harvest_storage=True)
        article = ShareArticleFactory()
        sdd = SharesDeliveryDayFactory(day_number=5)
        variation_a = ShareTypeVariationFactory()
        variation_b = ShareTypeVariationFactory()  # noisy neighbor

        share_a = ShareFactory(
            year=2026,
            delivery_week=30,
            delivery_day=sdd,
            share_type_variation=variation_a,
            packing_day=5,
        )
        share_b = ShareFactory(
            year=2026,
            delivery_week=30,
            delivery_day=sdd,
            share_type_variation=variation_b,
            packing_day=5,
        )

        station = DeliveryStationFactory()
        station_day = DeliveryStationDayFactory(
            delivery_station=station, delivery_day=sdd
        )
        pc = PaymentCycleFactory()

        # A: quantity 3
        sub_a = SubscriptionFactory(
            member=MemberFactory(),
            share_type_variation=variation_a,
            quantity=3,
            payment_cycle=pc,
            default_delivery_station_day=station_day,
            valid_from=datetime.date(2026, 1, 5),
        )
        # B: quantity 7 — should NOT contribute to share_a's totals
        sub_b = SubscriptionFactory(
            member=MemberFactory(),
            share_type_variation=variation_b,
            quantity=7,
            payment_cycle=pc,
            default_delivery_station_day=station_day,
            valid_from=datetime.date(2026, 1, 5),
        )
        from apps.commissioning.models import ShareDelivery

        ShareDelivery.objects.create(
            share=share_a, subscription=sub_a, delivery_station_day=station_day
        )
        ShareDelivery.objects.create(
            share=share_b, subscription=sub_b, delivery_station_day=station_day
        )

        forecast = ForecastFactory(
            share_article=article,
            year=2026,
            delivery_week=30,
            size="M",
            storage=storage,
        )
        sc_a = ShareContentFactory(
            share=share_a,
            share_article=article,
            delivery_station=station,
            amount=Decimal("2"),
            unit="KG",
            size="M",
            forecast=forecast,
        )
        sc_a = ShareContent.objects.select_related(
            "share__share_type_variation",
            "share__delivery_day",
            "share_article",
            "forecast",
            "seller",
        ).get(pk=sc_a.pk)

        ShareContentService().create_movements([sc_a])

        total = sum(
            m.amount
            for m in MovementShareArticle.objects.filter(
                share_content=sc_a, movement_type="SHARECONTENT"
            )
        )
        # Should be -(2 * 3) = -6, not -(2 * (3+7)) = -20.
        assert total == Decimal("-6"), (
            f"Variation isolation broken — got {total}, expected -6. "
            f"Other-variation demand is leaking into this variation's total."
        )


# ── 7) Sanity check on the demand-aggregation function itself ───────────
#
# Pinpoints whether the suspected bug is in the SQL aggregation rather than
# the multiplication. This bypasses ShareContentService entirely.
@pytest.mark.django_db
class TestDemandAggregationCountsQuantityNotRows:
    def test_single_subscription_quantity_5_counts_as_5(self, tenant):
        from apps.commissioning.utils.share_type_variation_amounts import (
            batch_get_physical_variation_totals_for_week,
        )

        sdd = SharesDeliveryDayFactory(day_number=5)
        variation = ShareTypeVariationFactory()
        share = ShareFactory(
            year=2026,
            delivery_week=30,
            delivery_day=sdd,
            share_type_variation=variation,
        )
        station = DeliveryStationFactory()
        station_day = DeliveryStationDayFactory(
            delivery_station=station, delivery_day=sdd
        )
        pc = PaymentCycleFactory()
        subscription = SubscriptionFactory(
            member=MemberFactory(),
            share_type_variation=variation,
            quantity=5,
            payment_cycle=pc,
            default_delivery_station_day=station_day,
            valid_from=datetime.date(2026, 1, 5),
        )
        from apps.commissioning.models import ShareDelivery

        ShareDelivery.objects.create(
            share=share, subscription=subscription, delivery_station_day=station_day
        )

        totals = batch_get_physical_variation_totals_for_week([variation], 2026, 30)
        basic = totals["basic"].get((sdd.id, variation.id))
        assert basic == 5, (
            f"batch_get_physical_variation_totals_for_week returned "
            f"{basic} for 1 subscription with quantity=5; expected 5. "
            f"If this fails, the bug is in the demand-aggregation SQL, NOT "
            f"in the ShareContentService multiplication."
        )

    def test_multiple_subscriptions_sum(self, tenant):
        from apps.commissioning.utils.share_type_variation_amounts import (
            batch_get_physical_variation_totals_for_week,
        )

        sdd = SharesDeliveryDayFactory(day_number=5)
        variation = ShareTypeVariationFactory()
        share = ShareFactory(
            year=2026,
            delivery_week=30,
            delivery_day=sdd,
            share_type_variation=variation,
        )
        station = DeliveryStationFactory()
        station_day = DeliveryStationDayFactory(
            delivery_station=station, delivery_day=sdd
        )
        pc = PaymentCycleFactory()
        from apps.commissioning.models import ShareDelivery

        for qty in [2, 3, 4]:
            sub = SubscriptionFactory(
                member=MemberFactory(),
                share_type_variation=variation,
                quantity=qty,
                payment_cycle=pc,
                default_delivery_station_day=station_day,
                valid_from=datetime.date(2026, 1, 5),
            )
            ShareDelivery.objects.create(
                share=share, subscription=sub, delivery_station_day=station_day
            )

        totals = batch_get_physical_variation_totals_for_week([variation], 2026, 30)
        basic = totals["basic"].get((sdd.id, variation.id))
        assert basic == 9, f"Expected 2+3+4=9, got {basic}."

    def test_share_delivery_without_subscription_contributes_zero(self, tenant):
        """A legacy / orphan ShareDelivery row without a subscription must
        not contribute fake demand (Sum of NULL is NULL, treated as 0)."""
        from apps.commissioning.utils.share_type_variation_amounts import (
            batch_get_physical_variation_totals_for_week,
        )

        sdd = SharesDeliveryDayFactory(day_number=5)
        variation = ShareTypeVariationFactory()
        share = ShareFactory(
            year=2026,
            delivery_week=30,
            delivery_day=sdd,
            share_type_variation=variation,
        )
        station = DeliveryStationFactory()
        station_day = DeliveryStationDayFactory(
            delivery_station=station, delivery_day=sdd
        )
        from apps.commissioning.models import ShareDelivery

        # ShareDelivery without a subscription. With Sum("subscription__quantity")
        # this is 0 (NULL skipped). If the implementation ever switched to
        # Count(*) this would silently inflate to 1 per orphan.
        ShareDelivery.objects.create(
            share=share, subscription=None, delivery_station_day=station_day
        )

        totals = batch_get_physical_variation_totals_for_week([variation], 2026, 30)
        basic = totals["basic"].get((sdd.id, variation.id), 0)
        # Either no entry, or 0 — both acceptable.
        assert (
            basic in (0, None) or basic == 0
        ), f"Orphan ShareDelivery (no subscription) leaked into demand: {basic}"


# Silence imports lint on Share — referenced only in type hints elsewhere
_ = Share
