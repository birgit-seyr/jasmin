"""Tests for compute_rolled_back_week, TheoreticalSourceData, and create_theoretical_objects."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from apps.commissioning.services.theoretical_objects import (
    TheoreticalSourceData,
    create_theoretical_objects,
)
from apps.commissioning.tests.factories import (
    ForecastFactory,
    ShareArticleFactory,
    ShareContentFactory,
    StorageFactory,
)
from apps.commissioning.utils.iso_week_utils import compute_rolled_back_week


# ---------------------------------------------------------------------------
# _AMOUNT_PER_PU_MAP  (pure — no DB)
# ---------------------------------------------------------------------------
class TestAmountPerPuMap:
    """Regression for the BUNCH unit-key mismatch: the map must key on the
    canonical ``UnitOptions`` values. A non-canonical key (e.g. "BUNCHES") makes
    ``_AMOUNT_PER_PU_MAP.get(src.unit)`` miss, so ``amount_per_pu`` resolves to
    None and BUNCH harvests silently contribute 0 crates to the harvesting-crate
    summary."""

    def test_keys_are_canonical_unit_options(self):
        from apps.commissioning.models.choices_text import UnitOptions
        from apps.commissioning.services.theoretical_objects import (
            _AMOUNT_PER_PU_MAP,
        )

        non_canonical = set(_AMOUNT_PER_PU_MAP) - set(UnitOptions.values)
        assert not non_canonical, (
            f"_AMOUNT_PER_PU_MAP keys must be UnitOptions values; got "
            f"non-canonical: {non_canonical}"
        )

    def test_bunch_resolves_to_its_per_pu_attr(self):
        from apps.commissioning.models.choices_text import UnitOptions
        from apps.commissioning.services.theoretical_objects import (
            _AMOUNT_PER_PU_MAP,
        )

        assert (
            _AMOUNT_PER_PU_MAP.get(UnitOptions.BUNCH)
            == "default_bunches_per_pu_harvest"
        )


# ---------------------------------------------------------------------------
# compute_rolled_back_week  (pure — no DB)
# ---------------------------------------------------------------------------
class TestComputeRolledBackWeek:
    def test_activity_before_delivery_same_week(self):
        # activity_day=1 (Tue), delivery_day=3 (Thu) → same week
        y, w = compute_rolled_back_week(2026, 15, activity_day=1, delivery_day=3)
        assert (y, w) == (2026, 15)

    def test_activity_after_delivery_rolls_back(self):
        # activity_day=5 (Sat), delivery_day=2 (Wed) → previous week
        y, w = compute_rolled_back_week(2026, 15, activity_day=5, delivery_day=2)
        assert (y, w) == (2026, 14)

    def test_year_boundary_rollback(self):
        # Week 1 of 2026, activity rolls back → last week of 2025
        y, w = compute_rolled_back_week(2026, 1, activity_day=5, delivery_day=2)
        assert y == 2025
        assert w >= 52

    def test_same_day_stays_in_week(self):
        y, w = compute_rolled_back_week(2026, 15, activity_day=3, delivery_day=3)
        assert (y, w) == (2026, 15)


# ---------------------------------------------------------------------------
# TheoreticalSourceData properties  (pure — no DB)
# ---------------------------------------------------------------------------
class TestTheoreticalSourceDataProperties:
    def _make_src(self, **overrides):
        defaults = dict(
            year=2026,
            delivery_week=15,
            delivery_day=2,
            harvesting_day=1,
            washing_day=1,
            cleaning_day=1,
            share_article=MagicMock(),
            amount=Decimal("10.000"),
            unit="KG",
            size="M",
            note=None,
            washing=False,
            cleaning=False,
            forecast=None,
            is_purchased=False,
            share_content=MagicMock(),
            order_content=None,
        )
        defaults.update(overrides)
        return TheoreticalSourceData(**defaults)

    def test_needs_harvest_with_forecast(self):
        src = self._make_src(forecast=MagicMock())
        assert src.needs_harvest is True

    def test_needs_harvest_without_forecast(self):
        src = self._make_src(forecast=None)
        assert src.needs_harvest is False

    def test_needs_purchase_when_purchased(self):
        src = self._make_src(is_purchased=True)
        assert src.needs_purchase is True

    def test_needs_purchase_when_not_purchased(self):
        src = self._make_src(is_purchased=False)
        assert src.needs_purchase is False

    def test_needs_wash_and_clean(self):
        src = self._make_src(washing=True, cleaning=True)
        assert src.needs_wash is True
        assert src.needs_clean is True

    def test_has_positive_amount(self):
        assert self._make_src(amount=Decimal("5")).has_positive_amount is True
        assert self._make_src(amount=Decimal("0")).has_positive_amount is False
        assert self._make_src(amount=None).has_positive_amount is False

    def test_content_kwargs_share_content(self):
        sc = MagicMock()
        src = self._make_src(share_content=sc, order_content=None)
        assert src.content_kwargs == {"share_content": sc}

    def test_content_kwargs_order_content(self):
        oc = MagicMock()
        src = self._make_src(share_content=None, order_content=oc)
        assert src.content_kwargs == {"order_content": oc}


# ---------------------------------------------------------------------------
# create_theoretical_objects  (DB)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateTheoreticalObjects:
    def test_creates_theoretical_harvest_and_placeholder(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        forecast = ForecastFactory(share_article=article)
        sc = ShareContentFactory(share_article=article)

        src = TheoreticalSourceData(
            year=2026,
            delivery_week=15,
            delivery_day=2,
            harvesting_day=1,
            washing_day=None,
            cleaning_day=None,
            share_article=article,
            amount=Decimal("10.000"),
            unit="KG",
            size="M",
            note=None,
            washing=False,
            cleaning=False,
            forecast=forecast,
            is_purchased=False,
            share_content=sc,
            storage=storage,
        )

        result = create_theoretical_objects([src])
        assert "harvests" in result
        assert len(result["harvests"]) == 1
        th = result["harvests"][0]
        assert th.share_article == article
        assert th.amount == Decimal("10.000")

        # Placeholder Harvest should also exist
        from apps.commissioning.models import Harvest

        assert Harvest.objects.filter(share_article=article, year=2026).exists()

    def test_creates_theoretical_purchase_and_placeholder(self, tenant):
        article = ShareArticleFactory(is_purchased=True)
        storage = StorageFactory(is_short_term_harvest_storage=True)
        sc = ShareContentFactory(share_article=article)

        src = TheoreticalSourceData(
            year=2026,
            delivery_week=15,
            delivery_day=2,
            harvesting_day=None,
            washing_day=None,
            cleaning_day=None,
            share_article=article,
            amount=Decimal("20.000"),
            unit="KG",
            size="M",
            note=None,
            washing=False,
            cleaning=False,
            forecast=None,
            is_purchased=True,
            share_content=sc,
            storage=storage,
        )

        result = create_theoretical_objects([src])
        assert "purchases" in result
        assert len(result["purchases"]) == 1

        from apps.commissioning.models import Purchase

        assert Purchase.objects.filter(share_article=article, year=2026).exists()

    def test_skips_zero_amount_sources(self, tenant):
        article = ShareArticleFactory()
        sc = ShareContentFactory(share_article=article)

        src = TheoreticalSourceData(
            year=2026,
            delivery_week=15,
            delivery_day=2,
            harvesting_day=1,
            washing_day=None,
            cleaning_day=None,
            share_article=article,
            amount=Decimal("0"),
            unit="KG",
            size="M",
            note=None,
            washing=False,
            cleaning=False,
            forecast=MagicMock(),
            is_purchased=False,
            share_content=sc,
        )

        result = create_theoretical_objects([src])
        assert result == {}

    def test_no_placeholders_when_disabled(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        forecast = ForecastFactory(share_article=article)
        sc = ShareContentFactory(share_article=article)

        src = TheoreticalSourceData(
            year=2026,
            delivery_week=15,
            delivery_day=2,
            harvesting_day=1,
            washing_day=None,
            cleaning_day=None,
            share_article=article,
            amount=Decimal("10.000"),
            unit="KG",
            size="M",
            note=None,
            washing=False,
            cleaning=False,
            forecast=forecast,
            is_purchased=False,
            share_content=sc,
            storage=storage,
        )

        result = create_theoretical_objects([src], create_placeholders=False)
        assert "harvests" in result

        from apps.commissioning.models import Harvest

        assert not Harvest.objects.filter(share_article=article, year=2026).exists()

    def test_wash_clean_land_in_short_term_storage_for_long_term_line(self, tenant):
        # MOV-6: a long-term line's wash/clean theoreticals carry
        # RequiresShortTermStorageMixin, so they must land in the SHORT-term
        # harvest storage — not the long-term storage the line draws from.
        article = ShareArticleFactory()
        short_term = StorageFactory(is_short_term_harvest_storage=True)
        long_term = StorageFactory(is_short_term_harvest_storage=False)
        sc = ShareContentFactory(share_article=article)

        src = TheoreticalSourceData(
            year=2026,
            delivery_week=15,
            delivery_day=2,
            harvesting_day=1,
            washing_day=1,
            cleaning_day=1,
            share_article=article,
            amount=Decimal("10.000"),
            unit="KG",
            size="M",
            note=None,
            washing=True,
            cleaning=True,
            forecast=None,
            is_purchased=False,
            share_content=sc,
            storage=long_term,  # the long-term storage the line draws from
            comes_from_long_term_storage=True,
            total_amount_for_shares=Decimal("10.000"),
        )

        result = create_theoretical_objects([src], create_placeholders=False)

        assert result["washes"][0].storage_id == short_term.id
        assert result["washes"][0].storage.is_short_term_harvest_storage
        assert result["cleans"][0].storage_id == short_term.id
        assert result["cleans"][0].storage.is_short_term_harvest_storage
