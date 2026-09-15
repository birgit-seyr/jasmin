"""Maintained current-balance projection for stock queries.

This is the "current state" half of a CQRS-lite pattern over
``MovementShareArticle`` (the append-only event log). A single
``CurrentStockBalance`` row per ``(share_article, unit, size, storage)``
entity is kept in sync with the movement ledger so the DocumentationCurrentStock
page can read O(N) rows instead of summing the full history every request.

Write path: ``CurrentBalanceService.recompute_for_entity(...)`` is called from
every movement-mutating chokepoint (snapshot cascades, inventory-create
helpers). Each call recomputes the entity's balance via
``SnapshotService.compute_balance`` (which itself uses the latest snapshot as
a baseline) and upserts the row, or removes it once the entity has no movements
left. Idempotent.

Reconciliation: ``get_drift()`` compares every stored balance against a fresh
recompute and returns the drifted rows. Used by the
``reconcile_current_stock`` management command, which calls
``recompute_for_entity()`` per drifted entity to repair.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TypeAlias

from django.db import transaction

from ..models import CurrentStockBalance
from .snapshot_service import SnapshotService

EntityKey: TypeAlias = tuple[str, str | None, str | None, str | None]


def _lock_sort_key(key: EntityKey) -> tuple[str, str, str, str]:
    """Deterministic, None-safe sort key for a ``current_balance`` lock.

    Coerces every ``None`` to ``""`` so (a) tuple comparison never trips over
    ``None < str`` (a py3 ``TypeError``) and (b) the order matches the
    ``"…:{unit or ''}:…"`` string the lock itself is keyed on. Every lock-
    acquisition site MUST use this same ordering so two transactions touching an
    overlapping entity set take the shared locks in the same order (no AB/BA)."""
    return tuple(part or "" for part in key)  # type: ignore[return-value]


def _normalize(
    share_article_id: str,
    unit: str | None,
    size: str | None,
    storage_id: str | None,
) -> EntityKey:
    return (
        str(share_article_id),
        unit,
        size,
        str(storage_id) if storage_id else None,
    )


class CurrentBalanceService:
    """Maintain ``CurrentStockBalance`` as a projection of the movement ledger."""

    @staticmethod
    def acquire_locks_for_entities(entity_keys: Iterable[EntityKey]) -> None:
        """Take every entity's ``current_balance`` advisory lock UP FRONT,
        in one canonical (sorted) order, before any cascade / movement work.

        The per-entity lock is otherwise acquired incrementally inside
        ``recompute_for_entity`` — in whatever order a caller happens to process
        its entities (bulk-view request-body order, an unordered movement list)
        — and, being transaction-scoped, is held until the OUTERMOST transaction
        commits. Two concurrent operations over an overlapping entity set could
        therefore take the shared locks in opposite orders and deadlock (AB/BA).
        Pre-acquiring them all sorted gives every caller the same order; the
        later ``recompute_for_entity`` calls just re-take an already-held
        (re-entrant, transaction-scoped) lock, so this is purely additive.

        MUST be called inside the caller's ``transaction.atomic`` block.
        """
        from core.db_locks import acquire_advisory_xact_lock

        deduped = {_normalize(*key) for key in entity_keys}
        for share_article_id, unit, size, storage_id in sorted(
            deduped, key=_lock_sort_key
        ):
            acquire_advisory_xact_lock(
                f"current_balance:{share_article_id}:{unit or ''}:{size or ''}"
                f":{storage_id or ''}"
            )

    @staticmethod
    def _ledger_balance(
        share_article_id: str,
        unit: str | None,
        size: str | None,
        storage_id: str | None,
    ):
        """The entity's balance straight from the FULL movement ledger — no
        snapshot baseline. This is the same quantity ``get_drift`` trusts as
        ground truth (its grouped ``Sum('amount')`` per entity)."""
        from decimal import Decimal

        from django.db.models import Sum

        from ..models import MovementShareArticle

        total = MovementShareArticle.objects.filter(
            share_article_id=share_article_id,
            unit=unit,
            size=size,
            storage_id=storage_id,
        ).aggregate(total=Sum("amount"))["total"]
        return total or Decimal("0")

    @staticmethod
    @transaction.atomic
    def recompute_for_entity(
        share_article_id: str,
        unit: str | None,
        size: str | None,
        storage_id: str | None,
        *,
        from_ledger: bool = False,
    ) -> CurrentStockBalance | None:
        """Recompute the balance for one entity and upsert. Idempotent.

        An entity without movements and with a zero balance has no stock: its row
        is removed and ``None`` returned. A leftover zero row would still count as
        a use of the share article (the foreign key is PROTECT) and block deleting
        the article.

        ``from_ledger=False`` (default, the hot cascade path): uses
        ``compute_balance``, which short-circuits via the most recent
        ``StockSnapshot`` — cheap when snapshots are fresh.

        ``from_ledger=True`` (the reconcile ``--fix`` repair path): sums the FULL
        ledger directly, bypassing the snapshot baseline. A repair MUST converge
        to the ground truth ``get_drift`` checks against — if it reused the
        snapshot-baselined ``compute_balance`` and the snapshot itself were
        corrupt (the exact failure reconciliation exists to catch), repair would
        rewrite the same wrong value and the drift would never clear.
        """
        # Serialize the read-modify-write per entity so concurrent writers
        # for the same entity (an INVENTORY PATCH + a share/theoretical recompute,
        # which lock disjoint objects) can't lost-update the projection. The lock
        # is transaction-scoped — this method is @transaction.atomic — and keyed
        # WITHOUT movement_type so every movement kind shares one lock.
        from core.db_locks import acquire_advisory_xact_lock

        acquire_advisory_xact_lock(
            f"current_balance:{share_article_id}:{unit or ''}:{size or ''}"
            f":{storage_id or ''}"
        )

        if from_ledger:
            balance = CurrentBalanceService._ledger_balance(
                share_article_id, unit, size, storage_id
            )
        else:
            balance = SnapshotService.compute_balance(
                share_article_id, unit, size, storage_id
            )
        from ..models import MovementShareArticle

        entity = {
            "share_article_id": share_article_id,
            "unit": unit,
            "size": size,
            "storage_id": storage_id,
        }
        if balance == 0 and not MovementShareArticle.objects.filter(**entity).exists():
            CurrentStockBalance.objects.filter(**entity).delete()
            return None
        # update_or_create is safe under our partial unique index because
        # nulls_distinct=False (PG15+) treats two NULL storages as equal.
        obj, _ = CurrentStockBalance.objects.update_or_create(
            share_article_id=share_article_id,
            unit=unit,
            size=size,
            storage_id=storage_id,
            defaults={"balance": balance},
        )
        return obj

    @staticmethod
    def get_drift() -> list[dict]:
        """Compare every stored balance against the ledger's true sum.

        Returns one entry per drifted row: ``{"entity": ..., "stored": ...,
        "expected": ...}``. An empty list means the projection is consistent
        with the ledger.

        Expected is the full per-entity movement sum, computed in ONE grouped
        query (rather than a per-row ``compute_balance`` round-trip, an N+1 over
        every CurrentStockBalance). This is the SAME raw-ledger quantity
        the ``--fix`` repair writes (``recompute_for_entity(from_ledger=True)``),
        so a repaired row matches ``expected`` by construction and the drift
        clears even when an entity's snapshot is itself corrupt.

        Also flags entities present in the ledger but MISSING a projection row
        (``stored=None``) so ``--fix`` seeds them, and rows for entities without
        any movements (``has_movements=False``) so ``--fix`` removes them.
        """
        from decimal import Decimal

        from django.db.models import Sum

        from ..models import MovementShareArticle

        ledger_sums: dict[EntityKey, object] = {}
        for agg in MovementShareArticle.objects.values(
            "share_article_id", "unit", "size", "storage_id"
        ).annotate(total=Sum("amount")):
            key = _normalize(
                agg["share_article_id"], agg["unit"], agg["size"], agg["storage_id"]
            )
            ledger_sums[key] = agg["total"] or Decimal("0")

        drift: list[dict] = []
        seen: set[EntityKey] = set()
        for row in CurrentStockBalance.objects.iterator():
            key = _normalize(row.share_article_id, row.unit, row.size, row.storage_id)
            seen.add(key)
            has_movements = key in ledger_sums
            expected = ledger_sums.get(key, Decimal("0"))
            if expected != row.balance or not has_movements:
                drift.append(
                    {
                        "entity": key,
                        "stored": row.balance,
                        "expected": expected,
                        "has_movements": has_movements,
                    }
                )
        # Ledger entities with no projection row at all — invisible to the loop
        # above. A non-zero ledger sum with no row is a missing projection.
        for key, expected in ledger_sums.items():
            if key not in seen and expected != Decimal("0"):
                drift.append(
                    {
                        "entity": key,
                        "stored": None,
                        "expected": expected,
                        "has_movements": True,
                    }
                )
        return drift

    @staticmethod
    def get_snapshot_drift() -> list[dict]:
        """Compare every ``StockSnapshot``'s stored balance against the raw ledger
        sum up to its ``snapshot_date``.

        ``get_drift`` only checks the CURRENT total, so a snapshot that is wrong at
        its own date but masked by a correct LATER snapshot (or whose error nets
        out of the current total) is invisible to it — yet it still poisons every
        ``compute_balance(from_ledger=False)`` that baselines off it and every
        historical ``compute_balance(up_to=...)`` between it and the next snapshot.

        Returns one entry per drifted snapshot: ``{"entity", "snapshot_date",
        "stored", "expected"}``. One aggregate per snapshot — fine for an
        out-of-band maintenance command.
        """
        from decimal import Decimal

        from django.db.models import Sum

        from ..models import MovementShareArticle, StockSnapshot

        drift: list[dict] = []
        for snap in StockSnapshot.objects.iterator():
            expected = MovementShareArticle.objects.filter(
                share_article_id=snap.share_article_id,
                unit=snap.unit,
                size=snap.size,
                storage_id=snap.storage_id,
                date__lte=snap.snapshot_date,
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
            if expected != snap.balance:
                drift.append(
                    {
                        "entity": _normalize(
                            snap.share_article_id,
                            snap.unit,
                            snap.size,
                            snap.storage_id,
                        ),
                        "snapshot_date": snap.snapshot_date,
                        "stored": snap.balance,
                        "expected": expected,
                    }
                )
        return drift

    @staticmethod
    @transaction.atomic
    def repair_snapshots_for_entity(
        share_article_id: str,
        unit: str | None,
        size: str | None,
        storage_id: str | None,
    ) -> None:
        """Rebuild an entity's snapshots from the ledger.

        DROP ALL of the entity's snapshots first — with none present,
        ``compute_balance`` falls back to the full raw-ledger sum and cannot
        re-read a corrupt baseline — then reseed ONE fresh ``now`` snapshot (its
        balance recomputed from the ledger) so current reads stay O(1), and
        recompute the current balance. Historical ``compute_balance(up_to=<past>)``
        queries find no snapshot at/ before that past date and likewise fall back
        to the ledger, so they are correct too. Runs under the entity's
        ``current_balance`` lock so it serializes with concurrent cascades; keeping
        the repair here (not in ``recompute_for_entity``) leaves that hot path's
        single raw-ledger responsibility untouched.
        """
        from core.db_locks import acquire_advisory_xact_lock

        acquire_advisory_xact_lock(
            f"current_balance:{share_article_id}:{unit or ''}:{size or ''}"
            f":{storage_id or ''}"
        )
        SnapshotService.delete_snapshots_for_entity(
            share_article_id, unit, size, storage_id
        )
        SnapshotService.create_snapshot_for_entity(
            share_article_id, unit, size, storage_id
        )
        CurrentBalanceService.recompute_for_entity(
            share_article_id, unit, size, storage_id, from_ledger=True
        )
