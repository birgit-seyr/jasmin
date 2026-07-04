"""Tests for SharesDayChangeService.

Verify that updating day fields on Share rows:
1. Persists the new field values.
2. Recreates linked TheoreticalHarvest/Wash/Clean and SHARECONTENT
   movements with the new days.
3. Refuses past weeks unless ``force=True``.
4. Skips recomputation when no recompute-relevant field actually changed.
5. Crosses ISO week boundaries correctly via ``compute_rolled_back_week``.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.commissioning.errors import PastWeekError
from apps.commissioning.models import (
    MovementShareArticle,
    ShareContent,
    TheoreticalCleanAmount,
    TheoreticalHarvest,
    TheoreticalWashAmount,
)
from apps.commissioning.services.shares_day_change_service import (
    SharesDayChangeService,
)
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    ForecastFactory,
    ShareArticleFactory,
    ShareContentFactory,
    ShareDeliveryFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
    StorageFactory,
    SubscriptionFactory,
)

# Use a future week so past-week guard doesn't reject by default.
# (Tests run with frozen "today" of 2026-04-22 = ISO week 17.)
FUTURE_YEAR = 2026
FUTURE_WEEK = 30

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


def _make_totals(share_contents, quantity=3):
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


def _build_share_with_content(
    *,
    year: int = FUTURE_YEAR,
    delivery_week: int = FUTURE_WEEK,
    delivery_day_number: int = 5,  # Saturday
    harvesting_day: int = 1,
    washing_day: int = 1,
    cleaning_day: int = 1,
    packing_day: int = 5,
    with_forecast: bool = True,
    # washing/cleaning are mutually exclusive per line (DB constraint) — default to
    # a washed line. Tests that need BOTH steps use
    # ``_build_share_with_wash_and_clean_contents`` (two lines: one washed, one cleaned).
    washing: bool = True,
    cleaning: bool = False,
):
    """Create a Share + ShareContent (+ optional Forecast) ready for recompute tests."""
    storage = StorageFactory(is_short_term_harvest_storage=True)
    article = ShareArticleFactory()
    sdd = SharesDeliveryDayFactory(day_number=delivery_day_number)
    stv = ShareTypeVariationFactory()
    share = ShareFactory(
        year=year,
        delivery_week=delivery_week,
        delivery_day=sdd,
        share_type_variation=stv,
        harvesting_day=harvesting_day,
        washing_day=washing_day,
        cleaning_day=cleaning_day,
        packing_day=packing_day,
    )
    station = DeliveryStationFactory()
    DeliveryStationDayFactory(delivery_station=station, delivery_day=sdd)

    forecast = None
    if with_forecast:
        forecast = ForecastFactory(
            share_article=article,
            year=year,
            delivery_week=delivery_week,
            size="M",
            storage=storage,
        )

    sc = ShareContentFactory(
        share=share,
        share_article=article,
        delivery_station=station,
        amount=Decimal("5"),
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
    return share, sc, storage


def _build_share_with_wash_and_clean_contents(
    *,
    year: int = FUTURE_YEAR,
    delivery_week: int = FUTURE_WEEK,
    delivery_day_number: int = 5,  # Saturday
    harvesting_day: int = 1,
    washing_day: int = 1,
    cleaning_day: int = 1,
    packing_day: int = 5,
    with_forecast: bool = True,
):
    """One Share with TWO ShareContents — one washed, one cleaned.

    A line can't be both washed and cleaned (DB constraint), so a share whose
    goods-flow spans both steps is modelled as two lines (distinct articles).
    Returns ``(share, sc_wash, sc_clean, storage)``.
    """
    storage = StorageFactory(is_short_term_harvest_storage=True)
    sdd = SharesDeliveryDayFactory(day_number=delivery_day_number)
    stv = ShareTypeVariationFactory()
    share = ShareFactory(
        year=year,
        delivery_week=delivery_week,
        delivery_day=sdd,
        share_type_variation=stv,
        harvesting_day=harvesting_day,
        washing_day=washing_day,
        cleaning_day=cleaning_day,
        packing_day=packing_day,
    )
    station = DeliveryStationFactory()
    DeliveryStationDayFactory(delivery_station=station, delivery_day=sdd)

    contents = []
    for washed in (True, False):
        article = ShareArticleFactory()
        forecast = None
        if with_forecast:
            forecast = ForecastFactory(
                share_article=article,
                year=year,
                delivery_week=delivery_week,
                size="M",
                storage=storage,
            )
        sc = ShareContentFactory(
            share=share,
            share_article=article,
            delivery_station=station,
            amount=Decimal("5"),
            unit="KG",
            size="M",
            forecast=forecast,
            washing=washed,
            cleaning=not washed,
        )
        contents.append(
            ShareContent.objects.select_related(
                "share__share_type_variation",
                "share__delivery_day",
                "share_article",
                "forecast",
                "seller",
            ).get(pk=sc.pk)
        )
    sc_wash, sc_clean = contents
    return share, sc_wash, sc_clean, storage


# ═══════════════════════════════════════════════════════
# Past-week guard
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestPastWeekGuard:
    def test_past_week_raises_without_force(self, tenant):
        share, _sc, _storage = _build_share_with_content(
            year=2026, delivery_week=15  # week 15 < today (week 17)
        )
        with pytest.raises(PastWeekError):
            SharesDayChangeService.apply(
                year=2026,
                delivery_week=15,
                day_number=share.delivery_day.day_number,
                data={"harvesting_day": 0},
            )

    def test_past_week_allowed_with_force(self, tenant):
        share, _sc, _storage = _build_share_with_content(year=2026, delivery_week=15)
        with _patch_totals(_make_totals([_sc])):
            result = SharesDayChangeService.apply(
                year=2026,
                delivery_week=15,
                day_number=share.delivery_day.day_number,
                data={"harvesting_day": 0},
                force=True,
            )
        assert result["changed_fields"] == ["harvesting_day"]


# ═══════════════════════════════════════════════════════
# No matching shares
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestNoMatchingShares:
    def test_returns_empty_when_no_shares(self, tenant):
        result = SharesDayChangeService.apply(
            year=FUTURE_YEAR,
            delivery_week=FUTURE_WEEK,
            day_number=3,
            data={"harvesting_day": 0},
        )
        assert result == {
            "updated_share_ids": [],
            "recomputed_share_content_ids": [],
            "changed_fields": [],
        }


# ═══════════════════════════════════════════════════════
# No actual change → no recompute
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestNoChange:
    def test_no_change_does_not_recompute(self, tenant):
        share, sc, _storage = _build_share_with_content(harvesting_day=1)
        with _patch_totals(_make_totals([sc])):
            from apps.commissioning.services.share_content_service import (
                ShareContentService,
            )

            ShareContentService().create_all_theoretical_objects([sc])

        # Snapshot existing theoretical IDs
        existing_th_ids = set(
            TheoreticalHarvest.objects.filter(share_content=sc).values_list(
                "id", flat=True
            )
        )

        # Apply with the SAME harvesting_day
        result = SharesDayChangeService.apply(
            year=FUTURE_YEAR,
            delivery_week=FUTURE_WEEK,
            day_number=share.delivery_day.day_number,
            data={"harvesting_day": 1},
        )
        assert result["changed_fields"] == []
        assert result["recomputed_share_content_ids"] == []
        # Old theoreticals still there (same ids)
        new_th_ids = set(
            TheoreticalHarvest.objects.filter(share_content=sc).values_list(
                "id", flat=True
            )
        )
        assert new_th_ids == existing_th_ids

    def test_irrelevant_field_change_does_not_recompute(self, tenant):
        """Changing changed_day_number or get_current_stock_day must NOT
        trigger theoretical recreation."""
        share, sc, _storage = _build_share_with_content()
        with _patch_totals(_make_totals([sc])):
            from apps.commissioning.services.share_content_service import (
                ShareContentService,
            )

            ShareContentService().create_all_theoretical_objects([sc])

        existing_th_ids = set(
            TheoreticalHarvest.objects.filter(share_content=sc).values_list(
                "id", flat=True
            )
        )

        result = SharesDayChangeService.apply(
            year=FUTURE_YEAR,
            delivery_week=FUTURE_WEEK,
            day_number=share.delivery_day.day_number,
            data={
                "changed_day_number": 4,
                "get_current_stock_day": 3,
            },
        )
        assert set(result["changed_fields"]) == {
            "changed_day_number",
            "get_current_stock_day",
        }
        assert result["recomputed_share_content_ids"] == []
        assert (
            set(
                TheoreticalHarvest.objects.filter(share_content=sc).values_list(
                    "id", flat=True
                )
            )
            == existing_th_ids
        )

    def test_no_share_contents_does_not_recompute(self, tenant):
        """Day field changed but no ShareContent yet → only Share row touched."""
        sdd = SharesDeliveryDayFactory(day_number=3)
        share = ShareFactory(
            year=FUTURE_YEAR,
            delivery_week=FUTURE_WEEK,
            delivery_day=sdd,
            harvesting_day=1,
        )
        result = SharesDayChangeService.apply(
            year=FUTURE_YEAR,
            delivery_week=FUTURE_WEEK,
            day_number=3,
            data={"harvesting_day": 0},
        )
        assert result["changed_fields"] == ["harvesting_day"]
        assert result["recomputed_share_content_ids"] == []
        share.refresh_from_db()
        assert share.harvesting_day == 0


# ═══════════════════════════════════════════════════════
# Recompute on day change
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestRecomputeOnDayChange:
    def test_harvesting_day_change_recreates_theoretical_harvest(self, tenant):
        share, sc, _storage = _build_share_with_content(
            harvesting_day=1, delivery_day_number=5
        )
        with _patch_totals(_make_totals([sc])):
            from apps.commissioning.services.share_content_service import (
                ShareContentService,
            )

            ShareContentService().create_all_theoretical_objects([sc])

        # Snapshot
        old_th = TheoreticalHarvest.objects.get(share_content=sc)
        assert old_th.day_number == 1
        old_th_id = old_th.id

        with _patch_totals(_make_totals([sc])):
            result = SharesDayChangeService.apply(
                year=FUTURE_YEAR,
                delivery_week=FUTURE_WEEK,
                day_number=share.delivery_day.day_number,
                data={"harvesting_day": 3},
            )

        assert "harvesting_day" in result["changed_fields"]
        assert sc.id in result["recomputed_share_content_ids"]

        # Old TheoreticalHarvest deleted, new one with day=3 exists
        assert not TheoreticalHarvest.objects.filter(id=old_th_id).exists()
        new_th = TheoreticalHarvest.objects.get(share_content=sc)
        assert new_th.day_number == 3
        # delivery day = 5, harvesting_day = 3 (no rollback)
        assert new_th.delivery_week == FUTURE_WEEK
        assert new_th.year == FUTURE_YEAR

    def test_washing_and_cleaning_day_change(self, tenant):
        # A washed line and a cleaned line on the same share; a Share-level
        # washing_day/cleaning_day change must recompute both.
        share, sc_wash, sc_clean, _storage = _build_share_with_wash_and_clean_contents(
            washing_day=1,
            cleaning_day=1,
            delivery_day_number=5,
            with_forecast=False,
        )
        contents = [sc_wash, sc_clean]
        with _patch_totals(_make_totals(contents)):
            from apps.commissioning.services.share_content_service import (
                ShareContentService,
            )

            ShareContentService().create_all_theoretical_objects(contents)

        old_wash_id = TheoreticalWashAmount.objects.get(share_content=sc_wash).id
        old_clean_id = TheoreticalCleanAmount.objects.get(share_content=sc_clean).id

        with _patch_totals(_make_totals(contents)):
            SharesDayChangeService.apply(
                year=FUTURE_YEAR,
                delivery_week=FUTURE_WEEK,
                day_number=share.delivery_day.day_number,
                data={"washing_day": 2, "cleaning_day": 4},
            )

        assert not TheoreticalWashAmount.objects.filter(id=old_wash_id).exists()
        assert not TheoreticalCleanAmount.objects.filter(id=old_clean_id).exists()

        new_wash = TheoreticalWashAmount.objects.get(share_content=sc_wash)
        new_clean = TheoreticalCleanAmount.objects.get(share_content=sc_clean)
        assert new_wash.day_number == 2
        assert new_clean.day_number == 4

    def test_packing_day_change_recreates_sharecontent_movement(self, tenant):
        share, sc, storage = _build_share_with_content(
            packing_day=5,
            delivery_day_number=5,
            washing=False,
            cleaning=False,
            with_forecast=False,
        )
        with _patch_totals(_make_totals([sc])):
            from apps.commissioning.services.share_content_service import (
                ShareContentService,
            )

            svc = ShareContentService()
            svc.create_movements([sc])

        old_mv_ids = set(
            MovementShareArticle.objects.filter(
                share_content=sc, movement_type="SHARECONTENT"
            ).values_list("id", flat=True)
        )
        assert old_mv_ids, "expected at least one SHARECONTENT movement"

        with _patch_totals(_make_totals([sc])):
            SharesDayChangeService.apply(
                year=FUTURE_YEAR,
                delivery_week=FUTURE_WEEK,
                day_number=share.delivery_day.day_number,
                data={"packing_day": 3},
            )

        # All old SHARECONTENT movements gone
        assert not MovementShareArticle.objects.filter(id__in=old_mv_ids).exists()
        # New ones created
        new_mvs = MovementShareArticle.objects.filter(
            share_content=sc, movement_type="SHARECONTENT"
        )
        assert new_mvs.exists()

    def test_share_field_persisted(self, tenant):
        share, sc, _storage = _build_share_with_content(harvesting_day=1)
        with _patch_totals(_make_totals([sc])):
            SharesDayChangeService.apply(
                year=FUTURE_YEAR,
                delivery_week=FUTURE_WEEK,
                day_number=share.delivery_day.day_number,
                data={"harvesting_day": 4},
            )
        share.refresh_from_db()
        assert share.harvesting_day == 4


# ═══════════════════════════════════════════════════════
# ISO week boundary rollback
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestWeekBoundaryRollback:
    def test_harvesting_day_after_delivery_day_rolls_back_one_week(self, tenant):
        """harvesting_day > delivery_day → theoretical lands in PREVIOUS week."""
        share, sc, _storage = _build_share_with_content(
            delivery_day_number=2,  # Wed
            harvesting_day=1,
        )
        with _patch_totals(_make_totals([sc])):
            from apps.commissioning.services.share_content_service import (
                ShareContentService,
            )

            ShareContentService().create_all_theoretical_objects([sc])
            SharesDayChangeService.apply(
                year=FUTURE_YEAR,
                delivery_week=FUTURE_WEEK,
                day_number=2,
                data={"harvesting_day": 5},  # Saturday > Wednesday → rollback
            )

        new_th = TheoreticalHarvest.objects.get(share_content=sc)
        assert new_th.day_number == 5
        # Rolled back to previous ISO week
        assert (new_th.year, new_th.delivery_week) != (FUTURE_YEAR, FUTURE_WEEK)
        # Specifically: previous week
        assert new_th.delivery_week == FUTURE_WEEK - 1


# ═══════════════════════════════════════════════════════
# Lock & atomicity smoke test
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestAtomicity:
    def test_apply_runs_in_transaction(self, tenant):
        """Sanity: errors during recompute leave no partial state."""
        share, sc, _storage = _build_share_with_content(harvesting_day=1)

        # Create initial theoreticals
        with _patch_totals(_make_totals([sc])):
            from apps.commissioning.services.share_content_service import (
                ShareContentService,
            )

            ShareContentService().create_all_theoretical_objects([sc])

        old_th_id = TheoreticalHarvest.objects.get(share_content=sc).id

        # Force create_all_theoretical_objects to blow up mid-way.
        # The service imports ShareContentService lazily, so patch at source.
        with patch(
            "apps.commissioning.services.share_content_service"
            ".ShareContentService.create_all_theoretical_objects",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError):
                SharesDayChangeService.apply(
                    year=FUTURE_YEAR,
                    delivery_week=FUTURE_WEEK,
                    day_number=share.delivery_day.day_number,
                    data={"harvesting_day": 4},
                )

        # Transaction rolled back: old theoretical still exists, share unchanged
        assert TheoreticalHarvest.objects.filter(id=old_th_id).exists()
        share.refresh_from_db()
        assert share.harvesting_day == 1


# ═══════════════════════════════════════════════════════
# Full-pipeline consistency: stock & sums must be invariant
# ═══════════════════════════════════════════════════════


def _theoretical_total(share_contents) -> dict[str, Decimal]:
    """Return total amount per theoretical model across the given ShareContents."""
    sc_ids = [sc.id for sc in share_contents]
    return {
        "harvest": sum(
            (
                t.amount or Decimal("0")
                for t in TheoreticalHarvest.objects.filter(share_content_id__in=sc_ids)
            ),
            Decimal("0"),
        ),
        "wash": sum(
            (
                t.amount or Decimal("0")
                for t in TheoreticalWashAmount.objects.filter(
                    share_content_id__in=sc_ids
                )
            ),
            Decimal("0"),
        ),
        "clean": sum(
            (
                t.amount or Decimal("0")
                for t in TheoreticalCleanAmount.objects.filter(
                    share_content_id__in=sc_ids
                )
            ),
            Decimal("0"),
        ),
    }


def _movement_totals(share_contents) -> dict[str, Decimal]:
    """Return summed movement amounts per source category."""
    sc_ids = [sc.id for sc in share_contents]

    sharecontent_total = sum(
        (
            mv.amount
            for mv in MovementShareArticle.objects.filter(
                share_content_id__in=sc_ids,
                movement_type="SHARECONTENT",
            )
        ),
        Decimal("0"),
    )

    th_ids = list(
        TheoreticalHarvest.objects.filter(share_content_id__in=sc_ids).values_list(
            "id", flat=True
        )
    )
    tw_ids = list(
        TheoreticalWashAmount.objects.filter(share_content_id__in=sc_ids).values_list(
            "id", flat=True
        )
    )
    tc_ids = list(
        TheoreticalCleanAmount.objects.filter(share_content_id__in=sc_ids).values_list(
            "id", flat=True
        )
    )

    return {
        "sharecontent": sharecontent_total,
        "theoretical_harvest_movements": sum(
            (
                mv.amount
                for mv in MovementShareArticle.objects.filter(
                    theoretical_harvest_id__in=th_ids
                )
            ),
            Decimal("0"),
        ),
        "theoretical_wash_movements": sum(
            (
                mv.amount
                for mv in MovementShareArticle.objects.filter(
                    theoretical_wash_amount_id__in=tw_ids
                )
            ),
            Decimal("0"),
        ),
        "theoretical_clean_movements": sum(
            (
                mv.amount
                for mv in MovementShareArticle.objects.filter(
                    theoretical_clean_amount_id__in=tc_ids
                )
            ),
            Decimal("0"),
        ),
    }


@pytest.mark.django_db
class TestPostChangeConsistency:
    """Full pipeline: theoreticals + movements + snapshots must remain
    consistent (same totals, same end-of-time stock balance) after a day
    change. Only the *positions in time* of the rows should move."""

    def test_stock_and_totals_unchanged_after_day_change(self, tenant):
        from apps.commissioning.services.share_content_service import (
            ShareContentService,
        )
        from apps.commissioning.services.snapshot_service import SnapshotService

        # Wash and clean can't coexist on one line, so the goods-flow that spans
        # both steps is two lines (one washed, one cleaned) on the same share.
        share, sc_wash, sc_clean, storage = _build_share_with_wash_and_clean_contents(
            delivery_day_number=5,  # Saturday
            harvesting_day=1,
            washing_day=1,
            cleaning_day=1,
            packing_day=5,
            with_forecast=True,
        )
        contents = [sc_wash, sc_clean]
        svc = ShareContentService()

        # ── Build initial state: theoreticals + movements ──
        with _patch_totals(_make_totals(contents, quantity=4)):
            svc.create_all_theoretical_objects(contents)
            svc.create_movements(contents)

        # Sanity: we actually got rows — harvest on both, wash on the washed line,
        # clean on the cleaned line, movements on both.
        assert (
            TheoreticalHarvest.objects.filter(share_content__in=contents).count() == 2
        )
        assert TheoreticalWashAmount.objects.filter(share_content=sc_wash).exists()
        assert TheoreticalCleanAmount.objects.filter(share_content=sc_clean).exists()
        assert MovementShareArticle.objects.filter(
            share_content__in=contents, movement_type="SHARECONTENT"
        ).exists()

        # Capture per-day distribution (so we can assert it actually moved)
        old_harvest_days = sorted(
            TheoreticalHarvest.objects.filter(share_content__in=contents).values_list(
                "day_number", flat=True
            )
        )
        old_wash_days = sorted(
            TheoreticalWashAmount.objects.filter(
                share_content__in=contents
            ).values_list("day_number", flat=True)
        )
        old_clean_days = sorted(
            TheoreticalCleanAmount.objects.filter(
                share_content__in=contents
            ).values_list("day_number", flat=True)
        )
        assert old_harvest_days == [1, 1]
        assert old_wash_days == [1]
        assert old_clean_days == [1]

        # ── Snapshot the invariants ──
        old_th_totals = _theoretical_total(contents)
        old_mv_totals = _movement_totals(contents)

        # End-of-time balance per (article, unit, size, storage) — one per line
        # (the two lines carry distinct articles). Using a far-future date so all
        # movements are included.
        from datetime import datetime as _dt

        from django.utils.timezone import make_aware as _make_aware

        far_future = _make_aware(_dt(FUTURE_YEAR + 5, 1, 1))

        def _balances():
            return {
                sc.share_article_id: SnapshotService.compute_balance(
                    share_article_id=sc.share_article_id,
                    unit=sc.unit,
                    size=sc.size,
                    storage_id=storage.id,
                    up_to=far_future,
                )
                for sc in contents
            }

        old_balances = _balances()

        # ── Apply day change: shift every relevant day ──
        with _patch_totals(_make_totals(contents, quantity=4)):
            result = SharesDayChangeService.apply(
                year=FUTURE_YEAR,
                delivery_week=FUTURE_WEEK,
                day_number=share.delivery_day.day_number,
                data={
                    "harvesting_day": 3,  # Thursday
                    "washing_day": 4,  # Friday
                    "cleaning_day": 4,  # Friday
                    "packing_day": 4,  # Friday (was 5)
                },
            )
        assert set(result["changed_fields"]) == {
            "harvesting_day",
            "washing_day",
            "cleaning_day",
            "packing_day",
        }
        assert sc_wash.id in result["recomputed_share_content_ids"]
        assert sc_clean.id in result["recomputed_share_content_ids"]

        # ── Days actually moved ──
        new_harvest_days = sorted(
            TheoreticalHarvest.objects.filter(share_content__in=contents).values_list(
                "day_number", flat=True
            )
        )
        new_wash_days = sorted(
            TheoreticalWashAmount.objects.filter(
                share_content__in=contents
            ).values_list("day_number", flat=True)
        )
        new_clean_days = sorted(
            TheoreticalCleanAmount.objects.filter(
                share_content__in=contents
            ).values_list("day_number", flat=True)
        )
        assert new_harvest_days == [3, 3]
        assert new_wash_days == [4]
        assert new_clean_days == [4]

        # ── Total amounts unchanged (the invariant) ──
        new_th_totals = _theoretical_total(contents)
        new_mv_totals = _movement_totals(contents)
        assert new_th_totals == old_th_totals, (
            "Theoretical amounts must be conserved across a day change "
            f"(old={old_th_totals}, new={new_th_totals})"
        )
        assert new_mv_totals == old_mv_totals, (
            "Movement amounts must be conserved across a day change "
            f"(old={old_mv_totals}, new={new_mv_totals})"
        )

        # ── End-of-time balance unchanged (per line/article) ──
        new_balances = _balances()
        assert new_balances == old_balances, (
            "End-of-time stock balance must be invariant under day changes "
            f"(old={old_balances}, new={new_balances})"
        )

        # ── There are no orphaned movements pointing at deleted theoreticals ──
        # Every is_theoretical movement must point at an existing source.
        orphans = MovementShareArticle.objects.filter(
            is_theoretical=True,
            theoretical_harvest__isnull=True,
            theoretical_purchase__isnull=True,
            theoretical_wash_amount__isnull=True,
            theoretical_clean_amount__isnull=True,
            additional_theoretical_harvest__isnull=True,
            additional_theoretical_purchase__isnull=True,
            additional_theoretical_wash_amount__isnull=True,
            additional_theoretical_clean_amount__isnull=True,
        )
        assert (
            not orphans.exists()
        ), "Found theoretical movements with no source FK after recompute"

    def test_multiple_share_contents_same_article_balance_invariant(self, tenant):
        """Two ShareContents on the same article on the same week — the
        per-article balance must stay the same after a day shake-up."""
        from apps.commissioning.services.share_content_service import (
            ShareContentService,
        )
        from apps.commissioning.services.snapshot_service import SnapshotService

        # Reuse the same article + storage across two Shares
        storage = StorageFactory(is_short_term_harvest_storage=True)
        article = ShareArticleFactory()
        sdd_a = SharesDeliveryDayFactory(day_number=2)  # Wed
        sdd_b = SharesDeliveryDayFactory(day_number=4)  # Fri
        stv_a = ShareTypeVariationFactory()
        stv_b = ShareTypeVariationFactory()

        share_a = ShareFactory(
            year=FUTURE_YEAR,
            delivery_week=FUTURE_WEEK,
            delivery_day=sdd_a,
            share_type_variation=stv_a,
            harvesting_day=1,
            washing_day=1,
            cleaning_day=1,
            packing_day=2,
        )
        share_b = ShareFactory(
            year=FUTURE_YEAR,
            delivery_week=FUTURE_WEEK,
            delivery_day=sdd_b,
            share_type_variation=stv_b,
            harvesting_day=1,
            washing_day=1,
            cleaning_day=1,
            packing_day=4,
        )
        station_a = DeliveryStationFactory()
        station_b = DeliveryStationFactory()
        DeliveryStationDayFactory(delivery_station=station_a, delivery_day=sdd_a)
        DeliveryStationDayFactory(delivery_station=station_b, delivery_day=sdd_b)
        forecast = ForecastFactory(
            share_article=article,
            year=FUTURE_YEAR,
            delivery_week=FUTURE_WEEK,
            size="M",
            storage=storage,
        )

        sc_a = ShareContentFactory(
            share=share_a,
            share_article=article,
            delivery_station=station_a,
            amount=Decimal("3"),
            unit="KG",
            size="M",
            forecast=forecast,
            washing=True,
            cleaning=False,
        )
        sc_b = ShareContentFactory(
            share=share_b,
            share_article=article,
            delivery_station=station_b,
            amount=Decimal("2"),
            unit="KG",
            size="M",
            forecast=forecast,
            washing=False,
            cleaning=True,
        )

        sc_a = ShareContent.objects.select_related(
            "share__share_type_variation",
            "share__delivery_day",
            "share_article",
            "forecast",
        ).get(pk=sc_a.pk)
        sc_b = ShareContent.objects.select_related(
            "share__share_type_variation",
            "share__delivery_day",
            "share_article",
            "forecast",
        ).get(pk=sc_b.pk)

        svc = ShareContentService()
        with patch(
            TOTALS_PATCH_PATH, return_value=_make_totals([sc_a, sc_b], quantity=2)
        ):
            svc.create_all_theoretical_objects([sc_a, sc_b])
            svc.create_movements([sc_a, sc_b])

        from datetime import datetime as _dt

        from django.utils.timezone import make_aware as _make_aware

        far_future = _make_aware(_dt(FUTURE_YEAR + 5, 1, 1))
        old_balance = SnapshotService.compute_balance(
            share_article_id=article.id,
            unit="KG",
            size="M",
            storage_id=storage.id,
            up_to=far_future,
        )
        old_th_totals = _theoretical_total([sc_a, sc_b])
        old_mv_totals = _movement_totals([sc_a, sc_b])

        # Change days only on share_a
        with patch(
            TOTALS_PATCH_PATH, return_value=_make_totals([sc_a, sc_b], quantity=2)
        ):
            SharesDayChangeService.apply(
                year=FUTURE_YEAR,
                delivery_week=FUTURE_WEEK,
                day_number=sdd_a.day_number,
                data={"harvesting_day": 0, "washing_day": 0},
            )

        new_balance = SnapshotService.compute_balance(
            share_article_id=article.id,
            unit="KG",
            size="M",
            storage_id=storage.id,
            up_to=far_future,
        )
        new_th_totals = _theoretical_total([sc_a, sc_b])
        new_mv_totals = _movement_totals([sc_a, sc_b])

        assert (
            new_balance == old_balance
        ), f"per-article balance changed: {old_balance} → {new_balance}"
        assert new_th_totals == old_th_totals
        assert new_mv_totals == old_mv_totals

        # share_b's theoreticals are untouched (still on day=1 etc.)
        sc_b_harvest_days = sorted(
            TheoreticalHarvest.objects.filter(share_content=sc_b).values_list(
                "day_number", flat=True
            )
        )
        assert sc_b_harvest_days == [1], "share_b should not have been recomputed"

        # share_a's theoreticals moved
        sc_a_harvest_days = sorted(
            TheoreticalHarvest.objects.filter(share_content=sc_a).values_list(
                "day_number", flat=True
            )
        )
        assert sc_a_harvest_days == [0]


# ═══════════════════════════════════════════════════════
# changed_day_number → re-plan billing (MEM-3)
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestChangedDayNumberNotifiesPayments:
    """MEM-3: ``changed_day_number`` is the top-priority input to the delivery
    date the billing regen buckets deliveries by, so editing it must notify
    payments to re-plan — even though it's NOT a recompute-relevant (theoretical)
    field. The informational ``get_current_stock_day`` must NOT trigger a re-plan.
    """

    NOTIFY_PATH = "apps.shared.subscription_hooks.notify_subscription_changed"

    def _share_with_subscribed_delivery(self):
        # day_number 5 so it never collides with the SubscriptionFactory's own
        # default_delivery_station_day (a SharesDeliveryDay at day_number 2,
        # which is a GLOBAL overlap scope).
        sub = SubscriptionFactory()
        sdd = SharesDeliveryDayFactory(day_number=5)
        share = ShareFactory(
            year=FUTURE_YEAR,
            delivery_week=FUTURE_WEEK,
            delivery_day=sdd,
            share_type_variation=sub.share_type_variation,
        )
        station_day = DeliveryStationDayFactory(delivery_day=sdd)
        ShareDeliveryFactory(
            share=share, subscription=sub, delivery_station_day=station_day
        )
        return share, sub

    def test_changed_day_number_notifies_subscription(self, tenant):
        share, sub = self._share_with_subscribed_delivery()

        with patch(self.NOTIFY_PATH) as notify_mock:
            result = SharesDayChangeService.apply(
                year=FUTURE_YEAR,
                delivery_week=FUTURE_WEEK,
                day_number=share.delivery_day.day_number,
                data={"changed_day_number": 3},
            )

        assert result["changed_fields"] == ["changed_day_number"]
        notify_mock.assert_called_once()
        assert notify_mock.call_args.args[0].pk == sub.pk

    def test_informational_day_field_does_not_notify(self, tenant):
        # get_current_stock_day is neither recompute-relevant nor billing-relevant
        # — editing it alone must not spuriously re-plan billing (no machinery).
        share, _sub = self._share_with_subscribed_delivery()

        with patch(self.NOTIFY_PATH) as notify_mock:
            SharesDayChangeService.apply(
                year=FUTURE_YEAR,
                delivery_week=FUTURE_WEEK,
                day_number=share.delivery_day.day_number,
                data={"get_current_stock_day": 4},
            )

        notify_mock.assert_not_called()

    def test_subscription_set_dedups_by_pk(self, tenant):
        # MEM-3 dedups subscriptions via a Python set: {sd.subscription for ...}.
        # select_related yields a DISTINCT Subscription instance per row, so the
        # set only collapses duplicates if Django's Model __hash__/__eq__ are
        # pk-based — they are (hash(self.pk) + pk equality). Re-fetching one row
        # twice reproduces exactly that distinct-identity / same-pk shape, so the
        # set must collapse to one. (Belt-and-braces: the
        # share_unique_year_week_day_variation constraint + one-variation-per-
        # subscription already make >1 matching delivery per subscription, per
        # (week, day), impossible — so a subscription is never notified twice.)
        from apps.commissioning.models import Subscription

        sub = SubscriptionFactory()
        again = Subscription.objects.get(pk=sub.pk)
        assert again is not sub  # distinct identities, like two select_related rows
        assert len({sub, again}) == 1  # …but one logical subscription
