"""Tests for ShareContentService."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from apps.commissioning.models import ShareContent
from apps.commissioning.services.share_content_service import ShareContentService
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    ShareArticleFactory,
    ShareContentFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
)
from core.errors import JasminError


# ---------------------------------------------------------------------------
# _extract_day_variations  (pure — no DB)
# ---------------------------------------------------------------------------
class TestExtractDayVariations:
    def test_extracts_basic_key(self):
        data = {"day_1_variation_2": "5.5", "other_key": "ignored"}
        result = ShareContentService._extract_day_variations(data)
        assert len(result) == 1
        day, var, amount, tour, station = result[0]
        assert day == "1"
        assert var == "2"
        assert amount == Decimal("5.5")
        assert tour is None
        assert station is None

    def test_extracts_tour_key(self):
        data = {"day_1_variation_2_tour_3": "10"}
        result = ShareContentService._extract_day_variations(data)
        assert len(result) == 1
        _, _, _, tour, station = result[0]
        assert tour == "3"
        assert station is None

    def test_extracts_station_key(self):
        data = {"day_1_variation_2_station_99": "7"}
        result = ShareContentService._extract_day_variations(data)
        assert len(result) == 1
        _, _, _, tour, station = result[0]
        assert tour is None
        assert station == "99"

    def test_skips_none_and_empty(self):
        data = {
            "day_1_variation_2": None,
            "day_1_variation_3": "",
            "day_1_variation_4": "undefined",
        }
        result = ShareContentService._extract_day_variations(data)
        assert result == []

    def test_raises_invalid_amount_on_invalid_decimal(self):
        """Bad amount values surface as an ``InvalidAmount`` (JasminError) whose
        ``field`` names the offending key so the frontend can flag the input.

        Was previously a silent ``continue`` (the row was dropped from
        the save with no signal to the user).
        """
        from apps.commissioning.errors import InvalidAmount

        data = {"day_1_variation_2": "not_a_number"}
        with pytest.raises(InvalidAmount) as exc_info:
            ShareContentService._extract_day_variations(data)
        assert exc_info.value.field == "day_1_variation_2"

    def test_bare_dropped_when_station_specific_also_present(self):
        """In stations/tours planning mode the frontend ships BOTH the
        bare row-level amount AND the station/tour-specific amount for
        the same ``(day, variation)``. Both representations carry the
        same value (the bare key is the UI's sum across stations) —
        keeping both creates the same ShareContent twice and trips
        the downstream ``(share, station)`` dedupe with "Duplicate
        planning entry …".

        The extractor must keep ONLY the specific entry in that case.
        """
        data = {
            "day_X_variation_Y": "4",  # bare
            "day_X_variation_Y_station_Z": "4",  # specific
        }
        result = ShareContentService._extract_day_variations(data)
        assert len(result) == 1
        day, var, amount, tour, station = result[0]
        assert (day, var, amount) == ("X", "Y", Decimal("4"))
        assert tour is None
        assert station == "Z"

    def test_station_wins_over_tour_when_both_present(self):
        """If a single ``(day, variation)`` group has BOTH a station
        entry AND a tour entry, the extractor must keep ONLY the
        station entries — they're more specific (name an exact
        delivery station). Keeping the tour entry too would let it
        expand to every station on that tour at create-time, and
        any tour station that's already named explicitly would
        collide and trip the ``Duplicate planning entry …`` guard
        downstream.
        """
        data = {
            "day_X_variation_Y": "5",  # bare
            "day_X_variation_Y_tour_1": "5",  # tour
            "day_X_variation_Y_station_Z": "5",  # station (wins)
        }
        result = ShareContentService._extract_day_variations(data)
        assert len(result) == 1
        day, var, amount, tour, station = result[0]
        assert (day, var, amount, tour, station) == (
            "X",
            "Y",
            Decimal("5"),
            None,
            "Z",
        )

    def test_tour_kept_when_only_tour_specifics_present(self):
        """A group with tour entries but NO station entries is in
        tours-tier mode — keep the tour entries, drop the bare."""
        data = {
            "day_X_variation_Y": "5",  # bare (dropped)
            "day_X_variation_Y_tour_1": "5",  # tour (kept)
        }
        result = ShareContentService._extract_day_variations(data)
        assert len(result) == 1
        day, var, amount, tour, station = result[0]
        assert (day, var, amount, tour, station) == (
            "X",
            "Y",
            Decimal("5"),
            "1",
            None,
        )

    def test_bare_kept_when_no_specific_entry(self):
        """In basic (non-stations/tours) planning mode only the bare
        key comes back. The extractor must NOT drop it — the bare
        amount is the canonical value that fans out to every
        station downstream.
        """
        data = {"day_X_variation_Y": "4"}
        result = ShareContentService._extract_day_variations(data)
        assert len(result) == 1
        assert result[0] == ("X", "Y", Decimal("4"), None, None)

    def test_multiple_specifics_under_same_group_all_kept(self):
        """If a row genuinely has different amounts split across
        multiple stations (or tours) for the same variation, every
        specific entry must come through — only the bare aggregate
        is the duplicate."""
        data = {
            "day_X_variation_Y": "10",  # bare aggregate
            "day_X_variation_Y_station_A": "3",
            "day_X_variation_Y_station_B": "7",
        }
        result = ShareContentService._extract_day_variations(data)
        assert len(result) == 2
        stations = sorted(entry[4] for entry in result)
        assert stations == ["A", "B"]
        amounts = sorted(entry[2] for entry in result)
        assert amounts == [Decimal("3"), Decimal("7")]

    def test_zero_amount_entries_dropped(self):
        """The frontend planning grid ships a zero-filled scaffold
        for EVERY tour/station on the row regardless of what the
        user touched. Treating those zeros as real planning entries
        spawns phantom ``ShareContent`` rows, and the zero-amount
        tour entry would expand to all stations on the tour and
        clash with the explicit station entry the user did fill in
        — the exact "Duplicate planning entry …" symptom that
        triggers the dedupe guard downstream.
        """
        data = {
            "day_X_variation_Y_station_A": "5",
            "day_X_variation_Y_tour_1": 0,  # noise
            "day_X_variation_Y_station_B": 0,  # noise
        }
        result = ShareContentService._extract_day_variations(data)
        assert len(result) == 1
        day, var, amount, tour, station = result[0]
        assert (day, var, amount, tour, station) == (
            "X",
            "Y",
            Decimal("5"),
            None,
            "A",
        )

    def test_zero_bare_dropped_even_without_specifics(self):
        """A row where the user typed nothing should not produce
        a planning entry at all. ``0`` for the bare key is the
        scaffold's default, not a deliberate user input.
        """
        data = {"day_X_variation_Y": 0}
        result = ShareContentService._extract_day_variations(data)
        assert result == []


# ---------------------------------------------------------------------------
# _get_share_article
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetShareArticle:
    def test_returns_article(self, tenant):
        article = ShareArticleFactory()
        result = ShareContentService._get_share_article(str(article.pk))
        assert result == article

    def test_raises_for_nonexistent(self, tenant):
        with pytest.raises(JasminError, match="does not exist"):
            ShareContentService._get_share_article("999999")


# ---------------------------------------------------------------------------
# process_share_planning_data
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestProcessSharePlanningData:
    @patch.object(
        ShareContentService, "create_all_theoretical_objects", return_value={}
    )
    @patch.object(ShareContentService, "create_movements", return_value=[])
    def test_creates_share_contents(self, _mock_movements, _mock_theo, tenant):
        article = ShareArticleFactory()
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2)
        _station_day = DeliveryStationDayFactory(delivery_day=delivery_day)

        data = {
            "year": 2026,
            "delivery_week": 15,
            "share_article": str(article.pk),
            "unit": "KG",
            "size": "M",
            f"day_{delivery_day.pk}_variation_{variation.pk}": "3.5",
        }

        svc = ShareContentService()
        result = svc.process_share_planning_data(data)

        assert len(result) >= 1
        assert all(isinstance(sc, ShareContent) for sc in result)
        assert result[0].share_article == article
        assert result[0].amount == Decimal("3.5")

    def test_raises_for_missing_fields(self, tenant):
        svc = ShareContentService()
        with pytest.raises(JasminError, match="Missing required fields"):
            svc.process_share_planning_data({"year": 2026})

    @patch.object(
        ShareContentService, "create_all_theoretical_objects", return_value={}
    )
    @patch.object(ShareContentService, "create_movements", return_value=[])
    def test_returns_empty_when_no_day_variations(self, _m1, _m2, tenant):
        # "All cells zero" (or no day_variation_ keys at all) is a valid
        # UPDATE: it means the user cleared every cell on this slot, which
        # in this codebase means "no human plan" (equivalent to amount =
        # NULL/0 — see ``forecast_service._delete_orphaned_share_contents``).
        # ``process_share_planning_data`` returns ``[]`` and lets the
        # caller (``replace_share_planning``) decide what survives the
        # clear — forecast-attached rows stay, ad-hoc rows go. The CREATE
        # viewset enforces "no empty payload" separately.
        article = ShareArticleFactory()
        data = {
            "year": 2026,
            "delivery_week": 15,
            "share_article": str(article.pk),
            "unit": "KG",
            "size": "M",
        }
        svc = ShareContentService()
        assert svc.process_share_planning_data(data) == []


# ---------------------------------------------------------------------------
# replace_share_planning  (empty-clear semantics)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestReplaceSharePlanningEmptyClear:
    """Pins the "user cleared every cell" branch: forecast-attached rows
    survive with amount=None so the row stays visible in the planning
    list; ad-hoc (no-forecast) rows are deleted because their only
    reason to exist was the now-cleared amount.
    """

    @patch(
        "apps.commissioning.services.recompute.recompute_shares",
        return_value=None,
    )
    @patch(
        "apps.commissioning.services.snapshot_service.SnapshotService.cascade_for_movements",
        return_value=None,
    )
    def test_empty_data_spares_forecast_attached_rows(
        self, _mock_cascade, _mock_recompute, tenant
    ):
        from apps.commissioning.tests.factories import ForecastFactory

        article = ShareArticleFactory()
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2)
        DeliveryStationDayFactory(delivery_day=delivery_day)
        share = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=variation,
        )
        forecast = ForecastFactory(
            year=2026,
            delivery_week=15,
            share_article=article,
            unit="KG",
            size="M",
        )
        forecast_row = ShareContentFactory(
            share=share,
            share_article=article,
            forecast=forecast,
            amount=Decimal("5"),
            unit="KG",
            size="M",
        )
        adhoc_row = ShareContentFactory(
            share=share,
            share_article=article,
            forecast=None,
            amount=Decimal("3"),
            unit="KG",
            size="M",
        )

        svc = ShareContentService()
        # Empty data == every cell on this slot was cleared on the
        # frontend.
        result = svc.replace_share_planning(
            year=2026,
            delivery_week=15,
            share_article_id=str(article.pk),
            unit="KG",
            size="M",
            data={},
        )

        forecast_row.refresh_from_db()
        assert forecast_row.amount is None
        assert not ShareContent.objects.filter(pk=adhoc_row.pk).exists()
        # Response includes the surviving forecast row so the frontend
        # still renders the planning row (amount=None reads as 0).
        result_ids = {sc.pk for sc in result}
        assert forecast_row.pk in result_ids

    @patch(
        "apps.commissioning.services.snapshot_service.SnapshotService.cascade_for_movements",
        return_value=None,
    )
    @patch(
        "apps.commissioning.services.recompute.recompute_shares",
        return_value=None,
    )
    def test_empty_data_recomputes_affected_shares(
        self, mock_recompute, _mock_cascade, tenant
    ):
        """Clearing every cell must rebuild theoreticals + SHARECONTENT
        movements for the affected shares. A spared forecast row keeps its
        amount set to None, so without a recompute its harvest/production
        demand built off the old amount would linger and overstate output.
        """
        from apps.commissioning.tests.factories import ForecastFactory

        article = ShareArticleFactory()
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2)
        DeliveryStationDayFactory(delivery_day=delivery_day)
        share = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=variation,
        )
        forecast = ForecastFactory(
            year=2026,
            delivery_week=15,
            share_article=article,
            unit="KG",
            size="M",
        )
        ShareContentFactory(
            share=share,
            share_article=article,
            forecast=forecast,
            amount=Decimal("5"),
            unit="KG",
            size="M",
        )

        svc = ShareContentService()
        svc.replace_share_planning(
            year=2026,
            delivery_week=15,
            share_article_id=str(article.pk),
            unit="KG",
            size="M",
            data={},
        )

        mock_recompute.assert_called_once()
        recomputed_ids = mock_recompute.call_args.args[0]
        assert share.id in recomputed_ids

    @patch(
        "apps.commissioning.services.snapshot_service.SnapshotService.cascade_for_movements",
        return_value=None,
    )
    def test_empty_clear_runs_real_recompute_over_none_amount_row(
        self, _mock_cascade, tenant
    ):
        """Regression: clearing every cell sets the spared forecast row's
        amount to None, then recompute runs FOR REAL (not mocked, unlike the
        sibling tests — which is why the bug slipped through). create_movements
        must not choke on ``Decimal(str(None))`` — a None-amount row simply
        contributes no SHARECONTENT movement. Without the guard this raised
        decimal.InvalidOperation → HTTP 500 on the PUT.
        """
        from apps.commissioning.models import MovementShareArticle
        from apps.commissioning.tests.factories import ForecastFactory

        article = ShareArticleFactory()
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2)
        DeliveryStationDayFactory(delivery_day=delivery_day)
        share = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=variation,
        )
        forecast = ForecastFactory(
            year=2026,
            delivery_week=15,
            share_article=article,
            unit="KG",
            size="M",
        )
        forecast_row = ShareContentFactory(
            share=share,
            share_article=article,
            forecast=forecast,
            amount=Decimal("5"),
            unit="KG",
            size="M",
        )

        svc = ShareContentService()
        # Must NOT raise (previously Decimal(str(None)) → InvalidOperation).
        result = svc.replace_share_planning(
            year=2026,
            delivery_week=15,
            share_article_id=str(article.pk),
            unit="KG",
            size="M",
            data={},
        )

        forecast_row.refresh_from_db()
        assert forecast_row.amount is None
        assert forecast_row.pk in {sc.pk for sc in result}
        # The cleared row produces no SHARECONTENT movement (skipped, not 0).
        assert not MovementShareArticle.objects.filter(
            share_content=forecast_row, movement_type="SHARECONTENT"
        ).exists()


# ---------------------------------------------------------------------------
# get_share_content_as_frontend_data
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetShareContentAsFrontendData:
    @patch(
        "apps.commissioning.services.share_content_service.StockService.get_theoretical_current_stock",
        return_value={},
    )
    def test_groups_by_article(self, _mock_stock, tenant):
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)

        share = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=variation,
        )

        article = ShareArticleFactory()
        sc = ShareContentFactory(
            share=share,
            share_article=article,
            delivery_station=station_day.delivery_station,
            amount=Decimal("5"),
            unit="KG",
            size="M",
        )

        svc = ShareContentService()
        result = svc.get_share_content_as_frontend_data([sc])

        assert len(result) == 1
        assert result[0]["share_article"] == article.pk
        assert result[0]["unit"] == "KG"

    @patch(
        "apps.commissioning.services.share_content_service.StockService.get_theoretical_current_stock",
        return_value={},
    )
    def test_empty_for_no_data(self, _mock_stock, tenant):
        svc = ShareContentService()
        result = svc.get_share_content_as_frontend_data([])
        assert result == []


# ---------------------------------------------------------------------------
# get_share_content_for_week
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetShareContentForWeek:
    @patch(
        "apps.commissioning.services.share_content_service.StockService.get_theoretical_current_stock",
        return_value={},
    )
    def test_returns_data_for_week(self, _mock_stock, tenant):
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)

        share = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=variation,
        )

        article = ShareArticleFactory()
        ShareContentFactory(
            share=share,
            share_article=article,
            delivery_station=station_day.delivery_station,
            amount=Decimal("7"),
            unit="KG",
            size="M",
        )

        svc = ShareContentService()
        result = svc.get_share_content_for_week(
            year=2026,
            delivery_week=15,
            share_option="HARVEST_SHARE",
        )

        assert len(result) >= 1


# ---------------------------------------------------------------------------
# _get_kg_per_piece_with_fallback
# ---------------------------------------------------------------------------
class TestGetKgPerPieceWithFallback:
    def test_returns_from_share_content(self):
        sc = MagicMock()
        sc.kg_per_piece = Decimal("0.5")
        assert ShareContentService._get_kg_per_piece_with_fallback(sc) == Decimal("0.5")

    def test_fallback_to_article(self):
        sc = MagicMock()
        sc.kg_per_piece = None
        sc.unit = "PCS"
        sc.size = "M"
        sc.share_article.kg_per_piece_M = Decimal("0.3")
        result = ShareContentService._get_kg_per_piece_with_fallback(sc)
        assert result == Decimal("0.3")

    def test_none_for_kg_unit(self):
        sc = MagicMock()
        sc.kg_per_piece = None
        sc.unit = "KG"
        sc.size = "M"
        assert ShareContentService._get_kg_per_piece_with_fallback(sc) is None


# ---------------------------------------------------------------------------
# get_share_content_for_week — stock-only rows are share_option scoped
# ---------------------------------------------------------------------------


_STOCK_PATCH = (
    "apps.commissioning.services.share_content_service."
    "StockService.get_theoretical_current_stock"
)


def _stock_entry(amount: float) -> dict:
    """A single (article, unit, size, storage) theoretical-stock value with
    no physical count, mirroring ``StockService.get_theoretical_current_stock``."""
    return {
        "theoretical_current_stock": amount,
        "current_stock_amount": None,
        "note": "",
    }


@pytest.mark.django_db
class TestStockOnlyRowsShareOptionFilter:
    """``get_share_content_for_week`` synthesizes "stock-only" rows for
    articles that still have leftover stock at the start of the week. Those
    rows must be limited to articles actually assigned to the requested
    ``share_option`` (via ``share_option`` / ``share_option2`` /
    ``share_option3`` on ShareArticle) — otherwise leftover broccoli would
    surface on the honey-share planner.

    No ``ShareContent`` is created, so every returned row is a synthesized
    stock-only row.
    """

    def test_excludes_article_of_other_share_option(self, tenant):
        broccoli = ShareArticleFactory(name="Broccoli", share_option="HARVEST_SHARE")
        honey = ShareArticleFactory(name="Honey", share_option="HONEY_SHARE")

        with patch(_STOCK_PATCH) as mock_stock:
            mock_stock.return_value = {
                (broccoli.id, "KG", "", "storage-1"): _stock_entry(12.0),
                (honey.id, "KG", "", "storage-1"): _stock_entry(5.0),
            }
            rows = ShareContentService().get_share_content_for_week(
                year=2026, delivery_week=10, share_option="HONEY_SHARE"
            )

        article_ids = {row["share_article"] for row in rows}
        assert honey.id in article_ids
        assert broccoli.id not in article_ids

    def test_includes_article_of_requested_share_option(self, tenant):
        broccoli = ShareArticleFactory(name="Broccoli", share_option="HARVEST_SHARE")

        with patch(_STOCK_PATCH) as mock_stock:
            mock_stock.return_value = {
                (broccoli.id, "KG", "", "storage-1"): _stock_entry(12.0),
            }
            rows = ShareContentService().get_share_content_for_week(
                year=2026, delivery_week=10, share_option="HARVEST_SHARE"
            )

        assert broccoli.id in {row["share_article"] for row in rows}

    def test_secondary_share_option_counts_as_assignment(self, tenant):
        # Primary harvest, secondary honey → it belongs to the honey planner too.
        dual = ShareArticleFactory(
            name="Dual",
            share_option="HARVEST_SHARE",
            share_option2="HONEY_SHARE",
        )

        with patch(_STOCK_PATCH) as mock_stock:
            mock_stock.return_value = {
                (dual.id, "KG", "", "storage-1"): _stock_entry(3.0),
            }
            rows = ShareContentService().get_share_content_for_week(
                year=2026, delivery_week=10, share_option="HONEY_SHARE"
            )

        assert dual.id in {row["share_article"] for row in rows}
