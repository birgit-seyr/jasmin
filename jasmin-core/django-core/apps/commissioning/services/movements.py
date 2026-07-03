"""
Shared service for creating MovementShareArticle records from
ShareContent and OrderContent sources.

Both sources follow the same algorithm:
1. Determine the packing datetime (packing_day at 12:00, with ISO-week rollback).
2. Query available stock per storage (smallest-first via StockService).
3. Allocate the required amount across storages.
4. Bulk-create the movements and cascade snapshots.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from django.db import transaction

from ..models import (
    MovementShareArticle,
    ShareArticle,
    Storage,
)
from ..utils.iso_week_utils import compute_rolled_back_week, make_noon_datetime
from .snapshot_service import SnapshotService

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────
# Normalised descriptor for a movement source
# ──────────────────────────────────────────────────────


class MovementSourceData:
    """Unified view of a ShareContent or OrderContent for movement creation."""

    def __init__(
        self,
        *,
        year: int,
        delivery_week: int,
        delivery_day: int,
        packing_day: int,
        share_article: ShareArticle,
        unit: str | None,
        size: str | None,
        amount: Decimal,
        movement_type: str,
        # Exactly one of these must be set:
        share_content=None,
        order_content=None,
    ):
        self.year = year
        self.delivery_week = delivery_week
        self.delivery_day = delivery_day
        self.packing_day = packing_day
        self.share_article = share_article
        self.unit = unit
        self.size = size
        self.amount = Decimal(str(amount))
        self.movement_type = movement_type
        self.share_content = share_content
        self.order_content = order_content

    @property
    def source_kwargs(self) -> dict[str, Any]:
        """FK kwarg for the movement's source."""
        if self.share_content is not None:
            return {"share_content": self.share_content}
        return {"order_content": self.order_content}


# ──────────────────────────────────────────────────────
# Stock allocation helper
# ──────────────────────────────────────────────────────


def calculate_current_stock_for_allocation(
    share_article: ShareArticle,
    unit: str,
    size: str,
    year: int,
    delivery_week: int,
    day_number: int,
    stock_map: dict | None = None,
) -> list[dict[str, Any]]:
    """Return available stock per storage location, sorted smallest-first.

    ``stock_map``: pass a precomputed
    ``StockService.get_theoretical_current_stock(year, week, day)``
    result when calling this in a loop — for a given snapshot the map
    covers every (unit, size, storage) of whichever articles it was
    fetched for (batch callers scope it to the batch's source articles
    via ``entity_filter``), so they must not rebuild it per article.
    This function only reads entries whose ``share_article_id`` matches
    ``share_article``.
    """
    from .stock_service import StockService

    if stock_map is None:
        stock_map = StockService.get_theoretical_current_stock(
            year, delivery_week, day_number, storage=None
        )

    available_stocks: list[dict[str, Any]] = []
    for (sa_id, s_unit, s_size, storage_id), stock_data in stock_map.items():
        if sa_id == share_article.id and s_unit == unit and s_size == size:
            current_amount = stock_data.get("current_stock_amount")
            if current_amount is None:
                current_amount = stock_data.get("theoretical_current_stock", 0)
            if current_amount and current_amount > 0:
                available_stocks.append(
                    {
                        "storage_id": storage_id,
                        "amount": current_amount,
                        "is_finalized": stock_data.get("is_finalized", False),
                    }
                )

    available_stocks.sort(key=lambda x: x["amount"])
    return available_stocks


# ──────────────────────────────────────────────────────
# Packing datetime helper
# ──────────────────────────────────────────────────────


def _compute_packing_datetime(
    year: int,
    delivery_week: int,
    packing_day: int,
    delivery_day: int,
):
    """Return an aware datetime at noon on the packing day_number (ISO-week safe)."""
    rolled_year, rolled_week = compute_rolled_back_week(
        year, delivery_week, packing_day, delivery_day
    )
    return make_noon_datetime(rolled_year, rolled_week, packing_day)


# ──────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────


@transaction.atomic
def create_movements(
    sources: list[MovementSourceData],
    *,
    collect_movements: list[MovementShareArticle] | None = None,
) -> list[MovementShareArticle]:
    """Create movements for a batch of source items with stock allocation.

    Algorithm per source:
    1. Compute packing datetime (packing_day at 12:00 with week rollback).
    2. Query available stock (smallest-first).
    3. If no stock → single negative movement against short-term storage.
    4. If stock exists → allocate across storages until the full amount is covered.
    5. Bulk-create all movements and cascade snapshots.

    ``collect_movements``: when given, step 5's snapshot cascade is deferred —
    the created movements are appended to the list and the caller runs one
    union ``cascade_for_movements`` at the end of its transaction (a single
    sorted ``current_balance:*`` advisory-lock pass instead of one pass per
    creation step; see ``ShareContentService.recompute_for_shares``).
    """
    short_term_storage = Storage.short_term_harvest()

    # ── Lock affected share articles to serialize concurrent allocations ──
    # ``order_by("id")`` (over sorted ids) so two concurrent recomputes acquire
    # the row locks in the SAME order — without it the lock order is
    # plan-dependent, the classic AB/BA deadlock the sibling services
    # (share_content_service / order_content_service) already guard against.
    article_ids = sorted({src.share_article.id for src in sources})
    if article_ids:
        list(
            ShareArticle.objects.filter(id__in=article_ids)
            .select_for_update()
            .order_by("id")
        )

    # ── Pre-compute stock & collect storage IDs ──
    # ``get_theoretical_current_stock`` is scoped to the ARTICLES these sources
    # actually need (``entity_filter``), not the whole ledger: the snapshot only
    # has to carry the source articles' stock, and a source's allocation only
    # reads its own (article, unit, size). Without the scope an unfiltered
    # ``date__lte`` query materialises every article × unit × size × storage
    # movement (and the full balance table) per snapshot — a near full-ledger
    # scan once per week on a season-wide recompute, run synchronously while the
    # Share/ShareArticle row locks are held. We still compute each snapshot once
    # (all sources read the same pre-bulk_create DB state).
    from .stock_service import StockService

    stock_map_by_snapshot: dict[tuple[int, int, int], dict] = {}
    stock_cache: dict[int, list[dict[str, Any]]] = {}
    all_storage_ids: set[Any] = set()
    snapshot_entity_filter = {"share_article_id": article_ids} if article_ids else None

    for src in sources:
        snapshot_key = (src.year, src.delivery_week, src.packing_day)
        stock_map = stock_map_by_snapshot.get(snapshot_key)
        if stock_map is None:
            stock_map = StockService.get_theoretical_current_stock(
                src.year,
                src.delivery_week,
                src.packing_day,
                storage=None,
                entity_filter=snapshot_entity_filter,
            )
            stock_map_by_snapshot[snapshot_key] = stock_map
        stocks = calculate_current_stock_for_allocation(
            share_article=src.share_article,
            unit=src.unit,
            size=src.size,
            year=src.year,
            delivery_week=src.delivery_week,
            day_number=src.packing_day,
            stock_map=stock_map,
        )
        stock_cache[id(src)] = stocks
        for s in stocks:
            if s["storage_id"]:
                all_storage_ids.add(s["storage_id"])

    storage_by_id: dict[Any, Storage] = (
        {s.id: s for s in Storage.objects.filter(id__in=all_storage_ids)}
        if all_storage_ids
        else {}
    )

    # ── Build movements ──
    movements_to_create: list[MovementShareArticle] = []

    for src in sources:
        packing_dt = _compute_packing_datetime(
            src.year,
            src.delivery_week,
            src.packing_day,
            src.delivery_day,
        )

        available_stocks = stock_cache[id(src)]
        total_amount = abs(src.amount)

        base_kwargs = {
            "date": packing_dt,
            "movement_type": src.movement_type,
            "share_article": src.share_article,
            "unit": src.unit,
            "size": src.size,
            **src.source_kwargs,
        }

        if not available_stocks:
            if short_term_storage is not None:
                movements_to_create.append(
                    MovementShareArticle(
                        **base_kwargs,
                        amount=-total_amount,
                        storage=short_term_storage,
                    )
                )
            continue

        remaining = total_amount
        for stock in available_stocks:
            if remaining <= 0:
                break

            stock_amount = Decimal(str(stock["amount"]))
            take = min(remaining, stock_amount)
            storage_obj = (
                storage_by_id.get(stock["storage_id"]) if stock["storage_id"] else None
            )

            movements_to_create.append(
                MovementShareArticle(
                    **base_kwargs,
                    amount=-take,
                    storage=storage_obj,
                )
            )
            remaining -= take

        # Stock ran out before covering the full demand. Record the uncovered
        # remainder against short-term storage so the ledger's total outflow
        # equals the requested amount — otherwise ``theoretical_current_stock``
        # stays too high by ``remaining`` and corrupts downstream balance /
        # offer / forecast calculations. Mirrors the no-stock branch above.
        if remaining > 0 and short_term_storage is not None:
            movements_to_create.append(
                MovementShareArticle(
                    **base_kwargs,
                    amount=-remaining,
                    storage=short_term_storage,
                )
            )

    # ── Persist & cascade ──
    if movements_to_create:
        created = list(MovementShareArticle.objects.bulk_create(movements_to_create))
        if collect_movements is not None:
            collect_movements.extend(created)
        else:
            SnapshotService.cascade_for_movements(created)
        return created
    return []
