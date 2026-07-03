"""Tests for movements — calculate_current_stock_for_allocation & create_movements."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.commissioning.services.movements import (
    MovementSourceData,
    calculate_current_stock_for_allocation,
    create_movements,
)
from apps.commissioning.tests.factories import (
    ShareArticleFactory,
    ShareContentFactory,
    StorageFactory,
)


# ---------------------------------------------------------------------------
# MovementSourceData
# ---------------------------------------------------------------------------
class TestMovementSourceData:
    def test_source_kwargs_share_content(self):
        sentinel = object()
        src = MovementSourceData(
            year=2026,
            delivery_week=15,
            delivery_day=2,
            packing_day=1,
            share_article=None,
            unit="KG",
            size="M",
            amount=Decimal("10"),
            movement_type="SHARE",
            share_content=sentinel,
        )
        assert src.source_kwargs == {"share_content": sentinel}

    def test_source_kwargs_order_content(self):
        sentinel = object()
        src = MovementSourceData(
            year=2026,
            delivery_week=15,
            delivery_day=2,
            packing_day=1,
            share_article=None,
            unit="KG",
            size="M",
            amount=Decimal("10"),
            movement_type="ORDER",
            order_content=sentinel,
        )
        assert src.source_kwargs == {"order_content": sentinel}


# ---------------------------------------------------------------------------
# calculate_current_stock_for_allocation
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCalculateCurrentStockForAllocation:
    def test_returns_sorted_stocks(self, tenant):
        article = ShareArticleFactory()
        s1 = StorageFactory(is_short_term_harvest_storage=True)
        s2 = StorageFactory()

        # Simulate StockService returning two storages with stock
        mock_stock_map = {
            (str(article.pk), "KG", "M", str(s1.pk)): {
                "current_stock_amount": Decimal("20"),
                "theoretical_current_stock": Decimal("20"),
                "is_finalized": False,
            },
            (str(article.pk), "KG", "M", str(s2.pk)): {
                "current_stock_amount": Decimal("5"),
                "theoretical_current_stock": Decimal("5"),
                "is_finalized": False,
            },
        }

        with patch(
            "apps.commissioning.services.stock_service.StockService.get_theoretical_current_stock",
            return_value=mock_stock_map,
        ):
            stocks = calculate_current_stock_for_allocation(
                article,
                "KG",
                "M",
                2026,
                15,
                1,
            )

        # Smallest first
        assert len(stocks) == 2
        assert stocks[0]["amount"] == Decimal("5")
        assert stocks[1]["amount"] == Decimal("20")

    def test_excludes_zero_stock(self, tenant):
        article = ShareArticleFactory()
        s1 = StorageFactory()

        mock_stock_map = {
            (str(article.pk), "KG", "M", str(s1.pk)): {
                "current_stock_amount": Decimal("0"),
                "theoretical_current_stock": Decimal("0"),
                "is_finalized": False,
            },
        }

        with patch(
            "apps.commissioning.services.stock_service.StockService.get_theoretical_current_stock",
            return_value=mock_stock_map,
        ):
            stocks = calculate_current_stock_for_allocation(
                article,
                "KG",
                "M",
                2026,
                15,
                1,
            )

        assert stocks == []


# ---------------------------------------------------------------------------
# create_movements
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateMovements:
    def _make_source(self, article, share_content, **overrides):
        defaults = dict(
            year=2026,
            delivery_week=15,
            delivery_day=2,
            packing_day=1,
            share_article=article,
            unit="KG",
            size="M",
            amount=Decimal("10"),
            movement_type="SHARE",
            share_content=share_content,
        )
        defaults.update(overrides)
        return MovementSourceData(**defaults)

    def test_negative_movement_when_no_stock(self, tenant):
        short = StorageFactory(is_short_term_harvest_storage=True)
        article = ShareArticleFactory()
        sc = ShareContentFactory(share_article=article)

        with patch(
            "apps.commissioning.services.movements.calculate_current_stock_for_allocation",
            return_value=[],
        ), patch(
            "apps.commissioning.services.snapshot_service.SnapshotService.cascade_for_movements",
        ):
            movements = create_movements([self._make_source(article, sc)])

        assert len(movements) == 1
        assert movements[0].amount == Decimal("-10")
        assert movements[0].storage == short

    def test_allocates_across_storages(self, tenant):
        s1 = StorageFactory(is_short_term_harvest_storage=True)
        s2 = StorageFactory()
        article = ShareArticleFactory()
        sc = ShareContentFactory(share_article=article)

        stocks = [
            {"storage_id": s1.pk, "amount": Decimal("3"), "is_finalized": False},
            {"storage_id": s2.pk, "amount": Decimal("20"), "is_finalized": False},
        ]

        with patch(
            "apps.commissioning.services.movements.calculate_current_stock_for_allocation",
            return_value=stocks,
        ), patch(
            "apps.commissioning.services.snapshot_service.SnapshotService.cascade_for_movements",
        ):
            movements = create_movements(
                [self._make_source(article, sc, amount=Decimal("8"))]
            )

        assert len(movements) == 2
        amounts = sorted(m.amount for m in movements)
        assert amounts == [Decimal("-5"), Decimal("-3")]

    def test_records_remainder_when_stock_under_covers_demand(self, tenant):
        """When available stock (3) is LESS than demand (10), the loop deducts
        what's there and the uncovered remainder (7) is recorded against
        short-term storage — total recorded outflow == the full demand (-10).
        Before the fix the uncovered amount was silently dropped, leaving
        theoretical_current_stock too high (COR-16)."""
        short = StorageFactory(is_short_term_harvest_storage=True)
        s2 = StorageFactory()
        article = ShareArticleFactory()
        sc = ShareContentFactory(share_article=article)

        stocks = [
            {"storage_id": s2.pk, "amount": Decimal("3"), "is_finalized": False},
        ]

        with patch(
            "apps.commissioning.services.movements.calculate_current_stock_for_allocation",
            return_value=stocks,
        ), patch(
            "apps.commissioning.services.snapshot_service.SnapshotService.cascade_for_movements",
        ):
            movements = create_movements(
                [self._make_source(article, sc, amount=Decimal("10"))]
            )

        assert len(movements) == 2
        # Total outflow equals the full demand, not just the covered 3.
        assert sum(m.amount for m in movements) == Decimal("-10")
        # The uncovered 7 lands on short-term storage.
        remainder = [m for m in movements if m.storage == short]
        assert len(remainder) == 1
        assert remainder[0].amount == Decimal("-7")

    def test_returns_empty_for_no_sources(self, tenant):
        result = create_movements([])
        assert result == []


# ---------------------------------------------------------------------------
# REF-3/4: ShareContent movement-capture helper — single source of truth for the
# "both movement halves" filter once copy-pasted across 5 delete/replace paths.
# ---------------------------------------------------------------------------
def _q_lookup_paths(node) -> set[str]:
    """Flatten a Q tree to the set of lookup paths (left-hand sides) it uses."""
    paths: set[str] = set()
    for child in node.children:
        if hasattr(child, "children"):
            paths |= _q_lookup_paths(child)
        else:
            paths.add(child[0])
    return paths


class TestShareContentMovementCapture:
    def test_theoretical_fk_tuple_matches_source_map(self):
        """Drift guard: the capture tuple must cover exactly the ShareContent-
        reachable ``theoretical_*`` source FKs — NOT the ``additional_theoretical_*``
        ones (no ``share_content`` FK). Adding a new theoretical type to
        ``_SOURCE_TO_TYPE`` fails this until the capture tuple is updated too."""
        from apps.commissioning.models.movements import (
            _SHARE_CONTENT_THEORETICAL_FKS,
            _SOURCE_TO_TYPE,
        )

        expected = {
            key
            for key in _SOURCE_TO_TYPE
            if key.startswith("theoretical_")
            and not key.startswith("additional_theoretical_")
        }
        assert set(_SHARE_CONTENT_THEORETICAL_FKS) == expected

    def test_queryset_branch_covers_share_content_and_all_theoretical_halves(self):
        from apps.commissioning.models.movements import (
            _SHARE_CONTENT_THEORETICAL_FKS,
            share_content_movement_q,
        )

        paths = _q_lookup_paths(share_content_movement_q(["sc-1", "sc-2"]))
        assert "share_content__in" in paths
        for fk in _SHARE_CONTENT_THEORETICAL_FKS:
            assert f"{fk}__share_content__in" in paths

    def test_instance_branch_uses_exact_lookup(self):
        from apps.commissioning.models import ShareContent
        from apps.commissioning.models.movements import share_content_movement_q

        # Unsaved instance — no DB needed; only the isinstance(Model) branch.
        paths = _q_lookup_paths(share_content_movement_q(ShareContent()))
        assert "share_content" in paths
        assert "share_content__in" not in paths
        assert "theoretical_harvest__share_content" in paths
