"""Integration tests for the preparation lists shown to gardeners:

    - Harvesting list   (model="harvest")
    - Washing list      (model="washamount")
    - Cleaning list     (model="cleanamount")

For each list we create *several* ``ShareContent`` rows pointing at the same
ShareArticle/day/unit/size combination (so they should aggregate into one
summary row), trigger the real ``ShareContentService`` pipeline to produce
``Theoretical*`` rows + movements, then read back through
``DocumentationSummaryService.get_summary`` and assert the totals are correct.

In addition we add one regression test for the variation-count endpoint used
by ``PlanningHarvestSharesBase`` to make sure that joker deliveries are
**excluded** from the count (only "real" deliveries count).

The subscription-totals helper ``batch_get_physical_variation_totals_for_week``
is patched in the share-content tests so the focus stays on the aggregation
of multiple ShareContent rows rather than on subscription counting.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.commissioning.models import (
    CleanAmount,
    Harvest,
    TheoreticalCleanAmount,
    TheoreticalHarvest,
    TheoreticalWashAmount,
    WashAmount,
)
from apps.commissioning.services.documentation_summary_service import (
    DocumentationSummaryService,
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
    ShareDeliveryFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
    StorageFactory,
    SubscriptionFactory,
)
from apps.commissioning.utils.share_type_variation_amounts import (
    batch_get_physical_variation_totals_for_week,
    get_physical_share_type_variation_totals,
)

YEAR = 2026
WEEK = 15
# SharesDeliveryDayFactory defaults: default_harvesting_day = default_washing_day
# = default_cleaning_day = 1 (Tuesday).  We use day_number=2 (Wednesday) for the
# delivery itself so harvest/wash/clean stay at day=1 ≤ delivery_day=2 and
# therefore don't roll back into the previous ISO week.
DELIVERY_DAY = 2
ACTIVITY_DAY = 1  # = default_harvesting_day / washing_day / cleaning_day

TOTALS_PATCH_PATH = (
    "apps.commissioning.services.share_content_service"
    ".batch_get_physical_variation_totals_for_weeks"
)


def _patch_totals(totals):
    """Patch the multi-week totals batch with a fake returning ``totals``
    (the single-week shape the tests build) for every requested week."""
    return patch(
        TOTALS_PATCH_PATH,
        side_effect=lambda physical_variations, year, weeks: {
            week: totals for week in weeks
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_totals(share_contents, *, quantity):
    """Build the dict structure returned by
    ``batch_get_physical_variation_totals_for_week`` so each ShareContent
    contributes ``quantity`` share_type_variations
    (= ``share_content.amount * quantity`` units of theoretical demand).
    """
    basic: dict[tuple, Decimal] = {}
    station: dict[tuple, Decimal] = {}
    for sc in share_contents:
        basic[(sc.share.delivery_day_id, sc.share.share_type_variation_id)] = Decimal(
            str(quantity)
        )
        station[
            (
                sc.share.delivery_day_id,
                sc.share.share_type_variation_id,
                sc.delivery_station_id,
            )
        ] = Decimal(str(quantity))
    return {"basic": basic, "tour": {}, "station": station}


def _make_totals_per_sc(per_sc_quantity):
    """Build totals dict where each ShareContent has its own quantity.

    ``per_sc_quantity`` maps a ShareContent → quantity (int/Decimal).
    """
    basic: dict[tuple, Decimal] = {}
    station: dict[tuple, Decimal] = {}
    for sc, qty in per_sc_quantity.items():
        q = Decimal(str(qty))
        basic[(sc.share.delivery_day_id, sc.share.share_type_variation_id)] = q
        station[
            (
                sc.share.delivery_day_id,
                sc.share.share_type_variation_id,
                sc.delivery_station_id,
            )
        ] = q
    return {"basic": basic, "tour": {}, "station": station}


@pytest.fixture
def shared_delivery_day(tenant):
    """A single SharesDeliveryDay reused across all ShareContents in a test.

    SharesDeliveryDay has ``overlap_unique_fields = ("day_number",)`` so we
    cannot create two rows with the same ``day_number`` and overlapping
    validity windows in one test.
    """
    return SharesDeliveryDayFactory(day_number=DELIVERY_DAY)


@pytest.fixture
def short_term_storage(tenant):
    return StorageFactory(is_short_term_harvest_storage=True)


def _build_share_contents(
    *,
    article,
    sdd,
    count,
    sc_amount=Decimal("5"),
    forecast=None,
    washing=False,
    cleaning=False,
    station=None,
):
    """Create ``count`` ShareContent rows for one (article, day, station)
    bucket. Each gets its own ShareTypeVariation so the patched totals dict
    can address them independently.
    """
    if station is None:
        station = DeliveryStationFactory()
        DeliveryStationDayFactory(delivery_station=station, delivery_day=sdd)
    # If the caller passed a pre-existing station they are responsible for
    # creating its DeliveryStationDay (only one is allowed per (station, day))

    contents = []
    for _ in range(count):
        stv = ShareTypeVariationFactory()
        share = ShareFactory(
            year=YEAR,
            delivery_week=WEEK,
            delivery_day=sdd,
            share_type_variation=stv,
        )
        sc_kwargs = dict(
            share=share,
            share_article=article,
            delivery_station=station,
            amount=sc_amount,
            unit="KG",
            size="M",
            washing=washing,
            cleaning=cleaning,
        )
        if forecast is not None:
            sc_kwargs["forecast"] = forecast
        contents.append(ShareContentFactory(**sc_kwargs))
    return contents


# ─────────────────────────────────────────────────────────────────────────────
# Harvesting list
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestHarvestingListAggregation:
    """Several ShareContents pointing at the same article must aggregate into
    a single harvesting-list summary row whose ``theoretical_harvest_amount``
    equals the sum of every contributing ``TheoreticalHarvest.amount``.

    The pipeline auto-creates a placeholder ``Harvest`` row, so the test does
    not need to create one manually.
    """

    @patch.object(
        DocumentationSummaryService,
        "_get_theoretical_stock_map",
        return_value={},
    )
    def test_aggregates_multiple_share_contents(
        self, _mock_stock, shared_delivery_day, short_term_storage
    ):
        article = ShareArticleFactory()
        forecast = ForecastFactory(
            share_article=article,
            year=YEAR,
            delivery_week=WEEK,
            size="M",
            storage=short_term_storage,
        )

        # 3 share contents × amount 5 × quantity 4 = 60 KG total demand
        contents = _build_share_contents(
            article=article,
            sdd=shared_delivery_day,
            count=3,
            forecast=forecast,
        )
        totals = _make_totals(contents, quantity=4)

        with _patch_totals(totals):
            ShareContentService().create_all_theoretical_objects(contents)

        # sanity – pipeline created one TheoreticalHarvest per ShareContent
        assert TheoreticalHarvest.objects.count() == 3
        per_sc_amount = Decimal("5") * Decimal("4")  # 20
        assert all(
            th.amount == per_sc_amount for th in TheoreticalHarvest.objects.all()
        )
        # placeholder Harvest row was created automatically
        assert Harvest.objects.count() == 1

        result = DocumentationSummaryService.get_summary(
            year=YEAR,
            delivery_week=WEEK,
            model="harvest",
            day_number=ACTIVITY_DAY,
        )

        assert len(result) == 1
        row = result[0]
        assert row["share_article"] == article.pk
        assert row["unit"] == "KG"
        assert row["size"] == "M"
        # theoretical aggregates across all 3 share contents
        assert row["theoretical_harvest_amount"] == per_sc_amount * 3  # 60

    @patch.object(
        DocumentationSummaryService,
        "_get_theoretical_stock_map",
        return_value={},
    )
    def test_separates_different_articles(
        self, _mock_stock, shared_delivery_day, short_term_storage
    ):
        art_a = ShareArticleFactory()
        art_b = ShareArticleFactory()
        fc_a = ForecastFactory(
            share_article=art_a,
            year=YEAR,
            delivery_week=WEEK,
            size="M",
            storage=short_term_storage,
        )
        fc_b = ForecastFactory(
            share_article=art_b,
            year=YEAR,
            delivery_week=WEEK,
            size="M",
            storage=short_term_storage,
        )

        contents_a = _build_share_contents(
            article=art_a,
            sdd=shared_delivery_day,
            count=2,
            forecast=fc_a,
        )
        contents_b = _build_share_contents(
            article=art_b,
            sdd=shared_delivery_day,
            count=1,
            forecast=fc_b,
        )
        totals = _make_totals(contents_a + contents_b, quantity=2)

        with _patch_totals(totals):
            ShareContentService().create_all_theoretical_objects(
                contents_a + contents_b
            )

        result = DocumentationSummaryService.get_summary(
            year=YEAR, delivery_week=WEEK, model="harvest", day_number=ACTIVITY_DAY
        )

        by_article = {row["share_article"]: row for row in result}
        # 2 share-contents × 5 × 2 = 20 for A
        assert by_article[art_a.pk]["theoretical_harvest_amount"] == Decimal("20")
        # 1 share-content × 5 × 2 = 10 for B
        assert by_article[art_b.pk]["theoretical_harvest_amount"] == Decimal("10")

    @patch.object(
        DocumentationSummaryService,
        "_get_theoretical_stock_map",
        return_value={},
    )
    def test_sums_across_many_stations_and_amounts(
        self, _mock_stock, shared_delivery_day, short_term_storage
    ):
        """Realistic scenario: one share article, many delivery stations,
        every station has several ShareContents with *different* amounts and
        *different* subscription quantities. The harvesting-list summary must
        return the exact total: ``Σ (sc.amount × subscription_quantity)``.
        """
        article = ShareArticleFactory()
        forecast = ForecastFactory(
            share_article=article,
            year=YEAR,
            delivery_week=WEEK,
            size="M",
            storage=short_term_storage,
        )

        # Per-station mix of (sc_amount, subscription_quantity) tuples.
        # Sums per station (sc_amount * qty):
        station_specs = [
            [(Decimal("3"), 4), (Decimal("2"), 5)],  # 12 + 10 = 22
            [
                (Decimal("5"), 2),
                (Decimal("4"), 3),
                (Decimal("1"), 7),
            ],  # 10 + 12 + 7 = 29
            [(Decimal("6"), 1)],  #  6
            [(Decimal("2"), 10), (Decimal("3"), 2)],  # 20 + 6 = 26
        ]

        per_sc_quantity = {}
        all_contents = []
        expected_total = Decimal("0")

        for specs in station_specs:
            station = DeliveryStationFactory()
            DeliveryStationDayFactory(
                delivery_station=station, delivery_day=shared_delivery_day
            )
            for sc_amount, qty in specs:
                stv = ShareTypeVariationFactory()
                share = ShareFactory(
                    year=YEAR,
                    delivery_week=WEEK,
                    delivery_day=shared_delivery_day,
                    share_type_variation=stv,
                )
                sc = ShareContentFactory(
                    share=share,
                    share_article=article,
                    delivery_station=station,
                    amount=sc_amount,
                    unit="KG",
                    size="M",
                    forecast=forecast,
                )
                per_sc_quantity[sc] = qty
                all_contents.append(sc)
                expected_total += sc_amount * Decimal(qty)

        # Sanity: 22 + 29 + 6 + 26 = 83
        assert expected_total == Decimal("83")

        totals = _make_totals_per_sc(per_sc_quantity)

        with _patch_totals(totals):
            ShareContentService().create_all_theoretical_objects(all_contents)

        # One TheoreticalHarvest per ShareContent; their amounts sum to the total
        ths = list(TheoreticalHarvest.objects.all())
        assert len(ths) == len(all_contents)
        assert sum((th.amount or 0) for th in ths) == expected_total

        result = DocumentationSummaryService.get_summary(
            year=YEAR, delivery_week=WEEK, model="harvest", day_number=ACTIVITY_DAY
        )

        # Grouping is by (article, unit, size, day, storage) — NOT by station —
        # so we expect exactly one summary row.
        article_rows = [r for r in result if r["share_article"] == article.pk]
        assert len(article_rows) == 1, (
            f"Expected harvest to aggregate across stations into 1 row, "
            f"got {len(article_rows)}"
        )
        assert article_rows[0]["theoretical_harvest_amount"] == expected_total


# ─────────────────────────────────────────────────────────────────────────────
# Washing list
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestWashingListAggregation:
    """Only ShareContents flagged ``washing=True`` produce
    ``TheoreticalWashAmount`` rows; the washing-list summary must aggregate
    them per (article, unit, size, day).
    """

    @patch.object(
        DocumentationSummaryService,
        "_get_theoretical_stock_map",
        return_value={},
    )
    def test_aggregates_only_washing_share_contents(
        self, _mock_stock, shared_delivery_day, short_term_storage
    ):
        article = ShareArticleFactory()
        station = DeliveryStationFactory()
        DeliveryStationDayFactory(
            delivery_station=station, delivery_day=shared_delivery_day
        )

        washing_contents = _build_share_contents(
            article=article,
            sdd=shared_delivery_day,
            station=station,
            count=2,
            washing=True,
        )
        non_washing = _build_share_contents(
            article=article,
            sdd=shared_delivery_day,
            station=station,
            count=1,
            washing=False,
        )
        all_contents = washing_contents + non_washing
        totals = _make_totals(all_contents, quantity=3)

        with _patch_totals(totals):
            ShareContentService().create_all_theoretical_objects(all_contents)

        # only the washing-flagged contents produced TheoreticalWashAmount rows
        assert TheoreticalWashAmount.objects.count() == 2
        # placeholder WashAmount row was created automatically
        assert WashAmount.objects.count() == 1

        result = DocumentationSummaryService.get_summary(
            year=YEAR, delivery_week=WEEK, model="washamount", day_number=ACTIVITY_DAY
        )

        washing_rows = [r for r in result if r["share_article"] == article.pk]
        assert washing_rows, "expected at least one washing summary row"
        # 2 washing contents × 5 × 3 = 30
        assert (
            sum(r["theoretical_washamount_amount"] for r in washing_rows)
            == Decimal("5") * Decimal("3") * 2
        )


# ─────────────────────────────────────────────────────────────────────────────
# Cleaning list
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCleaningListAggregation:
    """Mirror of the washing test for ``cleaning=True``."""

    @patch.object(
        DocumentationSummaryService,
        "_get_theoretical_stock_map",
        return_value={},
    )
    def test_aggregates_only_cleaning_share_contents(
        self, _mock_stock, shared_delivery_day, short_term_storage
    ):
        article = ShareArticleFactory()
        station = DeliveryStationFactory()
        DeliveryStationDayFactory(
            delivery_station=station, delivery_day=shared_delivery_day
        )

        cleaning_contents = _build_share_contents(
            article=article,
            sdd=shared_delivery_day,
            station=station,
            count=3,
            cleaning=True,
        )
        non_cleaning = _build_share_contents(
            article=article,
            sdd=shared_delivery_day,
            station=station,
            count=2,
            cleaning=False,
        )
        all_contents = cleaning_contents + non_cleaning
        totals = _make_totals(all_contents, quantity=2)

        with _patch_totals(totals):
            ShareContentService().create_all_theoretical_objects(all_contents)

        assert TheoreticalCleanAmount.objects.count() == 3
        assert CleanAmount.objects.count() == 1

        result = DocumentationSummaryService.get_summary(
            year=YEAR, delivery_week=WEEK, model="cleanamount", day_number=ACTIVITY_DAY
        )

        cleaning_rows = [r for r in result if r["share_article"] == article.pk]
        assert cleaning_rows, "expected at least one cleaning summary row"
        # 3 cleaning contents × 5 × 2 = 30
        assert (
            sum(r["theoretical_cleanamount_amount"] for r in cleaning_rows)
            == Decimal("5") * Decimal("2") * 3
        )


# ─────────────────────────────────────────────────────────────────────────────
# PlanningHarvestSharesBase variation counts must EXCLUDE jokers
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestPlanningVariationCountsExcludeJokers:
    """The frontend ``PlanningHarvestSharesBase`` page reads variation totals
    from ``ShareVariationAmountsForPlanningView``, which delegates to
    ``batch_get_physical_variation_totals_for_week``. That helper filters
    ``ShareDelivery.objects.filter(joker_taken=False, ...)`` so the displayed
    count must reflect only "real" (non-joker) deliveries.
    """

    def _make_subscription(self, *, variation, station_day, quantity):
        member = MemberFactory()
        return SubscriptionFactory(
            member=member,
            share_type_variation=variation,
            payment_cycle=PaymentCycleFactory(),
            default_delivery_station_day=station_day,
            quantity=quantity,
        )

    def test_joker_deliveries_are_excluded(self, tenant):
        variation = ShareTypeVariationFactory()
        sdd = SharesDeliveryDayFactory(day_number=DELIVERY_DAY)
        station_day = DeliveryStationDayFactory(delivery_day=sdd, tour_number=1)

        share = ShareFactory(
            year=YEAR,
            delivery_week=WEEK,
            delivery_day=sdd,
            share_type_variation=variation,
        )

        # 3 normal deliveries (qty 2 each) → contribute 6 to the count
        for _ in range(3):
            sub = self._make_subscription(
                variation=variation, station_day=station_day, quantity=2
            )
            sd = ShareDeliveryFactory(
                share=share, delivery_station_day=station_day, joker_taken=False
            )
            sd.subscription = sub
            sd.save()

        # 2 joker deliveries (qty 5 each) → must NOT be counted
        for _ in range(2):
            sub = self._make_subscription(
                variation=variation, station_day=station_day, quantity=5
            )
            sd = ShareDeliveryFactory(
                share=share, delivery_station_day=station_day, joker_taken=True
            )
            sd.subscription = sub
            sd.save()

        totals = batch_get_physical_variation_totals_for_week(
            [variation], year=YEAR, delivery_week=WEEK
        )

        basic_count = totals["basic"].get((sdd.pk, variation.pk), 0)
        # 3 deliveries × subscription quantity 2 = 6 (no jokers)
        assert basic_count == 6, (
            f"Joker deliveries leaked into planning count: got {basic_count}, "
            "expected 6 (only the 3 real deliveries × qty 2)."
        )


@pytest.mark.django_db
class TestPhysicalVariationTotalsQueryCount:
    """``get_physical_share_type_variation_totals`` must aggregate demand in a
    constant number of queries — ONE ShareDelivery scan total, not one scan
    per physical variation (the old per-variation loop was the N+1)."""

    def _seed(self, sdd, station_day, n_variations: int) -> None:
        for _ in range(n_variations):
            # Variations share the single open HARVEST_SHARE ShareType but the
            # factory cycles ``size`` per call, so the (share_type, size)
            # uniqueness constraint never trips (n_variations stays <= 9).
            variation = ShareTypeVariationFactory()
            share = ShareFactory(
                year=YEAR,
                delivery_week=WEEK,
                delivery_day=sdd,
                share_type_variation=variation,
            )
            sub = SubscriptionFactory(
                member=MemberFactory(),
                share_type_variation=variation,
                payment_cycle=PaymentCycleFactory(),
                default_delivery_station_day=station_day,
                quantity=2,
            )
            share_delivery = ShareDeliveryFactory(
                share=share, delivery_station_day=station_day, joker_taken=False
            )
            share_delivery.subscription = sub
            share_delivery.save()

    @staticmethod
    def _share_delivery_selects(ctx: CaptureQueriesContext) -> int:
        return sum(
            1
            for q in ctx.captured_queries
            if '"commissioning_sharedelivery"' in q["sql"].lower()
            and q["sql"].lstrip().lower().startswith("select")
        )

    def test_demand_scan_constant_in_variation_count(self, tenant):
        # One shared delivery day / station day — two SharesDeliveryDay rows
        # with the same day_number trip the TimeBoundMixin overlap check.
        sdd = SharesDeliveryDayFactory(day_number=DELIVERY_DAY)
        station_day = DeliveryStationDayFactory(delivery_day=sdd, tour_number=1)

        self._seed(sdd, station_day, 2)
        with CaptureQueriesContext(connection) as ctx_small:
            res_small = get_physical_share_type_variation_totals(
                year=YEAR, delivery_week=WEEK
            )
        small = self._share_delivery_selects(ctx_small)

        self._seed(sdd, station_day, 4)  # 6 physical variations total now
        with CaptureQueriesContext(connection) as ctx_large:
            res_large = get_physical_share_type_variation_totals(
                year=YEAR, delivery_week=WEEK
            )
        large = self._share_delivery_selects(ctx_large)

        # Correctness: one delivery × subscription quantity 2 per variation.
        assert len(res_small) == 2
        assert len(res_large) == 6
        assert all(r["total_quantity"] == 2 for r in res_large)

        # Perf: a single ShareDelivery aggregation regardless of variation
        # count (was one scan per variation).
        assert small == 1, f"expected 1 ShareDelivery scan, got {small}"
        assert large == 1, (
            f"ShareDelivery scanned per variation: {large} scans for 6 "
            "variations — expected 1."
        )
