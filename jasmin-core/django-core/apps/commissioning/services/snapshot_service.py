from __future__ import annotations

from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone

from ..models import MovementShareArticle, StockSnapshot
from ..models.choices import MovementTypeOptions


class SnapshotService:
    """Create and query StockSnapshot entries for efficient balance lookups."""

    @staticmethod
    def create_snapshot_for_entity(
        share_article_id: str,
        unit: str | None,
        size: str | None,
        storage_id: str | None,
        snapshot_date=None,
    ) -> StockSnapshot:
        """
        Compute the running balance from all movements up to *snapshot_date*
        and persist a new StockSnapshot row.
        """
        if snapshot_date is None:
            snapshot_date = timezone.now()

        # Remove any existing snapshot for this entity at this timestamp so
        # compute_balance doesn't use a stale baseline.
        SnapshotService.delete_snapshots_for_entity(
            share_article_id,
            unit,
            size,
            storage_id,
            date_from=snapshot_date,
            date_to=snapshot_date,
        )

        balance = SnapshotService.compute_balance(
            share_article_id, unit, size, storage_id, up_to=snapshot_date
        )

        return StockSnapshot.objects.create(
            snapshot_date=snapshot_date,
            share_article_id=share_article_id,
            unit=unit,
            size=size,
            storage_id=storage_id,
            balance=balance,
        )

    @staticmethod
    def delete_snapshots_for_entity(
        share_article_id: str,
        unit: str | None,
        size: str | None,
        storage_id: str | None,
        date_from=None,
        date_to=None,
    ) -> int:
        """Delete snapshots for an entity, optionally within a date range."""
        qs = StockSnapshot.objects.filter(
            share_article_id=share_article_id,
            unit=unit,
            size=size,
            storage_id=storage_id,
        )
        if date_from is not None:
            qs = qs.filter(snapshot_date__gte=date_from)
        if date_to is not None:
            qs = qs.filter(snapshot_date__lte=date_to)
        count, _ = qs.delete()
        return count

    @staticmethod
    def rebuild_entity_day(
        share_article_id: str,
        unit: str | None,
        size: str | None,
        storage_id: str | None,
        *,
        day_start,
        day_end,
        snapshot_date,
        cascade_after=None,
    ) -> None:
        """Rebuild an entity's snapshot baseline after a day's INVENTORY changed.

        Deletes the day's snapshots (``day_start``..``day_end``), recreates the
        day snapshot at *snapshot_date*, then cascades future INVENTORY deltas
        and snapshots (``after_date`` = *cascade_after*, defaulting to
        *snapshot_date*).
        """
        SnapshotService.delete_snapshots_for_entity(
            share_article_id,
            unit,
            size,
            storage_id,
            date_from=day_start,
            date_to=day_end,
        )
        SnapshotService.create_snapshot_for_entity(
            share_article_id,
            unit,
            size,
            storage_id,
            snapshot_date=snapshot_date,
        )
        SnapshotService.cascade_future_inventories(
            share_article_id,
            unit,
            size,
            storage_id,
            after_date=cascade_after if cascade_after is not None else snapshot_date,
        )

    @staticmethod
    def cascade_future_inventories(
        share_article_id: str,
        unit: str | None,
        size: str | None,
        storage_id: str | None,
        after_date,
    ) -> int:
        """
        Recalculate all INVENTORY movements and snapshots that come after
        *after_date* for a single entity.

        Each INVENTORY stores a correction delta (counted − balance_before)
        in ``amount`` and the absolute counted value in ``counted_amount``.
        When an earlier movement changes, the balance_before of every later
        INVENTORY shifts, so the delta must be recomputed to preserve the
        original absolute counted value.

        Returns the number of INVENTORY movements that were updated.
        """
        # 1. Wipe all snapshots after the changed date — they are stale.
        SnapshotService.delete_snapshots_for_entity(
            share_article_id,
            unit,
            size,
            storage_id,
            date_from=after_date,
        )

        # 2. Find all future INVENTORY movements, ordered chronologically.
        entity_q = Q(share_article_id=share_article_id)
        entity_q &= Q(unit=unit) if unit is not None else Q(unit__isnull=True)
        entity_q &= Q(size=size) if size is not None else Q(size__isnull=True)
        if storage_id is not None:
            entity_q &= Q(storage_id=storage_id)
        else:
            entity_q &= Q(storage__isnull=True)

        future_inventories = list(
            MovementShareArticle.objects.filter(
                entity_q,
                movement_type=MovementTypeOptions.INVENTORY,
                date__gt=after_date,
            ).order_by(
                "date", "id"
            )  # ``id`` tiebreaker → deterministic cascade
        )

        updated = 0
        if future_inventories:
            # 3. Zero out future deltas so compute_balance returns a clean
            #    balance_before for each INVENTORY. ONLY rows we can recompute
            #    (counted_amount set) are zeroed; a NULL-counted_amount row
            #    (legacy/imported) is left UNTOUCHED — zeroing it here then
            #    skipping it in step 4 destroyed its delta forever (MOV-8). One
            #    bulk_update instead of a save() per row (no inter-row dependency).
            recomputable = [
                m for m in future_inventories if m.counted_amount is not None
            ]
            for inventory_movement in recomputable:
                inventory_movement.amount = Decimal("0")
            MovementShareArticle.objects.bulk_update(recomputable, ["amount"])

            # 4. Walk forward, recompute each delta from the stored
            #    counted_amount, and rebuild snapshots.
            for inventory_movement in recomputable:
                balance_before = SnapshotService.compute_balance(
                    share_article_id,
                    unit,
                    size,
                    storage_id,
                    up_to=inventory_movement.date,
                )
                new_delta = inventory_movement.counted_amount - balance_before
                inventory_movement.amount = new_delta
                inventory_movement.save(update_fields=["amount"])

                # Recreate a fresh snapshot at this point.
                SnapshotService.create_snapshot_for_entity(
                    share_article_id,
                    unit,
                    size,
                    storage_id,
                    snapshot_date=inventory_movement.date,
                )
                updated += 1

        # Refresh the maintained current-balance projection. Done in every
        # path (even with no future inventories) because the movement change
        # that triggered the cascade has already shifted the running balance.
        # Local import to avoid a circular import (CurrentBalanceService
        # imports SnapshotService).
        from .current_balance_service import CurrentBalanceService

        CurrentBalanceService.recompute_for_entity(
            share_article_id, unit, size, storage_id
        )

        return updated

    @staticmethod
    def cascade_for_movements(
        movements: list[MovementShareArticle],
    ) -> int:
        """
        Cascade future inventories for every unique entity affected by
        the given movements.  Collects the earliest date per entity and
        calls *cascade_future_inventories* once for each.
        """
        entities: dict[tuple, object] = {}  # key -> earliest date
        for movement in movements:
            key = (
                str(movement.share_article_id),
                movement.unit,
                movement.size,
                str(movement.storage_id) if movement.storage_id else None,
            )
            if key not in entities or movement.date < entities[key]:
                entities[key] = movement.date

        # TXN-1: cascade in a canonical (sorted) entity order so the per-entity
        # ``current_balance`` advisory locks (taken transaction-scoped inside
        # recompute_for_entity, held to the outer commit) are acquired in the
        # same order as every other caller — an unordered movement list would
        # otherwise let two overlapping recomputes/bulk-writes deadlock (AB/BA).
        # None-coerced sort key mirrors CurrentBalanceService's lock ordering.
        total = 0
        for (sa_id, unit, size, storage_id), date in sorted(
            entities.items(),
            key=lambda item: tuple(part or "" for part in item[0]),
        ):
            total += SnapshotService.cascade_future_inventories(
                share_article_id=sa_id,
                unit=unit,
                size=size,
                storage_id=storage_id,
                after_date=date,
            )
        return total

    @staticmethod
    def compute_balance(
        share_article_id: str,
        unit: str | None,
        size: str | None,
        storage_id: str | None,
        up_to=None,
    ) -> Decimal:
        """
        Compute the running balance for a single entity, optionally using an
        existing snapshot as a baseline to avoid scanning all rows.

        ``up_to`` is an upper bound on movement and snapshot dates.
        ``up_to=None`` means **no bound** — sum every movement on record. This
        is what the maintained ``CurrentStockBalance`` projection wants:
        INVENTORY movements are stored at 23:00 local time, so filtering by
        ``timezone.now()`` would silently drop today's inventory whenever the
        recompute runs before evening.
        """
        entity_q = Q(share_article_id=share_article_id)
        if unit is not None:
            entity_q &= Q(unit=unit)
        else:
            entity_q &= Q(unit__isnull=True)
        if size is not None:
            entity_q &= Q(size=size)
        else:
            entity_q &= Q(size__isnull=True)
        if storage_id is not None:
            entity_q &= Q(storage_id=storage_id)
        else:
            entity_q &= Q(storage__isnull=True)

        snapshot_qs = StockSnapshot.objects.filter(entity_q)
        if up_to is not None:
            snapshot_qs = snapshot_qs.filter(snapshot_date__lte=up_to)
        latest_snapshot = snapshot_qs.order_by("-snapshot_date").first()

        movement_qs = MovementShareArticle.objects.filter(entity_q)
        if up_to is not None:
            movement_qs = movement_qs.filter(date__lte=up_to)

        if latest_snapshot:
            baseline = latest_snapshot.balance
            movements_sum = movement_qs.filter(
                date__gt=latest_snapshot.snapshot_date
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        else:
            baseline = Decimal("0")
            movements_sum = movement_qs.aggregate(total=Sum("amount"))[
                "total"
            ] or Decimal("0")

        return baseline + movements_sum
