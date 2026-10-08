"""Stock counts: the INVENTORY movements a physical count writes.

The count endpoints and the bulk count endpoints share these, so a count is
dated, deduplicated and cascaded the same way whichever endpoint writes it.
"""

from __future__ import annotations

from datetime import datetime
from datetime import time as dt_time
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from ..models import MovementShareArticle
from ..models.choices import MovementTypeOptions
from ..utils.iso_week_utils import week_day_to_date
from .snapshot_service import SnapshotService


def inventory_datetime(year: int, delivery_week: int, day_number: int) -> datetime:
    """Convert (year, week, day_number-index) to a tz-aware datetime at 23:00.

    INVENTORY movements use 23:00 so they sort after all operational
    movements (harvests, allocations, etc.) which are recorded at noon.
    """
    cal_date = week_day_to_date(year, delivery_week, day_number)
    return timezone.make_aware(datetime.combine(cal_date, dt_time(23, 0, 0)))


def is_inventory_race(exc: IntegrityError | DjangoValidationError) -> bool:
    """True only for the ``one_inventory_per_entity_day`` unique violation — a
    concurrent writer created this entity-day's INVENTORY row first (a lost
    race that CONVERGES to an update).

    The race surfaces as EITHER exception type: ``MovementShareArticle.save()``
    runs ``full_clean()`` → ``validate_constraints()``, so when the winner is
    already committed and visible to the pre-INSERT SELECT it raises a Django
    ``ValidationError`` (message carries the constraint name); when the winner
    commits between that validation and the INSERT it's a DB ``IntegrityError``.
    Any OTHER error (an FK violation from a stale composite id, a genuine
    ``clean()`` failure) must propagate, not be swallowed."""
    cause = exc.__cause__
    constraint_name = getattr(getattr(cause, "diag", None), "constraint_name", "") or ""
    return (
        constraint_name.endswith("one_inventory_per_entity_day")
        or "one_inventory_per_entity_day" in str(exc).lower()
    )


def get_or_create_inventory(
    parsed: dict, defaults: dict
) -> tuple[MovementShareArticle, bool]:
    """Find an existing INVENTORY movement for the day_number or create one."""
    inventory_date = inventory_datetime(
        parsed["year"], parsed["delivery_week"], parsed["day_number"]
    )
    inventory_start = inventory_date.replace(hour=0, minute=0, second=0)
    inventory_end = inventory_date.replace(hour=23, minute=59, second=59)

    existing = (
        MovementShareArticle.objects.select_for_update()
        .filter(
            movement_type=MovementTypeOptions.INVENTORY,
            share_article_id=parsed["share_article_id"],
            unit=parsed["unit"],
            size=parsed["size"],
            storage_id=parsed["storage_id"],
            date__gte=inventory_start,
            date__lte=inventory_end,
        )
        .order_by("-date")
        .first()
    )

    if existing:
        return existing, False

    # Remove stale snapshots before computing balance
    storage_str = str(parsed["storage_id"]) if parsed["storage_id"] else None
    SnapshotService.delete_snapshots_for_entity(
        str(parsed["share_article_id"]),
        parsed["unit"],
        parsed["size"],
        storage_str,
        date_from=inventory_start,
        date_to=inventory_end,
    )

    # Compute correction delta
    running_balance = SnapshotService.compute_balance(
        str(parsed["share_article_id"]),
        parsed["unit"],
        parsed["size"],
        storage_str,
        up_to=inventory_end,
    )
    # Defensive coercion: callers may pass int / float / str — go through
    # ``str()`` to absorb any float input without binary-fp drift.
    raw_amount = defaults.get("amount", 0) or 0
    amount = raw_amount if isinstance(raw_amount, Decimal) else Decimal(str(raw_amount))
    correction = amount - running_balance

    try:
        # Savepoint so a lost race (one_inventory_per_entity_day) rolls
        # back ONLY this INSERT, not the caller's whole bulk transaction.
        with transaction.atomic():
            inventory = MovementShareArticle.objects.create(
                date=inventory_date,
                movement_type=MovementTypeOptions.INVENTORY,
                share_article_id=parsed["share_article_id"],
                unit=parsed["unit"],
                size=parsed["size"],
                storage_id=parsed["storage_id"],
                amount=correction,
                counted_amount=amount,
                is_finalized=defaults.get("is_finalized", False),
                **{
                    k: v
                    for k, v in defaults.items()
                    if k not in ("amount", "is_finalized")
                },
            )
    except (IntegrityError, DjangoValidationError) as exc:
        # Only the one-inventory-per-entity-day UNIQUE race is a "converge to
        # update" case. It surfaces as a Django ValidationError (full_clean's
        # validate_constraints saw the committed winner) OR an IntegrityError
        # (winner committed between validate and INSERT). A different error —
        # e.g. an FK violation from a stale composite id (bad share_article/
        # storage), or a genuine clean() failure — must NOT be swallowed as a
        # lost race, which would hand the caller None. Re-raise anything else.
        if not is_inventory_race(exc):
            raise

        # A concurrent writer inserted this entity-day's INVENTORY first. Re-fetch
        # the winner and treat it as found, so the caller converges to an update
        # instead of erroring (and the batch keeps going).
        existing = (
            MovementShareArticle.objects.filter(
                movement_type=MovementTypeOptions.INVENTORY,
                share_article_id=parsed["share_article_id"],
                unit=parsed["unit"],
                size=parsed["size"],
                storage_id=parsed["storage_id"],
                date__gte=inventory_start,
                date__lte=inventory_end,
            )
            .order_by("-date")
            .first()
        )
        if existing is None:
            # The unique violation fired but no row is visible on re-fetch:
            # re-raise the original error rather than return None, which the
            # caller can't use.
            raise
        return existing, False

    SnapshotService.create_snapshot_for_entity(
        str(parsed["share_article_id"]),
        parsed["unit"],
        parsed["size"],
        storage_str,
        snapshot_date=inventory_date,
    )

    # Cascade like the single-entry PATCH path: re-derive every LATER INVENTORY's
    # stored delta against the new balance_before and refresh the maintained
    # CurrentStockBalance projection (cascade_future_inventories calls
    # recompute_for_entity at the end). The bulk callers (finalize /
    # set-as-expected / set-to-zero) never ran a deferred cascade, so without
    # this a bulk inventory inserted BEFORE an existing later one left that later
    # delta — and the projection the office reads — stale until
    # ``reconcile_current_stock`` ran.
    SnapshotService.cascade_future_inventories(
        str(parsed["share_article_id"]),
        parsed["unit"],
        parsed["size"],
        storage_str,
        after_date=inventory_date,
    )

    return inventory, True
