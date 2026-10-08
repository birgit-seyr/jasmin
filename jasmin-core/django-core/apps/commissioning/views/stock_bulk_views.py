"""The three bulk stock count endpoints: finalize, set as expected and set to
zero. Each reports what it wrote next to a per-id ``errors`` list, with HTTP 207
when any id failed."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError, transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import IsStaff
from core.serializers import ErrorResponseSerializer

from ..errors import CompositeIdInvalid, PastWeekError
from ..models import MovementShareArticle
from ..serializers import BulkIdsRequestSerializer
from ..services import CurrentBalanceService, SnapshotService, StockService
from ..services.inventory_counts import get_or_create_inventory, inventory_datetime
from ..utils import parse_composite_id
from ..utils.stock_count_input import writable_composite_id
from ..utils.validation_utils import parse_bulk_ids


def _past_week_error(composite_id: str, exc: PastWeekError) -> dict[str, str]:
    """A per-id error for an id in a read-only week, with the code a client
    translates."""
    return {"id": composite_id, "error": exc.message, "code": exc.code}


def _group_composite_ids(
    composite_ids: list[str],
) -> tuple[dict[tuple, list[tuple[str, dict]]], list[dict[str, str]]]:
    """
    Parse and group composite IDs by (year, week, day_number, storage). An id
    in a week the stock count page shows read-only is reported, not grouped.

    Returns (grouped_ids, errors).
    """
    grouped: dict[tuple, list[tuple[str, dict]]] = defaultdict(list)
    errors: list[dict[str, str]] = []

    for composite_id in composite_ids:
        try:
            parsed = writable_composite_id(composite_id)
            group_key = (
                parsed["year"],
                parsed["delivery_week"],
                parsed["day_number"],
                parsed["storage_id"],
            )
            grouped[group_key].append((composite_id, parsed))
        except PastWeekError as exc:
            errors.append(_past_week_error(composite_id, exc))
        except (ValueError, CompositeIdInvalid) as e:
            errors.append(
                {"id": composite_id, "error": f"Invalid composite ID: {str(e)}"}
            )

    return grouped, errors


def _build_stock_key(parsed: dict) -> tuple:
    return (
        parsed["share_article_id"],
        parsed["unit"],
        parsed["size"],
        parsed["storage_id"],
    )


def _process_grouped_stock_with_theoretical(
    grouped: dict[tuple, list[tuple[str, dict]]],
    errors: list[dict[str, str]],
    *,
    process_item: Callable[[dict, float], tuple[int, int]],
) -> tuple[int, int]:
    """
    Iterate grouped composite IDs, fetch theoretical stock per group,
    and call process_item(parsed, theoretical_amount) for each item.

    Returns (updated_count, created_count).
    """
    updated_count = 0
    created_count = 0

    for group_key, items in grouped.items():
        year, delivery_week, day_number, storage_id = group_key

        try:
            # Savepoint around the group-level aggregation. Without it a
            # DatabaseError here (a lock / statement timeout on a big week's
            # movement aggregation, a connection blip) leaves the view's OUTER
            # @transaction.atomic poisoned: the ``except`` below would swallow it
            # and the loop keep going, but Postgres has aborted the transaction,
            # so the final COMMIT silently ROLLBACKs every already-processed
            # group — the 207 then reports ``updated``/``created`` counts that
            # never persisted (ERR contract in services/bulk_operations.py). The
            # savepoint rolls back only this fetch and keeps the connection
            # usable, so prior groups still commit and this group fails cleanly.
            with transaction.atomic():
                stock_map = StockService.get_theoretical_current_stock(
                    year, delivery_week, day_number, storage_id
                )
        except (
            DatabaseError,
            DjangoValidationError,
            DRFValidationError,
            ValueError,
        ) as exc:
            # Whole-group failure (StockService.get_theoretical_current_stock).
            # Re-attribute to each composite_id so the bulk response can show
            # per-id status — see _process_grouped_stock_with_theoretical doc.
            for composite_id, _ in items:
                if not any(err["id"] == composite_id for err in errors):
                    errors.append(
                        {"id": composite_id, "error": f"StockService error: {exc}"}
                    )
            continue

        for composite_id, parsed in items:
            try:
                stock_key = _build_stock_key(parsed)

                if stock_key not in stock_map:
                    errors.append(
                        {"id": composite_id, "error": "Theoretical stock not found"}
                    )
                    continue

                theoretical_amount = stock_map[stock_key]["theoretical_current_stock"]
                # Per-item savepoint: a DB error in ``process_item`` (a
                # constraint violation, a row deleted concurrently under
                # select_for_update) rolls back only this item and keeps the
                # connection usable. Without it the first failure poisons the
                # view's outer atomic and every later item raises
                # TransactionManagementError → the whole batch 500s.
                with transaction.atomic():
                    was_updated, was_created = process_item(parsed, theoretical_amount)
                updated_count += was_updated
                created_count += was_created

            except (
                DatabaseError,
                DjangoValidationError,
                DRFValidationError,
                ValueError,
            ) as exc:
                # Per-item failure collection inside a bulk operation.
                errors.append({"id": composite_id, "error": str(exc)})

    return updated_count, created_count


class _InventoryAlreadyCounted(ValueError):
    """An existing INVENTORY row a bulk count must not overwrite — it already
    carries a physical count, or it is finalized.

    A ``ValueError`` so the bulk loops' per-item handlers report it as a per-id
    entry, instead of the action silently returning updated=0 / created=0.
    """


def _refuse_recount(inventory: MovementShareArticle) -> None:
    """Raise unless *inventory* is an uncounted row a bulk count may fill in."""
    if inventory.is_finalized:
        raise _InventoryAlreadyCounted(
            "Inventory entry is finalized — unfinalize it before recounting."
        )
    if inventory.counted_amount is not None:
        raise _InventoryAlreadyCounted(
            f"Inventory entry already counted ({inventory.counted_amount}) — "
            "left unchanged; clear the count first to overwrite it."
        )


def _record_counted_amount(
    inventory: MovementShareArticle, parsed: dict, counted
) -> None:
    """Write an absolute counted value onto an EXISTING INVENTORY row.

    Mirrors the single-entry PATCH: ``amount`` holds the correction delta
    against the balance BEFORE this row, so this row's own stored correction is
    taken back out of the running balance before the new delta is derived. The
    day's snapshot baseline is then rebuilt and the later INVENTORY deltas
    re-cascaded, or every downstream balance keeps reflecting the old count.
    """
    counted = counted if isinstance(counted, Decimal) else Decimal(str(counted))

    inventory_date = inventory_datetime(
        parsed["year"], parsed["delivery_week"], parsed["day_number"]
    )
    day_start = inventory_date.replace(hour=0, minute=0, second=0)
    day_end = inventory_date.replace(hour=23, minute=59, second=59)
    storage_str = str(parsed["storage_id"]) if parsed["storage_id"] else None

    running_balance = SnapshotService.compute_balance(
        str(parsed["share_article_id"]),
        parsed["unit"],
        parsed["size"],
        storage_str,
        up_to=day_end,
    )
    # All Decimal so the value stored back to the DecimalField carries no
    # binary-fp drift.
    balance_before = running_balance - inventory.amount
    inventory.amount = counted - balance_before
    inventory.counted_amount = counted
    inventory.save()

    SnapshotService.rebuild_entity_day(
        str(parsed["share_article_id"]),
        parsed["unit"],
        parsed["size"],
        storage_str,
        day_start=day_start,
        day_end=day_end,
        snapshot_date=inventory_date,
    )


def _stamp_finalized_count(inventory: MovementShareArticle, parsed: dict) -> None:
    """Finalize an EXISTING uncounted INVENTORY row at the stock it reports.

    ``counted_amount`` becomes the entity's balance INCLUDING this row's own
    correction — the value the office reads as current stock — and ``amount``
    is left exactly as it stands, so locking the day moves no balance and needs
    no snapshot rebuild. Deriving a fresh delta here instead would discard
    whatever correction a NULL-counted row stores (the cascade refuses to touch
    those for that reason) and, when the balance is negative, would stamp a
    count nobody took.
    """
    inventory_date = inventory_datetime(
        parsed["year"], parsed["delivery_week"], parsed["day_number"]
    )
    day_end = inventory_date.replace(hour=23, minute=59, second=59)

    inventory.counted_amount = SnapshotService.compute_balance(
        str(parsed["share_article_id"]),
        parsed["unit"],
        parsed["size"],
        str(parsed["storage_id"]) if parsed["storage_id"] else None,
        up_to=day_end,
    )
    inventory.is_finalized = True
    inventory.save()


def _build_bulk_inventory_response(
    updated: int, created: int, errors: list[dict[str, str]]
) -> Response:
    # 207 on partial failure (some items errored), 200 only when every
    # item succeeded — matching the bulk-endpoint convention used in
    # reseller_views / finalize_views. Covers all three bulk-inventory callers.
    status_code = status.HTTP_207_MULTI_STATUS if errors else status.HTTP_200_OK
    return Response(
        {"updated": updated, "created": created, "errors": errors},
        status=status_code,
    )


# Shared @extend_schema fragments for the three bulk-inventory endpoints
# (finalize / set-as-expected / set-to-zero): identical request body
# (``BulkIdsRequestSerializer``) + 200 response shape — only the per-endpoint
# summary/description differ.
_BULK_INVENTORY_RESPONSE_BODY = {
    "type": "object",
    "properties": {
        "updated": {"type": "integer"},
        "created": {"type": "integer"},
        "errors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "error": {"type": "string"},
                    # Only on an id in a read-only week
                    # (``commissioning.past_week``).
                    "code": {"type": "string"},
                },
            },
        },
    },
}

BULK_INVENTORY_RESPONSE = {
    200: OpenApiResponse(
        description="Bulk operation completed (all items succeeded)",
        response=_BULK_INVENTORY_RESPONSE_BODY,
    ),
    207: OpenApiResponse(
        description="Bulk operation completed with per-item errors",
        response=_BULK_INVENTORY_RESPONSE_BODY,
    ),
    400: ErrorResponseSerializer,
}


def _pre_acquire_entity_locks(composite_ids: list[str]) -> None:
    """Take every entity's ``current_balance`` advisory lock up front, in
    one canonical (sorted) order, before the per-item processing loop.

    Each bulk view otherwise acquires the per-entity locks incrementally in
    request-body order (via ``get_or_create_inventory`` → cascade →
    ``recompute_for_entity``) and holds them to the end of the view's outer
    transaction, so two concurrent bulk writes over an overlapping entity set
    could take them in opposite orders and deadlock (AB/BA). Pre-acquiring them
    sorted gives every caller the same order; the later per-item
    ``recompute_for_entity`` calls just re-take a held (re-entrant,
    transaction-scoped) lock. Unparseable ids are skipped here — they surface as
    per-item errors in the processing loop."""
    entity_keys: list[tuple] = []
    for composite_id in composite_ids:
        try:
            parsed = parse_composite_id(composite_id, code="stock.invalid_composite_id")
        except (ValueError, CompositeIdInvalid):
            continue
        entity_keys.append(
            (
                parsed["share_article_id"],
                parsed["unit"],
                parsed["size"],
                parsed["storage_id"],
            )
        )
    CurrentBalanceService.acquire_locks_for_entities(entity_keys)


@extend_schema(
    summary="Bulk finalize inventory entries",
    description="""
    Finalize multiple INVENTORY entries by setting is_finalized=True.
    An entry nobody has counted yet is finalized AT the stock it reports
    (counted == the entity's current balance) with its stored correction left
    alone, so finalizing never moves a balance. An entry that is already
    finalized is left untouched and reported under ``errors`` for that id.
    An id in a week the stock count page shows read-only is left untouched and
    reported under ``errors`` with the code ``commissioning.past_week``.
    """,
    request=BulkIdsRequestSerializer,
    responses=BULK_INVENTORY_RESPONSE,
)
@api_view(["POST"])
@permission_classes([IsStaff])
@transaction.atomic
def bulk_finalize_current_stock(request: Request) -> Response:
    """Finalize multiple INVENTORY entries by setting is_finalized=True."""
    composite_ids = parse_bulk_ids(request)
    _pre_acquire_entity_locks(composite_ids)

    grouped, errors = _group_composite_ids(composite_ids)

    def _process(parsed: dict, theoretical_amount) -> tuple[int, int]:
        inventory, created = get_or_create_inventory(
            parsed, defaults={"amount": theoretical_amount, "is_finalized": True}
        )
        if created:
            return 0, 1

        if inventory.is_finalized:
            # A closed day stays closed: re-finalizing must not re-derive the
            # row's correction behind the office's back.
            raise _InventoryAlreadyCounted(
                "Inventory entry is already finalized — left unchanged."
            )
        if inventory.counted_amount is None:
            # Finalizing a row nobody counted records the stock it reports as
            # the count, so the entry is finalized WITH a count rather than as
            # a permanent blank. This saves the row.
            _stamp_finalized_count(inventory, parsed)
        else:
            inventory.is_finalized = True
            inventory.save()
        return 1, 0

    updated, created = _process_grouped_stock_with_theoretical(
        grouped, errors, process_item=_process
    )
    return _build_bulk_inventory_response(updated, created, errors)


@extend_schema(
    summary="Bulk set inventory to expected values",
    description="""
    Record theoretical_current_stock as the physical count for multiple
    INVENTORY entries — including a negative one, which is what an
    over-allocated article really holds. An entry that already carries a count,
    or is finalized, is left untouched and reported under ``errors`` for that
    id.
    An id in a week the stock count page shows read-only is left untouched and
    reported under ``errors`` with the code ``commissioning.past_week``.
    """,
    request=BulkIdsRequestSerializer,
    responses=BULK_INVENTORY_RESPONSE,
)
@api_view(["POST"])
@permission_classes([IsStaff])
@transaction.atomic
def bulk_set_as_expected_current_stock(request: Request) -> Response:
    """Record theoretical_current_stock as the count where none was taken yet."""
    composite_ids = parse_bulk_ids(request)
    _pre_acquire_entity_locks(composite_ids)

    grouped, errors = _group_composite_ids(composite_ids)

    def _process(parsed: dict, theoretical_amount) -> tuple[int, int]:
        # The theoretical value is recorded as it stands, negative included: an
        # over-allocated article genuinely holds less than nothing, and lifting
        # it to 0 would write a count nobody took and force the ledger to zero.
        inventory, created = get_or_create_inventory(
            parsed, defaults={"amount": theoretical_amount}
        )
        if created:
            return 0, 1

        # "Not counted yet" is ``counted_amount IS NULL`` — ``amount`` is the
        # correction delta and is never NULL, so keying on it skipped every
        # existing row. Confirm the theoretical amount as this row's count.
        _refuse_recount(inventory)
        _record_counted_amount(inventory, parsed, theoretical_amount)
        return 1, 0

    updated, created = _process_grouped_stock_with_theoretical(
        grouped, errors, process_item=_process
    )
    return _build_bulk_inventory_response(updated, created, errors)


@extend_schema(
    summary="Bulk set inventory to zero",
    description="""
    Record a physical count of 0 for multiple INVENTORY entries — the item was
    looked for and none was there. An entry that already carries a count, or is
    finalized, is left untouched and reported under ``errors`` for that id.
    An id in a week the stock count page shows read-only is left untouched and
    reported under ``errors`` with the code ``commissioning.past_week``.
    """,
    request=BulkIdsRequestSerializer,
    responses=BULK_INVENTORY_RESPONSE,
)
@api_view(["POST"])
@permission_classes([IsStaff])
@transaction.atomic
def bulk_set_to_zero_current_stock(request: Request) -> Response:
    """Record a count of 0 for entries where no count was taken yet."""
    composite_ids = parse_bulk_ids(request)
    _pre_acquire_entity_locks(composite_ids)

    updated_count = 0
    created_count = 0
    errors: list[dict[str, str]] = []

    for composite_id in composite_ids:
        try:
            parsed = writable_composite_id(composite_id)
            # Per-item savepoint: a DB error rolls back only this item and keeps
            # the connection usable, instead of poisoning the view's outer atomic
            # and 500-ing the whole batch on one bad row.
            with transaction.atomic():
                inventory, created = get_or_create_inventory(
                    parsed, defaults={"amount": 0}
                )

                if created:
                    created_count += 1
                else:
                    # "Set to zero" is a count of 0 on a row nobody has counted
                    # yet ("not counted yet" is ``counted_amount IS NULL``, not
                    # ``amount``, which is the never-NULL correction delta). The
                    # delta 0 − balance_before is derived in the helper.
                    _refuse_recount(inventory)
                    _record_counted_amount(inventory, parsed, Decimal("0"))
                    updated_count += 1

        except PastWeekError as exc:
            errors.append(_past_week_error(composite_id, exc))
        except _InventoryAlreadyCounted as exc:
            # Ahead of the ValueError clause below, which would label this a
            # malformed composite id.
            errors.append({"id": composite_id, "error": str(exc)})
        except (ValueError, CompositeIdInvalid) as exc:
            errors.append({"id": composite_id, "error": f"Invalid composite ID: {exc}"})
        except (
            DatabaseError,
            DjangoValidationError,
            DRFValidationError,
        ) as exc:
            # Per-item failure collection inside a bulk operation.
            errors.append({"id": composite_id, "error": str(exc)})

    return _build_bulk_inventory_response(updated_count, created_count, errors)
