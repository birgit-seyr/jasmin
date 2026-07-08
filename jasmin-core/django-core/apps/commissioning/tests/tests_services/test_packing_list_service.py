"""Tests for PackingListService."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
import time_machine
from isoweek import Week

from apps.commissioning.errors import PackingAmountsDivergeAcrossStations
from apps.commissioning.models import Share
from apps.commissioning.services.default_share_content_service import (
    DefaultShareContentService,
)
from apps.commissioning.services.packing_list_service import PackingListService
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    ShareArticleFactory,
    ShareContentFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
)


def _bulk_station_totals(delivery_day, per_station: dict) -> dict:
    """Build the ``batch_get_physical_variation_totals_for_week`` return shape
    from ``{station_id: {variation_pk: qty}}``. ``get_packing_list_bulk`` only
    consumes the ``station`` map ``{(day_id, variation_id, station_id): qty}``."""
    station = {
        (delivery_day.id, variation_id, station_id): qty
        for station_id, counts in per_station.items()
        for variation_id, qty in counts.items()
    }
    return {"basic": {}, "tour": {}, "station": station}


# ---------------------------------------------------------------------------
# get_packing_list
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetPackingList:
    def test_returns_entries_grouped_by_article(self, tenant):
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2, default_packing_day=2)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)

        share = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=variation,
        )
        # Ensure the packing_day matches our query
        share.packing_day = 2
        share.save()

        article = ShareArticleFactory()
        ShareContentFactory(
            share=share,
            share_article=article,
            delivery_station=station_day.delivery_station,
            amount=Decimal("5"),
            unit="KG",
            size="M",
        )

        result = PackingListService.get_packing_list(
            year=2026,
            delivery_week=15,
            day_number=2,
            share_type=str(variation.share_type_id),
            is_past=False,
        )

        assert len(result) >= 1
        entry = result[0]
        assert entry["share_article"] == article.pk
        assert f"variation_{variation.pk}" in entry
        assert entry[f"variation_{variation.pk}"] == Decimal("5")

    def _two_station_setup(self, amount_a, amount_b):
        """Same (article, unit, size, variation) at two delivery stations with
        the given amounts. Returns (variation, article, station_a, station_b)."""
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2, default_packing_day=2)
        station_a = DeliveryStationDayFactory(delivery_day=delivery_day)
        station_b = DeliveryStationDayFactory(delivery_day=delivery_day)
        share = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=variation,
        )
        share.packing_day = 2
        share.save()
        article = ShareArticleFactory()
        for station_day, amount in (
            (station_a, amount_a),
            (station_b, amount_b),
        ):
            ShareContentFactory(
                share=share,
                share_article=article,
                delivery_station=station_day.delivery_station,
                amount=amount,
                unit="KG",
                size="M",
            )
        return variation, article, station_a, station_b

    def test_all_stations_view_refuses_divergent_amounts(self, tenant):
        # Two stations disagree on the per-share amount for the same cell — the
        # all-stations view (no delivery_station) must refuse rather than keep an
        # arbitrary one (the pre-fix silent last-wins).
        variation, _article, _a, _b = self._two_station_setup(
            Decimal("5"), Decimal("3")
        )
        with pytest.raises(PackingAmountsDivergeAcrossStations):
            PackingListService.get_packing_list(
                year=2026,
                delivery_week=15,
                day_number=2,
                share_type=str(variation.share_type_id),
                is_past=False,
            )

    def test_all_stations_view_allows_equal_amounts(self, tenant):
        # Amounts agree across stations (the granularity-guard common case) →
        # collapse is harmless, no error, the shared amount is returned.
        variation, _article, _a, _b = self._two_station_setup(
            Decimal("5"), Decimal("5")
        )
        result = PackingListService.get_packing_list(
            year=2026,
            delivery_week=15,
            day_number=2,
            share_type=str(variation.share_type_id),
            is_past=False,
        )
        assert result[0][f"variation_{variation.pk}"] == Decimal("5")

    def test_station_scoped_view_skips_divergence_check(self, tenant):
        # With a concrete station the check is skipped (one row per cell); the
        # scoped station's own amount is returned — the bulk path relies on this.
        variation, _article, station_a, _b = self._two_station_setup(
            Decimal("5"), Decimal("3")
        )
        result = PackingListService.get_packing_list(
            year=2026,
            delivery_week=15,
            day_number=2,
            share_type=str(variation.share_type_id),
            is_past=False,
            delivery_station=station_a.delivery_station.id,
        )
        assert result[0][f"variation_{variation.pk}"] == Decimal("5")

    def test_scopes_to_delivery_day(self, tenant):
        # The endpoint scopes by DELIVERY day (day_number = the delivery weekday),
        # so two delivery days that share one packing day are returned SEPARATELY:
        # each request sees only its own delivery day's amount, never a cross-day
        # collapse. (Both shares carry packing_day=2; the filter keys on the
        # delivery day, not the packing day.)
        variation = ShareTypeVariationFactory()
        article = ShareArticleFactory()
        station = DeliveryStationFactory()
        for day_number, amount in ((2, Decimal("5")), (3, Decimal("3"))):
            delivery_day = SharesDeliveryDayFactory(
                day_number=day_number, default_packing_day=2
            )
            DeliveryStationDayFactory(
                delivery_day=delivery_day, delivery_station=station
            )
            share = ShareFactory(
                year=2026,
                delivery_week=15,
                delivery_day=delivery_day,
                share_type_variation=variation,
            )
            share.packing_day = 2
            share.save()
            ShareContentFactory(
                share=share,
                share_article=article,
                delivery_station=station,
                amount=amount,
                unit="KG",
                size="M",
            )

        result_2 = PackingListService.get_packing_list(
            year=2026,
            delivery_week=15,
            day_number=2,
            share_type=str(variation.share_type_id),
            is_past=False,
        )
        assert result_2[0][f"variation_{variation.pk}"] == Decimal("5")

        result_3 = PackingListService.get_packing_list(
            year=2026,
            delivery_week=15,
            day_number=3,
            share_type=str(variation.share_type_id),
            is_past=False,
        )
        assert result_3[0][f"variation_{variation.pk}"] == Decimal("3")

    def test_empty_for_no_data(self, tenant):
        result = PackingListService.get_packing_list(
            year=2026,
            delivery_week=99,
            day_number=1,
            share_type="nonexistent",
            is_past=False,
        )
        assert result == []

    def test_is_packed_bulk_false_excludes_bulk_variation_columns(self, tenant):
        """In MIXED mode the boxes packing list is requested with
        ``is_packed_bulk=False``. The returned per-article entries must
        only expose ``variation_<id>`` columns for boxed variations — the
        bulk variation's column must not appear, and rows where every
        boxed-column is zero must be filtered out."""
        delivery_day = SharesDeliveryDayFactory(day_number=2, default_packing_day=2)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)

        var_bulk = ShareTypeVariationFactory(size="S", is_packed_bulk=True)
        var_boxes = ShareTypeVariationFactory(
            size="M", share_type=var_bulk.share_type, is_packed_bulk=False
        )

        share_bulk = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=var_bulk,
        )
        share_bulk.packing_day = 2
        share_bulk.save()

        share_boxes = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=var_boxes,
        )
        share_boxes.packing_day = 2
        share_boxes.save()

        # Article A: shows up in BOTH variations — only the boxed
        # contribution must survive the filter.
        article_a = ShareArticleFactory(name="Carrots")
        ShareContentFactory(
            share=share_bulk,
            share_article=article_a,
            delivery_station=station_day.delivery_station,
            amount=Decimal("9"),
            unit="KG",
            size="M",
        )
        ShareContentFactory(
            share=share_boxes,
            share_article=article_a,
            delivery_station=station_day.delivery_station,
            amount=Decimal("3"),
            unit="KG",
            size="M",
        )

        # Article B: only in the bulk variation — must be filtered out
        # entirely because no boxed variation has a non-zero amount.
        article_b = ShareArticleFactory(name="Beets")
        ShareContentFactory(
            share=share_bulk,
            share_article=article_b,
            delivery_station=station_day.delivery_station,
            amount=Decimal("7"),
            unit="KG",
            size="M",
        )

        result = PackingListService.get_packing_list(
            year=2026,
            delivery_week=15,
            day_number=2,
            share_type=str(var_boxes.share_type_id),
            is_past=False,
            is_packed_bulk=False,
        )

        assert len(result) == 1
        entry = result[0]
        assert entry["share_article"] == article_a.pk
        # The boxed variation's column must be present with its own amount.
        assert entry[f"variation_{var_boxes.pk}"] == Decimal("3")
        # The bulk variation's column must NOT be emitted at all.
        assert f"variation_{var_bulk.pk}" not in entry

    def test_is_packed_bulk_true_excludes_boxed_variation_columns(self, tenant):
        """Symmetric to the boxes case: in MIXED mode the bulk packing
        list (or anywhere this filter is requested) must only expose
        bulk-variation columns."""
        delivery_day = SharesDeliveryDayFactory(day_number=2, default_packing_day=2)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)

        var_bulk = ShareTypeVariationFactory(size="S", is_packed_bulk=True)
        var_boxes = ShareTypeVariationFactory(
            size="M", share_type=var_bulk.share_type, is_packed_bulk=False
        )

        share_bulk = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=var_bulk,
        )
        share_bulk.packing_day = 2
        share_bulk.save()

        share_boxes = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=var_boxes,
        )
        share_boxes.packing_day = 2
        share_boxes.save()

        article = ShareArticleFactory(name="Onions")
        ShareContentFactory(
            share=share_bulk,
            share_article=article,
            delivery_station=station_day.delivery_station,
            amount=Decimal("4"),
            unit="KG",
            size="M",
        )
        ShareContentFactory(
            share=share_boxes,
            share_article=article,
            delivery_station=station_day.delivery_station,
            amount=Decimal("99"),
            unit="KG",
            size="M",
        )

        result = PackingListService.get_packing_list(
            year=2026,
            delivery_week=15,
            day_number=2,
            share_type=str(var_bulk.share_type_id),
            is_past=False,
            is_packed_bulk=True,
        )

        assert len(result) == 1
        entry = result[0]
        assert entry[f"variation_{var_bulk.pk}"] == Decimal("4")
        assert f"variation_{var_boxes.pk}" not in entry

    def test_is_packed_bulk_none_keeps_all_variation_columns(self, tenant):
        """In BULK/BOXES modes the filter is omitted and every active
        variation's column must be present on each article row."""
        delivery_day = SharesDeliveryDayFactory(day_number=2, default_packing_day=2)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)

        var_bulk = ShareTypeVariationFactory(size="S", is_packed_bulk=True)
        var_boxes = ShareTypeVariationFactory(
            size="M", share_type=var_bulk.share_type, is_packed_bulk=False
        )

        share_bulk = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=var_bulk,
        )
        share_bulk.packing_day = 2
        share_bulk.save()

        share_boxes = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=var_boxes,
        )
        share_boxes.packing_day = 2
        share_boxes.save()

        article = ShareArticleFactory()
        ShareContentFactory(
            share=share_bulk,
            share_article=article,
            delivery_station=station_day.delivery_station,
            amount=Decimal("4"),
            unit="KG",
            size="M",
        )
        ShareContentFactory(
            share=share_boxes,
            share_article=article,
            delivery_station=station_day.delivery_station,
            amount=Decimal("2"),
            unit="KG",
            size="M",
        )

        result = PackingListService.get_packing_list(
            year=2026,
            delivery_week=15,
            day_number=2,
            share_type=str(var_bulk.share_type_id),
            is_past=False,
        )

        assert len(result) == 1
        entry = result[0]
        assert entry[f"variation_{var_bulk.pk}"] == Decimal("4")
        assert entry[f"variation_{var_boxes.pk}"] == Decimal("2")

    def test_filters_by_packing_station(self, tenant):
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2, default_packing_day=2)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)

        share = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=variation,
        )
        share.packing_day = 2
        share.save()

        article = ShareArticleFactory()
        ShareContentFactory(
            share=share,
            share_article=article,
            delivery_station=station_day.delivery_station,
            amount=Decimal("5"),
            unit="KG",
            size="M",
            packing_station=3,
        )

        # Query for a different packing station
        result = PackingListService.get_packing_list(
            year=2026,
            delivery_week=15,
            day_number=2,
            share_type=str(variation.share_type_id),
            is_past=False,
            packing_station=99,
        )
        assert result == []


# ---------------------------------------------------------------------------
# get_packing_list_bulk
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetPackingListBulk:
    def test_returns_empty_when_no_packing_list(self, tenant):
        result = PackingListService.get_packing_list_bulk(
            year=2026, delivery_week=99, day_number=1, share_type="x", is_past=False
        )
        assert result == []

    @patch(
        "apps.commissioning.services.packing_list_service.batch_get_physical_variation_totals_for_week"
    )
    def test_multiplies_amounts_by_variation_count_per_station(
        self, mock_variation_totals, tenant
    ):
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2, default_packing_day=2)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)

        share = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=variation,
        )
        share.packing_day = 2
        share.save()

        article = ShareArticleFactory()
        ShareContentFactory(
            share=share,
            share_article=article,
            delivery_station=station_day.delivery_station,
            amount=Decimal("3"),
            unit="KG",
            size="M",
        )

        mock_variation_totals.return_value = _bulk_station_totals(
            delivery_day, {station_day.delivery_station.id: {variation.pk: 10}}
        )

        result = PackingListService.get_packing_list_bulk(
            year=2026,
            delivery_week=15,
            day_number=2,
            share_type=str(variation.share_type_id),
            is_past=False,
        )

        assert len(result) == 1
        row = result[0]
        assert row["total_amount"] == 30.0  # 3 × 10
        assert row["delivery_station"] == station_day.delivery_station.id
        assert row["share_article"] == article.id
        # Totals are resolved in ONE batched call for the week (then looked up
        # per station from the in-memory map) — not once per station.
        assert mock_variation_totals.call_count == 1
        assert mock_variation_totals.call_args.args[1:] == (2026, 15)

    @patch(
        "apps.commissioning.services.packing_list_service.batch_get_physical_variation_totals_for_week"
    )
    def test_emits_one_row_per_station(self, mock_variation_totals, tenant):
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2, default_packing_day=2)
        station_day_a = DeliveryStationDayFactory(delivery_day=delivery_day)
        station_day_b = DeliveryStationDayFactory(delivery_day=delivery_day)

        # Share is unique on (year, week, day, variation) — one template,
        # then one ShareContent per delivery station.
        share = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=variation,
        )
        share.packing_day = 2
        share.save()

        article = ShareArticleFactory()
        for station_day in (station_day_a, station_day_b):
            ShareContentFactory(
                share=share,
                share_article=article,
                delivery_station=station_day.delivery_station,
                amount=Decimal("2"),
                unit="KG",
                size="M",
            )

        # 5 share_type_variations per station × 2 KG = 10 KG per station
        mock_variation_totals.return_value = _bulk_station_totals(
            delivery_day,
            {
                station_day_a.delivery_station.id: {variation.pk: 5},
                station_day_b.delivery_station.id: {variation.pk: 5},
            },
        )

        result = PackingListService.get_packing_list_bulk(
            year=2026,
            delivery_week=15,
            day_number=2,
            share_type=str(variation.share_type_id),
            is_past=False,
        )

        assert len(result) == 2
        stations = {row["delivery_station"] for row in result}
        assert stations == {
            station_day_a.delivery_station.id,
            station_day_b.delivery_station.id,
        }
        assert all(row["total_amount"] == 10.0 for row in result)

    @patch(
        "apps.commissioning.services.packing_list_service.batch_get_physical_variation_totals_for_week"
    )
    def test_sums_across_share_types_when_share_type_omitted(
        self, mock_variation_totals, tenant
    ):
        """Omitting share_type sums every share_type's demand for the same
        (station, article) — the bulk list is a per-article warehouse total
        that ignores which share_type an article belongs to."""
        delivery_day = SharesDeliveryDayFactory(day_number=2, default_packing_day=2)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
        station = station_day.delivery_station

        variation_a = ShareTypeVariationFactory(
            share_type=ShareTypeFactory(share_option="HARVEST_SHARE")
        )
        variation_b = ShareTypeVariationFactory(
            share_type=ShareTypeFactory(share_option="HONEY_SHARE")
        )
        assert variation_a.share_type_id != variation_b.share_type_id

        article = ShareArticleFactory()
        for variation, amount in (
            (variation_a, Decimal("3")),
            (variation_b, Decimal("2")),
        ):
            share = ShareFactory(
                year=2026,
                delivery_week=15,
                delivery_day=delivery_day,
                share_type_variation=variation,
            )
            share.packing_day = 2
            share.save()
            ShareContentFactory(
                share=share,
                share_article=article,
                delivery_station=station,
                amount=amount,
                unit="KG",
                size="M",
            )

        mock_variation_totals.return_value = _bulk_station_totals(
            delivery_day, {station.id: {variation_a.pk: 10, variation_b.pk: 5}}
        )

        result = PackingListService.get_packing_list_bulk(
            year=2026, delivery_week=15, day_number=2, is_past=False
        )

        # One merged row: 3 × 10 (share_type A) + 2 × 5 (share_type B) = 40.
        assert len(result) == 1
        assert result[0]["total_amount"] == 40.0
        assert result[0]["share_article"] == article.id

        # Scoping to a single share_type returns only that share_type's slice.
        scoped = PackingListService.get_packing_list_bulk(
            year=2026,
            delivery_week=15,
            day_number=2,
            is_past=False,
            share_type=str(variation_a.share_type_id),
        )
        assert len(scoped) == 1
        assert scoped[0]["total_amount"] == 30.0

    @patch(
        "apps.commissioning.services.packing_list_service.batch_get_physical_variation_totals_for_week"
    )
    def test_bulk_query_count_does_not_scale_per_station(
        self, mock_variation_totals, tenant
    ):
        """The variation query + delivery_day probe are hoisted out of the
        per-station loop, so each extra station adds ~1 query (its own
        ``.values()``), not the ~5/station the un-hoisted path cost."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        mock_variation_totals.return_value = {"basic": {}, "tour": {}, "station": {}}
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2, default_packing_day=2)
        article = ShareArticleFactory()

        def _make_week(week: int, n_stations: int) -> None:
            share = ShareFactory(
                year=2026,
                delivery_week=week,
                delivery_day=delivery_day,
                share_type_variation=variation,
            )
            share.packing_day = 2
            share.save()
            for _ in range(n_stations):
                station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
                ShareContentFactory(
                    share=share,
                    share_article=article,
                    delivery_station=station_day.delivery_station,
                    amount=Decimal("2"),
                    unit="KG",
                    size="M",
                )

        _make_week(15, 2)
        _make_week(16, 5)

        def _count(week: int) -> int:
            with CaptureQueriesContext(connection) as ctx:
                PackingListService.get_packing_list_bulk(
                    year=2026,
                    delivery_week=week,
                    day_number=2,
                    share_type=str(variation.share_type_id),
                    is_past=False,
                )
            return len(ctx)

        q_two_stations = _count(15)
        q_five_stations = _count(16)

        # 3 extra stations. Hoisted: ~1 query/station marginal; the un-hoisted
        # path added ~5/station (variation list + exists()/first()/share probe).
        # A bound of 6 passes the hoisted path with headroom and fails a regression.
        assert q_five_stations - q_two_stations <= 6, (
            f"per-station query growth too high: {q_two_stations} (2 stations) "
            f"→ {q_five_stations} (5 stations)"
        )

    @patch(
        "apps.commissioning.services.packing_list_service.batch_get_physical_variation_totals_for_week"
    )
    def test_delivery_station_filter_scopes_result(self, mock_variation_totals, tenant):
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2, default_packing_day=2)
        station_day_a = DeliveryStationDayFactory(delivery_day=delivery_day)
        station_day_b = DeliveryStationDayFactory(delivery_day=delivery_day)

        share = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=variation,
        )
        share.packing_day = 2
        share.save()

        article = ShareArticleFactory()
        for station_day in (station_day_a, station_day_b):
            ShareContentFactory(
                share=share,
                share_article=article,
                delivery_station=station_day.delivery_station,
                amount=Decimal("2"),
                unit="KG",
                size="M",
            )

        mock_variation_totals.return_value = _bulk_station_totals(
            delivery_day,
            {
                station_day_a.delivery_station.id: {variation.pk: 5},
                station_day_b.delivery_station.id: {variation.pk: 5},
            },
        )

        result = PackingListService.get_packing_list_bulk(
            year=2026,
            delivery_week=15,
            day_number=2,
            share_type=str(variation.share_type_id),
            is_past=False,
            delivery_station=station_day_a.delivery_station.id,
        )

        assert len(result) == 1
        assert result[0]["delivery_station"] == station_day_a.delivery_station.id

    @patch(
        "apps.commissioning.services.packing_list_service.batch_get_physical_variation_totals_for_week"
    )
    def test_per_station_amounts_do_not_bleed_across_stations(
        self, mock_variation_totals, tenant
    ):
        """Regression: previously the global ``get_packing_list`` call
        collapsed multiple stations' ShareContents via the
        ``(article, unit, size)`` composite key, so the last station's
        amount silently overwrote the others. Per-station amounts must
        stay isolated."""
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2, default_packing_day=2)
        station_day_a = DeliveryStationDayFactory(delivery_day=delivery_day)
        station_day_b = DeliveryStationDayFactory(delivery_day=delivery_day)

        share = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=variation,
        )
        share.packing_day = 2
        share.save()

        # Same article + variation at two stations, but DIFFERENT amounts.
        article = ShareArticleFactory()
        ShareContentFactory(
            share=share,
            share_article=article,
            delivery_station=station_day_a.delivery_station,
            amount=Decimal("10"),
            unit="KG",
            size="M",
        )
        ShareContentFactory(
            share=share,
            share_article=article,
            delivery_station=station_day_b.delivery_station,
            amount=Decimal("3"),
            unit="KG",
            size="M",
        )

        # 5 share_type_variations at each station (same variation).
        mock_variation_totals.return_value = _bulk_station_totals(
            delivery_day,
            {
                station_day_a.delivery_station.id: {variation.pk: 5},
                station_day_b.delivery_station.id: {variation.pk: 5},
            },
        )

        result = PackingListService.get_packing_list_bulk(
            year=2026,
            delivery_week=15,
            day_number=2,
            share_type=str(variation.share_type_id),
            is_past=False,
        )

        by_station = {row["delivery_station"]: row["total_amount"] for row in result}
        # Station A must use its OWN amount (10 KG × 5 share_type_variations
        # = 50), not station B's (3) leaking via the composite-key overwrite.
        assert by_station[station_day_a.delivery_station.id] == pytest.approx(50.0)
        assert by_station[station_day_b.delivery_station.id] == pytest.approx(15.0)

    @patch(
        "apps.commissioning.services.packing_list_service.batch_get_physical_variation_totals_for_week"
    )
    def test_articles_only_at_one_station_do_not_leak_into_other(
        self, mock_variation_totals, tenant
    ):
        """Regression: previously the global ``get_packing_list`` produced
        a single row per article and that row was multiplied by every
        station's box counts, so an article unique to one station
        appeared (with a fake total) at every other station."""
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2, default_packing_day=2)
        station_day_a = DeliveryStationDayFactory(delivery_day=delivery_day)
        station_day_b = DeliveryStationDayFactory(delivery_day=delivery_day)

        share = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=variation,
        )
        share.packing_day = 2
        share.save()

        carrots = ShareArticleFactory(name="Carrots")
        onions = ShareArticleFactory(name="Onions")
        # Carrots only at station A; Onions only at station B.
        ShareContentFactory(
            share=share,
            share_article=carrots,
            delivery_station=station_day_a.delivery_station,
            amount=Decimal("2"),
            unit="KG",
            size="M",
        )
        ShareContentFactory(
            share=share,
            share_article=onions,
            delivery_station=station_day_b.delivery_station,
            amount=Decimal("2"),
            unit="KG",
            size="M",
        )

        mock_variation_totals.return_value = _bulk_station_totals(
            delivery_day,
            {
                station_day_a.delivery_station.id: {variation.pk: 5},
                station_day_b.delivery_station.id: {variation.pk: 5},
            },
        )

        result = PackingListService.get_packing_list_bulk(
            year=2026,
            delivery_week=15,
            day_number=2,
            share_type=str(variation.share_type_id),
            is_past=False,
        )

        rows_a = {
            row["share_article_name"]
            for row in result
            if row["delivery_station"] == station_day_a.delivery_station.id
        }
        rows_b = {
            row["share_article_name"]
            for row in result
            if row["delivery_station"] == station_day_b.delivery_station.id
        }
        assert rows_a == {"Carrots"}
        assert rows_b == {"Onions"}

    @patch(
        "apps.commissioning.services.packing_list_service.batch_get_physical_variation_totals_for_week"
    )
    def test_matrix_two_stations_two_variations_two_articles(
        self, mock_variation_totals, tenant
    ):
        """Full-matrix sanity check: every station must use its own
        ShareContent amounts and its own box counts, and the per-variation
        contributions must sum correctly per article."""
        delivery_day = SharesDeliveryDayFactory(day_number=2, default_packing_day=2)
        station_day_a = DeliveryStationDayFactory(delivery_day=delivery_day)
        station_day_b = DeliveryStationDayFactory(delivery_day=delivery_day)
        station_a = station_day_a.delivery_station
        station_b = station_day_b.delivery_station

        # Two physical variations of the same share_type, one Share each.
        var_s = ShareTypeVariationFactory(size="S")
        var_m = ShareTypeVariationFactory(size="M", share_type=var_s.share_type)

        share_s = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=var_s,
        )
        share_s.packing_day = 2
        share_s.save()

        share_m = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=var_m,
        )
        share_m.packing_day = 2
        share_m.save()

        carrots = ShareArticleFactory(name="Carrots")
        onions = ShareArticleFactory(name="Onions")

        # ShareContents: per (variation, article, station) with distinct
        # amounts so any cross-station / cross-variation leakage breaks the
        # assertion.
        amounts = {
            # (share, article, station) -> KG per box
            (share_s, carrots, station_a): Decimal("10"),
            (share_s, carrots, station_b): Decimal("8"),
            (share_s, onions, station_a): Decimal("1"),
            (share_s, onions, station_b): Decimal("2"),
            (share_m, carrots, station_a): Decimal("20"),
            (share_m, carrots, station_b): Decimal("15"),
            (share_m, onions, station_a): Decimal("3"),
            (share_m, onions, station_b): Decimal("4"),
        }
        for (share, article, station), amount in amounts.items():
            ShareContentFactory(
                share=share,
                share_article=article,
                delivery_station=station,
                amount=amount,
                unit="KG",
                size="M",
            )

        # Box counts per station × variation.
        variations_by_station = {
            station_a.id: {var_s.pk: 5, var_m.pk: 3},
            station_b.id: {var_s.pk: 2, var_m.pk: 4},
        }

        mock_variation_totals.return_value = _bulk_station_totals(
            delivery_day, variations_by_station
        )

        result = PackingListService.get_packing_list_bulk(
            year=2026,
            delivery_week=15,
            day_number=2,
            share_type=str(var_s.share_type_id),
            is_past=False,
        )

        totals = {
            (row["delivery_station"], row["share_article_name"]): row["total_amount"]
            for row in result
        }

        # Station A: 5 boxes S, 3 boxes M with A's own amounts.
        assert totals[(station_a.id, "Carrots")] == pytest.approx(
            5 * 10 + 3 * 20  # 110
        )
        assert totals[(station_a.id, "Onions")] == pytest.approx(5 * 1 + 3 * 3)  # 14
        # Station B: 2 boxes S, 4 boxes M with B's own amounts.
        assert totals[(station_b.id, "Carrots")] == pytest.approx(2 * 8 + 4 * 15)  # 76
        assert totals[(station_b.id, "Onions")] == pytest.approx(2 * 2 + 4 * 4)  # 20
        # No spurious rows for unused (station, article) combinations.
        assert len(totals) == 4

    @patch(
        "apps.commissioning.services.packing_list_service.batch_get_physical_variation_totals_for_week"
    )
    def test_is_packed_bulk_true_keeps_only_bulk_variations(
        self, mock_variation_totals, tenant
    ):
        """In MIXED packing mode the bulk list is requested with
        ``is_packed_bulk=True``; only variations flagged for bulk packing
        must contribute, and their per-variation amounts must sum into the
        per-(article, station) total."""
        delivery_day = SharesDeliveryDayFactory(day_number=2, default_packing_day=2)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
        station = station_day.delivery_station

        # Same share_type, two variations: one bulk, one boxed.
        var_bulk = ShareTypeVariationFactory(size="S", is_packed_bulk=True)
        var_boxes = ShareTypeVariationFactory(
            size="M", share_type=var_bulk.share_type, is_packed_bulk=False
        )

        share_bulk = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=var_bulk,
        )
        share_bulk.packing_day = 2
        share_bulk.save()

        share_boxes = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=var_boxes,
        )
        share_boxes.packing_day = 2
        share_boxes.save()

        article = ShareArticleFactory(name="Carrots")
        ShareContentFactory(
            share=share_bulk,
            share_article=article,
            delivery_station=station,
            amount=Decimal("4"),
            unit="KG",
            size="M",
        )
        ShareContentFactory(
            share=share_boxes,
            share_article=article,
            delivery_station=station,
            amount=Decimal("99"),  # would dominate the total if leaked
            unit="KG",
            size="M",
        )

        # 5 of each variation per station.
        mock_variation_totals.return_value = _bulk_station_totals(
            delivery_day, {station.id: {var_bulk.pk: 5, var_boxes.pk: 5}}
        )

        result = PackingListService.get_packing_list_bulk(
            year=2026,
            delivery_week=15,
            day_number=2,
            share_type=str(var_bulk.share_type_id),
            is_past=False,
            is_packed_bulk=True,
        )

        assert len(result) == 1
        # Only the bulk variation contributes: 4 KG × 5 boxes = 20.
        # The boxed variation (99 KG × 5) must NOT leak in.
        assert result[0]["total_amount"] == pytest.approx(20.0)
        assert result[0]["share_article"] == article.pk
        assert result[0]["delivery_station"] == station.id

    @patch(
        "apps.commissioning.services.packing_list_service.batch_get_physical_variation_totals_for_week"
    )
    def test_is_packed_bulk_false_keeps_only_boxed_variations(
        self, mock_variation_totals, tenant
    ):
        """Symmetric to the bulk case: in MIXED mode the boxes list is
        requested with ``is_packed_bulk=False``; rows must contain only the
        boxed variation's contribution."""
        delivery_day = SharesDeliveryDayFactory(day_number=2, default_packing_day=2)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
        station = station_day.delivery_station

        var_bulk = ShareTypeVariationFactory(size="S", is_packed_bulk=True)
        var_boxes = ShareTypeVariationFactory(
            size="M", share_type=var_bulk.share_type, is_packed_bulk=False
        )

        share_bulk = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=var_bulk,
        )
        share_bulk.packing_day = 2
        share_bulk.save()

        share_boxes = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=var_boxes,
        )
        share_boxes.packing_day = 2
        share_boxes.save()

        article = ShareArticleFactory(name="Onions")
        ShareContentFactory(
            share=share_bulk,
            share_article=article,
            delivery_station=station,
            amount=Decimal("9"),
            unit="KG",
            size="M",
        )
        ShareContentFactory(
            share=share_boxes,
            share_article=article,
            delivery_station=station,
            amount=Decimal("2"),
            unit="KG",
            size="M",
        )

        mock_variation_totals.return_value = _bulk_station_totals(
            delivery_day, {station.id: {var_bulk.pk: 4, var_boxes.pk: 7}}
        )

        result = PackingListService.get_packing_list_bulk(
            year=2026,
            delivery_week=15,
            day_number=2,
            share_type=str(var_bulk.share_type_id),
            is_past=False,
            is_packed_bulk=False,
        )

        assert len(result) == 1
        # Only the boxed variation: 2 KG × 7 boxes = 14. Bulk (9 × 4 = 36)
        # must NOT contribute.
        assert result[0]["total_amount"] == pytest.approx(14.0)

    @patch(
        "apps.commissioning.services.packing_list_service.batch_get_physical_variation_totals_for_week"
    )
    def test_is_packed_bulk_none_sums_all_variations(
        self, mock_variation_totals, tenant
    ):
        """In BULK/BOXES modes (filter omitted) every variation contributes
        to the bulk total — the filter is a no-op."""
        delivery_day = SharesDeliveryDayFactory(day_number=2, default_packing_day=2)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
        station = station_day.delivery_station

        var_a = ShareTypeVariationFactory(size="S", is_packed_bulk=True)
        var_b = ShareTypeVariationFactory(
            size="M", share_type=var_a.share_type, is_packed_bulk=False
        )

        share_a = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=var_a,
        )
        share_a.packing_day = 2
        share_a.save()

        share_b = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=var_b,
        )
        share_b.packing_day = 2
        share_b.save()

        article = ShareArticleFactory()
        ShareContentFactory(
            share=share_a,
            share_article=article,
            delivery_station=station,
            amount=Decimal("4"),
            unit="KG",
            size="M",
        )
        ShareContentFactory(
            share=share_b,
            share_article=article,
            delivery_station=station,
            amount=Decimal("2"),
            unit="KG",
            size="M",
        )

        mock_variation_totals.return_value = _bulk_station_totals(
            delivery_day, {station.id: {var_a.pk: 3, var_b.pk: 5}}
        )

        result = PackingListService.get_packing_list_bulk(
            year=2026,
            delivery_week=15,
            day_number=2,
            share_type=str(var_a.share_type_id),
            is_past=False,
        )

        assert len(result) == 1
        # Both variations contribute: 4×3 + 2×5 = 22.
        assert result[0]["total_amount"] == pytest.approx(22.0)

    @patch(
        "apps.commissioning.services.packing_list_service.batch_get_physical_variation_totals_for_week"
    )
    def test_applies_bulk_percentage_buffer(self, mock_variation_totals, tenant):
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2, default_packing_day=2)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)

        share = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=variation,
        )
        share.packing_day = 2
        share.save()

        # 20% buffer → multiplier 1.20
        article = ShareArticleFactory(percentage_added_to_bulk_packing_list=20)
        ShareContentFactory(
            share=share,
            share_article=article,
            delivery_station=station_day.delivery_station,
            amount=Decimal("3"),
            unit="KG",
            size="M",
        )

        mock_variation_totals.return_value = _bulk_station_totals(
            delivery_day, {station_day.delivery_station.id: {variation.pk: 10}}
        )

        result = PackingListService.get_packing_list_bulk(
            year=2026,
            delivery_week=15,
            day_number=2,
            share_type=str(variation.share_type_id),
            is_past=False,
        )

        assert len(result) == 1
        # 3 KG × 10 boxes × 1.20 buffer = 36.0
        assert result[0]["total_amount"] == pytest.approx(36.0)


# ---------------------------------------------------------------------------
# Default-content materialization → packing-list visibility
#
# Regression guard for the bug where ShareContent created through
# ``create_default_share_content`` (long-term planning, e.g. honey shares)
# never appeared in ANY day-filtered packing list. Root cause: that path
# builds ``Share`` rows with ``bulk_create``, which bypasses ``Share.save()``
# where ``packing_day`` / ``harvesting_day`` / ``washing_day`` /
# ``cleaning_day`` are defaulted from the delivery day. The rows landed with
# NULL day fields and were silently excluded by the ``share__packing_day=...``
# filter in ``get_packing_list`` / ``get_packing_list_bulk``.
#
# These tests go through the REAL service entry point — NOT the
# ``share.packing_day = 2; share.save()`` shortcut used elsewhere in this
# file, which is exactly why the bug went unnoticed for so long.
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDefaultContentMaterializationVisibility:
    """A Share materialized via default content must carry its day fields
    and therefore show up in the (day-filtered) boxes packing list."""

    YEAR = 2026
    WEEK = 40  # well clear of the frozen "now" below

    def _make_default_content(self, *, default_packing_day: int):
        """Drive ``create_default_share_content`` end-to-end for one future
        week, returning ``(variation, article, station)``."""
        monday = Week(self.YEAR, self.WEEK).monday()

        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(
            day_number=default_packing_day,
            default_harvesting_day=1,
            default_packing_day=default_packing_day,
            default_washing_day=3,
            default_cleaning_day=4,
        )
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
        article = ShareArticleFactory()

        validated_data = {
            "year": self.YEAR,
            "share_article": article.id,
            # share_option is a required field on the request but is not
            # consumed by materialization — a truthy placeholder is enough.
            "share_option": "any",
            "range_1": self.WEEK,
            "range_2": self.WEEK,
            "unit": "KG",
            "size": "M",
            f"amount_{variation.id}": "5",
        }

        # Freeze "now" a week before the target Monday so the week counts as
        # future (``_get_future_weeks`` materializes only weeks on/after now).
        with time_machine.travel(monday - timedelta(days=7)):
            DefaultShareContentService.create_default_share_content(validated_data)

        return variation, article, station_day.delivery_station

    def test_materialized_shares_carry_day_fields(self, tenant):
        variation, _article, _station = self._make_default_content(
            default_packing_day=2
        )

        shares = Share.objects.filter(
            year=self.YEAR,
            delivery_week=self.WEEK,
            share_type_variation=variation,
        )
        assert shares.exists(), "default content did not materialize any Share"
        for share in shares:
            # The bug: these were all NULL because bulk_create skipped save().
            assert share.packing_day == 2
            assert share.harvesting_day == 1
            assert share.washing_day == 3
            assert share.cleaning_day == 4

    def test_appears_in_boxes_packing_list(self, tenant):
        """The boxes list is the per-box recipe (no demand needed), so it
        proves the day-field fix makes default content visible without
        having to stand up subscriptions/ShareDeliveries."""
        variation, article, _station = self._make_default_content(default_packing_day=2)

        result = PackingListService.get_packing_list(
            year=self.YEAR,
            delivery_week=self.WEEK,
            day_number=2,
            share_type=str(variation.share_type_id),
            is_past=False,
        )

        assert any(row["share_article"] == article.id for row in result), (
            "default-content ShareContent did not surface in the boxes "
            "packing list — packing_day was likely NULL again"
        )

    def test_hidden_when_packing_day_does_not_match(self, tenant):
        """Sanity counterpart: a row materialized with packing_day=2 must NOT
        leak into a different packing day's list."""
        variation, _article, _station = self._make_default_content(
            default_packing_day=2
        )

        result = PackingListService.get_packing_list(
            year=self.YEAR,
            delivery_week=self.WEEK,
            day_number=5,  # different day
            share_type=str(variation.share_type_id),
            is_past=False,
        )

        assert result == []

    def test_regeneration_heals_preexisting_null_day_share(self, tenant):
        """A NULL-day Share left by an earlier bulk_create (e.g. a pre-fix
        subscription share) must be self-healed when default content reuses
        it via ``_prefetch_existing_shares`` — otherwise the freshly attached
        ShareContent inherits the NULL packing_day and stays invisible."""
        monday = Week(self.YEAR, self.WEEK).monday()

        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(
            day_number=2,
            default_harvesting_day=1,
            default_packing_day=2,
            default_washing_day=3,
            default_cleaning_day=4,
        )
        DeliveryStationDayFactory(delivery_day=delivery_day)
        article = ShareArticleFactory()

        # Pre-seed the exact Share key default content will reuse, with NULL
        # day fields (bulk_create bypasses save()).
        Share.objects.bulk_create(
            [
                Share(
                    year=self.YEAR,
                    delivery_week=self.WEEK,
                    delivery_day=delivery_day,
                    share_type_variation=variation,
                )
            ]
        )
        stale = Share.objects.get(
            year=self.YEAR, delivery_week=self.WEEK, share_type_variation=variation
        )
        assert stale.packing_day is None

        validated_data = {
            "year": self.YEAR,
            "share_article": article.id,
            "share_option": "any",
            "range_1": self.WEEK,
            "range_2": self.WEEK,
            "unit": "KG",
            "size": "M",
            f"amount_{variation.id}": "5",
        }
        with time_machine.travel(monday - timedelta(days=7)):
            DefaultShareContentService.create_default_share_content(validated_data)

        # The reused share was healed in place...
        stale.refresh_from_db()
        assert stale.packing_day == 2
        assert stale.harvesting_day == 1
        assert stale.washing_day == 3
        assert stale.cleaning_day == 4

        # ...so its ShareContent now surfaces in the day-filtered boxes list.
        result = PackingListService.get_packing_list(
            year=self.YEAR,
            delivery_week=self.WEEK,
            day_number=2,
            share_type=str(variation.share_type_id),
            is_past=False,
        )
        assert any(row["share_article"] == article.id for row in result)
