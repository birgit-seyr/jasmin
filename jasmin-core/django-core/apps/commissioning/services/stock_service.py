from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone
from django.utils.timezone import make_aware

from ..models import CurrentStockBalance, MovementShareArticle, StockSnapshot
from ..models.choices_text import MovementTypeOptions
from ..utils.iso_week_utils import week_day_to_date


def _build_base_filter(
    storage: str | None,
    entity_filter: dict[str, str] | None,
) -> Q:
    """Build a reusable Q filter from optional storage / entity constraints.

    An ``entity_filter`` value may be a scalar (exact match) OR a list/set/tuple
    (``__in`` match) — the latter lets a caller scope a stock query to several
    articles at once (e.g. a season-wide recompute scoping the snapshot to just
    the articles it is rebuilding instead of the whole ledger).
    """
    q = Q()
    if storage:
        q &= Q(storage=storage)
    if entity_filter:
        for field in ("share_article_id", "unit", "size"):
            if field in entity_filter:
                value = entity_filter[field]
                if isinstance(value, (list, set, tuple)):
                    q &= Q(**{f"{field}__in": list(value)})
                else:
                    q &= Q(**{field: value})
    return q


def _entity_key(
    share_article_id: str,
    unit: str | None,
    size: str | None,
    storage_id: str | None,
) -> tuple[str, str | None, str | None, str | None]:
    """Normalise an entity key (coerce falsy storage_id to None)."""
    return (str(share_article_id), unit, size, str(storage_id) if storage_id else None)


def _days_inventory_map(
    target_dt_start: datetime,
    target_dt_end: datetime,
    base_filter: Q,
) -> dict[tuple, dict]:
    """Aggregate the target day's INVENTORY movements per entity.

    Carries ``amount`` as Decimal internally so the running-balance math
    stays exact; callers convert to float only at the dict-build boundary
    where the result feeds into JSON responses.
    """
    inventory_qs = (
        MovementShareArticle.objects.filter(
            movement_type=MovementTypeOptions.INVENTORY,
            date__gte=target_dt_start,
            date__lte=target_dt_end,
        )
        .filter(base_filter)
        .select_related("share_article")
    )

    inventory_map: dict[tuple, dict] = {}
    for movement in inventory_qs.order_by("date"):
        key = _entity_key(
            movement.share_article_id,
            movement.unit,
            movement.size,
            movement.storage_id,
        )
        prior_amount = (inventory_map.get(key) or {}).get("amount") or Decimal("0")
        inventory_map[key] = {
            # Sum ALL of the day's INVENTORY corrections for this entity so
            # the theoretical baseline subtracts every same-day correction,
            # not just the last. Display fields keep the last row's.
            "amount": prior_amount + (movement.amount or Decimal("0")),
            "is_finalized": movement.is_finalized,
            "washed": movement.washed,
            "cleaned": movement.cleaned,
            "for_shares": movement.for_shares,
            "for_resellers": movement.for_resellers,
            "for_markets": movement.for_markets,
            "note": movement.note or "",
            "id": movement.id,
        }
    return inventory_map


def _build_result_row(
    running_balance: Decimal,
    inv_data: dict,
    has_inventory: bool,
) -> dict:
    """Assemble one result-dict entry from the entity's running balance and
    its (possibly empty) day-INVENTORY data."""
    inv_delta = inv_data.get("amount") or Decimal("0")  # Decimal

    # theoretical = balance without today's INVENTORY correction
    theoretical = running_balance - inv_delta  # Decimal
    # counted = balance including the correction (= absolute counted)
    counted = running_balance if has_inventory else None  # Decimal | None

    return {
        # Convert to float at the JSON boundary so the wire shape
        # stays unchanged (DRF's default Decimal-to-string would
        # break the frontend's number-typed parsing).
        "theoretical_current_stock": float(theoretical),
        "current_stock_amount": float(counted) if counted is not None else None,
        "is_finalized": inv_data.get("is_finalized") if has_inventory else None,
        "washed": inv_data.get("washed") if has_inventory else None,
        "cleaned": inv_data.get("cleaned") if has_inventory else None,
        "for_shares": inv_data.get("for_shares") if has_inventory else None,
        "for_resellers": inv_data.get("for_resellers") if has_inventory else None,
        "for_markets": inv_data.get("for_markets") if has_inventory else None,
        "note": inv_data.get("note", "") if has_inventory else "",
    }


class StockService:
    @staticmethod
    def get_theoretical_current_stock(
        year: int,
        delivery_week: int,
        day_number: int | str,
        storage: str | None = None,
        entity_filter: dict[str, str] | None = None,
    ) -> dict[tuple, dict]:
        """
        Calculate theoretical current stock and compare with inventory counts.

        Theoretical stock = sum of ALL movements (incl. INVENTORY) up to end of
        the target day_number.

        For target_date == today, reads from the maintained ``CurrentStockBalance``
        projection (O(N) lookup). For historical or future-dated queries, falls
        back to the snapshot+movements aggregation.

        Inventory count = the most recent INVENTORY movement for each entity
        on the target day_number (equivalent to the old CurrentStock).

        Returns a dict keyed by (share_article_id, unit, size, storage_id) with:
        - theoretical_current_stock: running balance from snapshots + movements
        - current_stock_amount: amount of today's INVENTORY movement (or None)
        - is_finalized, washed, cleaned, for_shares, for_resellers, for_markets
        """
        day_number = int(day_number)
        target_date = week_day_to_date(year, delivery_week, day_number)
        target_dt_start = make_aware(datetime.combine(target_date, time(0, 0, 0)))
        target_dt_end = make_aware(datetime.combine(target_date, time(23, 59, 59)))

        if target_date == timezone.now().date():
            return StockService._current_stock_from_projection(
                target_dt_start, target_dt_end, storage, entity_filter
            )

        base_filter = _build_base_filter(storage, entity_filter)

        # ── Step 1: today's INVENTORY movements (replaces stock-0) ─
        inventory_map = _days_inventory_map(target_dt_start, target_dt_end, base_filter)

        # ── Step 2: compute running balance per entity ─────────────
        # Use snapshots as baselines where available
        snap_filter = Q(snapshot_date__lte=target_dt_end)
        if storage:
            snap_filter &= Q(storage_id=storage)

        snapshot_baselines: dict[tuple, tuple[Decimal, datetime]] = {}
        for snap in StockSnapshot.objects.filter(snap_filter).order_by(
            "-snapshot_date"
        ):
            key = _entity_key(
                snap.share_article_id, snap.unit, snap.size, snap.storage_id
            )
            if key not in snapshot_baselines:
                snapshot_baselines[key] = (snap.balance, snap.snapshot_date)

        # Query movements, respecting per-entity snapshot cutoffs
        all_movements = list(
            MovementShareArticle.objects.filter(
                Q(date__lte=target_dt_end) & base_filter
            ).values_list(
                "share_article_id", "unit", "size", "storage_id", "date", "amount"
            )
        )

        # Collect all entity keys
        all_entity_keys: set[tuple] = set(inventory_map) | set(snapshot_baselines)
        for sa_id, unit, size, stor_id, _, _ in all_movements:
            all_entity_keys.add(_entity_key(sa_id, unit, size, stor_id))

        # Sum movements per entity
        movement_sums: dict[tuple, Decimal] = {}
        for sa_id, unit, size, stor_id, movement_date, amount in all_movements:
            movement_amount = amount or Decimal("0")
            if movement_amount == 0:
                continue

            key = _entity_key(sa_id, unit, size, stor_id)

            # Skip movements that predate this entity's snapshot
            if key in snapshot_baselines:
                _, snap_date = snapshot_baselines[key]
                if movement_date <= snap_date:
                    continue

            movement_sums[key] = movement_sums.get(key, Decimal("0")) + movement_amount

        # ── Step 3: calculate final results ────────────────────────
        result: dict[tuple, dict] = {}

        for key in all_entity_keys:
            baseline = snapshot_baselines.get(key, (Decimal("0"), None))[0]
            movements = movement_sums.get(key, Decimal("0"))
            running_balance = baseline + movements  # Decimal

            result[key] = _build_result_row(
                running_balance,
                inventory_map.get(key, {}),
                has_inventory=key in inventory_map,
            )

        return result

    @staticmethod
    def _current_stock_from_projection(
        target_dt_start: datetime,
        target_dt_end: datetime,
        storage: str | None,
        entity_filter: dict[str, str] | None,
    ) -> dict[tuple, dict]:
        """Fast path for ``target_date == today``.

        Reads the maintained ``CurrentStockBalance`` projection (one row per
        entity, updated transactionally with every movement change). Inventories
        on the target day are still fetched from MovementShareArticle to expose
        the per-entity ``is_finalized``/``washed``/etc. flags.
        """
        base_filter = _build_base_filter(storage, entity_filter)

        # Today's INVENTORY rows — same as slow path step 1
        inventory_map = _days_inventory_map(target_dt_start, target_dt_end, base_filter)

        # Maintained balances — one indexed lookup per entity, no aggregation.
        # CurrentStockBalance shares the entity field names with
        # MovementShareArticle, so the same base filter applies directly.
        balance_qs = CurrentStockBalance.objects.filter(base_filter)

        balances: dict[tuple, Decimal] = {
            _entity_key(b.share_article_id, b.unit, b.size, b.storage_id): b.balance
            for b in balance_qs
        }

        # The projection counts every movement on record (no date filter — see
        # SnapshotService.compute_balance). For "today" queries we want the
        # balance *at end of today*, so subtract any movements strictly after
        # target_dt_end (e.g. an INVENTORY scheduled for tomorrow).
        future_sums: dict[tuple, Decimal] = {}
        future_qs = (
            MovementShareArticle.objects.filter(date__gt=target_dt_end)
            .filter(base_filter)
            .values_list("share_article_id", "unit", "size", "storage_id", "amount")
        )
        for sa_id, unit, size, stor_id, amount in future_qs:
            key = _entity_key(sa_id, unit, size, stor_id)
            future_sums[key] = future_sums.get(key, Decimal("0")) + (
                amount or Decimal("0")
            )

        # Entities to emit: union of balances and today's inventories
        all_keys = set(balances) | set(inventory_map)

        result: dict[tuple, dict] = {}
        for key in all_keys:
            raw_balance = balances.get(key, Decimal("0"))
            future = future_sums.get(key, Decimal("0"))
            running_balance = raw_balance - future  # Decimal

            result[key] = _build_result_row(
                running_balance,
                inventory_map.get(key, {}),
                has_inventory=key in inventory_map,
            )
        return result
