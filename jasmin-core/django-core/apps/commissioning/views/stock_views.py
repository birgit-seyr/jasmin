from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from datetime import time as dt_time
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import QuerySet  # noqa: F401  used in type hints
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authz.permissions import APIViewRolePermissionsMixin, IsStaff
from core.serializers import ErrorResponseSerializer

from ..errors import (
    CompositeIdInvalid,
    InventoryEntryNotFound,
    ShareArticleNotFound,
    StorageNotFound,
)
from ..models import MovementShareArticle, ShareArticle, Storage
from ..models.choices import MovementTypeOptions
from ..schemas import (
    catalogue_param,
    get_day_number_parameter,
    get_delivery_week_parameter,
    get_share_article_parameter,
    get_storage_parameter,
    get_year_parameter,
)
from ..serializers import (
    BulkIdsRequestSerializer,
    InventoryEntrySerializer,
    StockComparisonSerializer,
    StorageLoggingEntrySerializer,
)
from ..services import CurrentBalanceService, SnapshotService, StockService
from ..utils import (
    build_composite_id,
    parse_composite_id,
)
from ..utils.iso_week_utils import week_day_to_date
from ..utils.lookup import get_or_404
from ..utils.query_params import validate_query_params
from ..utils.validation_utils import parse_bulk_ids


def _ywd_to_datetime(year: int, delivery_week: int, day_number: int | None) -> datetime:
    """Convert (year, week, day_number-index) to a tz-aware datetime at 23:00.

    INVENTORY movements use 23:00 so they sort after all operational
    movements (harvests, allocations, etc.) which are recorded at noon.
    """
    day_index = day_number if day_number is not None else 0
    cal_date = week_day_to_date(year, delivery_week, day_index)
    return timezone.make_aware(datetime.combine(cal_date, dt_time(23, 0, 0)))


# Fields that can be updated via PATCH on INVENTORY movements
_UPDATABLE_INVENTORY_FIELDS = frozenset(
    {
        "for_shares",
        "for_resellers",
        "for_markets",
        "washed",
        "cleaned",
        "note",
    }
)


class CurrentStockComparisonView(APIViewRolePermissionsMixin, APIView):
    read_permission = IsStaff
    write_permission = IsStaff
    """
    API endpoints for managing inventory counts (INVENTORY movements) with composite IDs.

    Supports:
    - GET: Retrieve theoretical vs actual stock comparison
    - PATCH: Update or create a CurrentStock entry
    - DELETE: Remove a CurrentStock entry
    """

    @extend_schema(
        summary="Get current stock comparison",
        description="""
        Compare theoretical stock (calculated from movements) with actual stock (from CurrentStock entries).
        Filters out entries where both theoretical and actual stock are zero/null.
        """,
        parameters=[
            get_year_parameter(),
            get_delivery_week_parameter(),
            get_day_number_parameter(),
            get_storage_parameter(required=False),
        ],
        responses={
            200: StockComparisonSerializer(many=True),
            400: ErrorResponseSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        params = validate_query_params(
            request,
            required=["year", "delivery_week", "day_number"],
            optional=["storage"],
        )
        year = params["year"]
        delivery_week = params["delivery_week"]
        day_number = params["day_number"]
        storage: str | None = params["storage"]

        stock_map = StockService.get_theoretical_current_stock(
            year, delivery_week, day_number, storage
        )
        share_article_ids = {key[0] for key in stock_map}
        share_articles = {
            str(sa.id): sa
            for sa in ShareArticle.objects.filter(id__in=share_article_ids)
        }

        results: list[dict] = []
        for (share_article_id, unit, size, storage_id), stock_data in stock_map.items():
            theoretical_stock = stock_data.get("theoretical_current_stock")
            current_amount = stock_data.get("current_stock_amount")

            if _is_empty_stock(theoretical_stock, current_amount):
                continue

            share_article = share_articles.get(str(share_article_id))
            if not share_article:
                continue

            composite_id = build_composite_id(
                share_article_id,
                unit,
                size,
                storage_id,
                year,
                delivery_week,
                day_number,
            )

            results.append(
                {
                    "id": composite_id,
                    "share_article": share_article_id,
                    "share_article_name": share_article.name,
                    "unit": unit,
                    "size": size,
                    "storage_id": storage_id,
                    "theoretical_current_stock": theoretical_stock,
                    "amount": current_amount,
                    "is_finalized": stock_data["is_finalized"],
                    "washed": stock_data["washed"],
                    "cleaned": stock_data["cleaned"],
                    "for_shares": stock_data["for_shares"],
                    "for_resellers": stock_data["for_resellers"],
                    "for_markets": stock_data["for_markets"],
                    "note": stock_data.get("note", ""),
                }
            )

        results.sort(key=lambda x: x["share_article_name"])
        return Response(results)

    @extend_schema(
        summary="Update or create inventory count",
        description="""
        Partially update an existing INVENTORY movement or create a new one.
        Uses a composite ID format: share_article_id_unit_size_storage_id_year_week_day

        ``composite_id`` is the PATH parameter (auto-declared by
        spectacular) — declaring it here as a query param would add a
        phantom duplicate the client must fabricate.
        """,
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "nullable": True},
                    "for_shares": {"type": "boolean"},
                    "for_resellers": {"type": "boolean"},
                    "for_markets": {"type": "boolean"},
                    "washed": {"type": "boolean"},
                    "cleaned": {"type": "boolean"},
                    "note": {"type": "string", "nullable": True},
                },
            }
        },
        responses={
            200: InventoryEntrySerializer,
            201: InventoryEntrySerializer,
            400: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    @transaction.atomic
    def patch(self, request: Request, composite_id: str) -> Response:
        from ..errors import CommissioningError

        # parse_composite_id raises CompositeIdInvalid (canonical 400,
        # code="stock.invalid_composite_id") — let it propagate, no re-wrap.
        parsed = parse_composite_id(composite_id)

        amount = request.data.get("amount")
        if amount is not None:
            try:
                amount = Decimal(str(amount))
            except (ValueError, TypeError, InvalidOperation) as exc:
                raise CommissioningError(
                    "Amount must be a number",
                    field="amount",
                    code="stock.amount_not_number",
                ) from exc
            if amount < 0:
                raise CommissioningError(
                    "Amount must be non-negative",
                    field="amount",
                    code="stock.amount_negative",
                )

        share_article = get_or_404(
            ShareArticle,
            parsed["share_article_id"],
            "Share article",
            error_cls=ShareArticleNotFound,
        )

        storage = None
        if parsed["storage_id"]:
            storage = get_or_404(
                Storage, parsed["storage_id"], "Storage", error_cls=StorageNotFound
            )

        # Find existing INVENTORY movement for this entity on this day_number
        inventory_date = _ywd_to_datetime(
            parsed["year"], parsed["delivery_week"], parsed["day_number"]
        )
        inventory_date_start = inventory_date.replace(hour=0, minute=0, second=0)
        inventory_date_end = inventory_date.replace(hour=23, minute=59, second=59)

        existing = (
            MovementShareArticle.objects.select_for_update()
            .filter(
                movement_type=MovementTypeOptions.INVENTORY,
                share_article=share_article,
                unit=parsed["unit"],
                size=parsed["size"],
                storage=storage,
                date__gte=inventory_date_start,
                date__lte=inventory_date_end,
            )
            .order_by("-date")
            .first()
        )

        # NOTE: snapshot invalidation happens INSIDE the mutation branches below
        # (only when something actually changes) — a no-op PATCH (existing row,
        # no amount + no updatable field) must NOT destroy the day's snapshot
        # baseline without rebuilding it (MOV-7).

        if not existing:
            # A metadata-only PATCH (no ``amount``) must NOT write a zeroing
            # correction against the theoretical balance (goods-flow audit #2):
            # with ``amount`` absent the old code computed ``0 − running_balance``,
            # an INVENTORY delta that cancelled the theoretical stock to 0. It
            # only toggles flags/note, so record a ZERO-delta row with
            # ``counted_amount = None`` ("not counted yet") — the balance is
            # preserved and the read path / cascade treat the row as uncounted.
            # A supplied ``amount`` still nets against the running balance.
            if amount is None:
                correction = Decimal("0")
                counted = None
            else:
                running_balance = SnapshotService.compute_balance(
                    str(share_article.id),
                    parsed["unit"],
                    parsed["size"],
                    str(storage.id) if storage else None,
                    up_to=inventory_date_end,
                )
                # Decimal arithmetic so ``correction`` lands in the
                # DecimalField without binary-fp drift.
                correction = amount - running_balance
                counted = amount

            try:
                # Savepoint so a lost race (MOV-6: one_inventory_per_entity_day)
                # rolls back ONLY this INSERT, not the whole PATCH transaction.
                with transaction.atomic():
                    inventory = MovementShareArticle.objects.create(
                        date=inventory_date,
                        movement_type=MovementTypeOptions.INVENTORY,
                        share_article=share_article,
                        unit=parsed["unit"],
                        size=parsed["size"],
                        storage=storage,
                        amount=correction,
                        counted_amount=counted,
                        for_shares=request.data.get("for_shares", True),
                        for_resellers=request.data.get("for_resellers", False),
                        for_markets=request.data.get("for_markets", False),
                        washed=request.data.get("washed", False),
                        cleaned=request.data.get("cleaned", False),
                        note=request.data.get("note", ""),
                    )
            except (IntegrityError, DjangoValidationError) as exc:
                # TXN-4: a concurrent writer created this entity-day's INVENTORY
                # between the ``select_for_update().first()`` miss above and this
                # INSERT. Re-fetch the winner and fall through to the update
                # branch below — converging to an update (like the bulk path's
                # ``_get_or_create_inventory``) instead of a bare 409 that would
                # discard the office's count.
                if not _is_inventory_race(exc):
                    raise
                existing = (
                    MovementShareArticle.objects.select_for_update()
                    .filter(
                        movement_type=MovementTypeOptions.INVENTORY,
                        share_article=share_article,
                        unit=parsed["unit"],
                        size=parsed["size"],
                        storage=storage,
                        date__gte=inventory_date_start,
                        date__lte=inventory_date_end,
                    )
                    .order_by("-date")
                    .first()
                )
                if existing is None:
                    raise
            else:
                # New INVENTORY row → invalidate any stale snapshot baseline for
                # the day, rebuild it, and cascade future INVENTORY deltas.
                SnapshotService.rebuild_entity_day(
                    str(share_article.id),
                    parsed["unit"],
                    parsed["size"],
                    str(storage.id) if storage else None,
                    day_start=inventory_date_start,
                    day_end=inventory_date_end,
                    snapshot_date=inventory_date,
                )
                created = True

        if existing:
            updated = _update_inventory_fields(existing, request.data)

            # Recalculate correction delta when counted amount changes
            if amount is not None:
                running_balance = SnapshotService.compute_balance(
                    str(share_article.id),
                    parsed["unit"],
                    parsed["size"],
                    str(storage.id) if storage else None,
                    up_to=inventory_date_end,
                )
                # running_balance includes the old correction; subtract it to
                # get the balance *before* this INVENTORY movement.
                # All Decimal so the result stored back to ``DecimalField``
                # carries no binary-fp drift.
                old_correction = existing.amount or Decimal("0")
                balance_before = running_balance - old_correction
                existing.amount = amount - balance_before
                existing.counted_amount = amount
                updated = True

            if updated:
                existing.save()
                # Invalidate the day's stale snapshot baseline, rebuild it, and
                # cascade — only now that the row actually changed.
                SnapshotService.rebuild_entity_day(
                    str(share_article.id),
                    parsed["unit"],
                    parsed["size"],
                    str(storage.id) if storage else None,
                    day_start=inventory_date_start,
                    day_end=inventory_date_end,
                    snapshot_date=inventory_date,
                )
            inventory = existing
            created = False

        # Compute the absolute counted value for the response.
        # amount is the user-supplied absolute value; when absent, derive it from
        # the running balance (which includes the stored correction delta) — but
        # ONLY for a genuinely counted row. A metadata-only row has
        # ``counted_amount = None`` (goods-flow audit #2) and must report no
        # counted value, not a phantom count equal to the theoretical balance.
        if amount is not None:
            response_amount = amount
        elif inventory.counted_amount is not None:
            response_balance = SnapshotService.compute_balance(
                str(share_article.id),
                parsed["unit"],
                parsed["size"],
                str(storage.id) if storage else None,
                up_to=inventory_date_end,
            )
            response_amount = float(response_balance)
        else:
            response_amount = None

        return Response(
            {
                "id": composite_id,
                "share_article": parsed["share_article_id"],
                "share_article_name": share_article.name,
                "unit": parsed["unit"],
                "size": parsed["size"],
                "storage_id": parsed["storage_id"],
                "amount": response_amount,
                "for_shares": inventory.for_shares,
                "for_resellers": inventory.for_resellers,
                "for_markets": inventory.for_markets,
                "washed": inventory.washed,
                "cleaned": inventory.cleaned,
                "note": inventory.note,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(
        summary="Delete inventory count entry",
        description=(
            "Delete an INVENTORY movement by its composite ID "
            "(path parameter, auto-declared)."
        ),
        responses={
            204: OpenApiResponse(description="Inventory entry deleted successfully"),
            400: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    @transaction.atomic
    def delete(self, request: Request, composite_id: str) -> Response:
        # parse_composite_id raises CompositeIdInvalid (canonical 400,
        # code="stock.invalid_composite_id") — let it propagate, no re-wrap.
        parsed = parse_composite_id(composite_id)

        inv_date = _ywd_to_datetime(
            parsed["year"], parsed["delivery_week"], parsed["day_number"]
        )
        inv_start = inv_date.replace(hour=0, minute=0, second=0)
        inv_end = inv_date.replace(hour=23, minute=59, second=59)

        deleted_count, _ = MovementShareArticle.objects.filter(
            movement_type=MovementTypeOptions.INVENTORY,
            share_article_id=parsed["share_article_id"],
            unit=parsed["unit"],
            size=parsed["size"],
            storage_id=parsed["storage_id"],
            date__gte=inv_start,
            date__lte=inv_end,
        ).delete()

        if deleted_count == 0:
            raise InventoryEntryNotFound("Inventory entry not found")

        # Clean up snapshots so future balance calculations are not
        # poisoned by stale baselines from the deleted INVENTORY.
        SnapshotService.delete_snapshots_for_entity(
            parsed["share_article_id"],
            parsed["unit"],
            parsed["size"],
            parsed["storage_id"],
            date_from=inv_start,
            date_to=inv_end,
        )

        # Cascade: recompute future INVENTORY deltas and snapshots
        SnapshotService.cascade_future_inventories(
            parsed["share_article_id"],
            parsed["unit"],
            parsed["size"],
            parsed["storage_id"],
            after_date=inv_start,
        )

        return Response(status=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _is_empty_stock(theoretical: float | None, current: float | None) -> bool:
    """Check if both stock values are empty (None or 0)."""
    return (theoretical is None or theoretical == 0) and (
        current is None or current == 0
    )


def _is_inventory_race(exc: IntegrityError | DjangoValidationError) -> bool:
    """True only for the ``one_inventory_per_entity_day`` unique violation — a
    concurrent writer created this entity-day's INVENTORY row first (a lost MOV-6
    race that CONVERGES to an update).

    The race surfaces as EITHER exception type: ``MovementShareArticle.save()``
    runs ``full_clean()`` → ``validate_constraints()``, so when the winner is
    already committed and visible to the pre-INSERT SELECT it raises a Django
    ``ValidationError`` (message carries the constraint name); when the winner
    commits between that validation and the INSERT it's a DB ``IntegrityError``.
    Any OTHER error (an FK violation from a stale composite id, a genuine
    ``clean()`` failure) must propagate, not be swallowed."""
    cause = getattr(exc, "__cause__", None)
    constraint_name = getattr(getattr(cause, "diag", None), "constraint_name", "") or ""
    return (
        constraint_name.endswith("one_inventory_per_entity_day")
        or "one_inventory_per_entity_day" in str(exc).lower()
    )


def _update_inventory_fields(inventory: MovementShareArticle, data: dict) -> bool:
    """Update inventory movement fields from request data. Returns True if changed."""
    updated = False
    for field in _UPDATABLE_INVENTORY_FIELDS:
        if field in data:
            setattr(inventory, field, data[field])
            updated = True
    return updated


def _group_composite_ids(
    composite_ids: list[str],
) -> tuple[dict[tuple, list[tuple[str, dict]]], list[dict[str, str]]]:
    """
    Parse and group composite IDs by (year, week, day_number, storage).

    Returns (grouped_ids, errors).
    """
    grouped: dict[tuple, list[tuple[str, dict]]] = defaultdict(list)
    errors: list[dict[str, str]] = []

    for composite_id in composite_ids:
        try:
            parsed = parse_composite_id(composite_id)
            group_key = (
                parsed["year"],
                parsed["delivery_week"],
                parsed["day_number"],
                parsed["storage_id"],
            )
            grouped[group_key].append((composite_id, parsed))
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
    process_item: callable,
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
            TypeError,
            KeyError,
            AttributeError,
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
                TypeError,
                KeyError,
                AttributeError,
            ) as exc:
                # Per-item failure collection inside a bulk operation.
                errors.append({"id": composite_id, "error": str(exc)})

    return updated_count, created_count


def _get_or_create_inventory(
    parsed: dict, defaults: dict
) -> tuple[MovementShareArticle, bool]:
    """Find an existing INVENTORY movement for the day_number or create one."""
    inv_date = _ywd_to_datetime(
        parsed["year"], parsed["delivery_week"], parsed["day_number"]
    )
    inv_start = inv_date.replace(hour=0, minute=0, second=0)
    inv_end = inv_date.replace(hour=23, minute=59, second=59)

    existing = (
        MovementShareArticle.objects.select_for_update()
        .filter(
            movement_type=MovementTypeOptions.INVENTORY,
            share_article_id=parsed["share_article_id"],
            unit=parsed["unit"],
            size=parsed["size"],
            storage_id=parsed["storage_id"],
            date__gte=inv_start,
            date__lte=inv_end,
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
        date_from=inv_start,
        date_to=inv_end,
    )

    # Compute correction delta
    running_balance = SnapshotService.compute_balance(
        str(parsed["share_article_id"]),
        parsed["unit"],
        parsed["size"],
        storage_str,
        up_to=inv_end,
    )
    # Defensive coercion: callers may pass int / float / str — go through
    # ``str()`` to absorb any float input without binary-fp drift.
    raw_amount = defaults.get("amount", 0) or 0
    amount = raw_amount if isinstance(raw_amount, Decimal) else Decimal(str(raw_amount))
    correction = amount - running_balance

    try:
        # Savepoint so a lost race (MOV-6: one_inventory_per_entity_day) rolls
        # back ONLY this INSERT, not the caller's whole bulk transaction.
        with transaction.atomic():
            inventory = MovementShareArticle.objects.create(
                date=inv_date,
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
        # lost race (that returned None → a cryptic AttributeError downstream).
        # Re-raise anything else.
        if not _is_inventory_race(exc):
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
                date__gte=inv_start,
                date__lte=inv_end,
            )
            .order_by("-date")
            .first()
        )
        if existing is None:
            # The unique violation fired but no row is visible on re-fetch —
            # don't return None (it surfaces as an opaque AttributeError per
            # item). Surface the original error instead.
            raise
        return existing, False

    SnapshotService.create_snapshot_for_entity(
        str(parsed["share_article_id"]),
        parsed["unit"],
        parsed["size"],
        storage_str,
        snapshot_date=inv_date,
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
        after_date=inv_date,
    )

    return inventory, True


def _build_bulk_inventory_response(
    updated: int, created: int, errors: list[dict[str, str]]
) -> Response:
    # REF-1: 207 on partial failure (some items errored), 200 only when every
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
    """TXN-1: take every entity's ``current_balance`` advisory lock up front, in
    one canonical (sorted) order, before the per-item processing loop.

    Each bulk view otherwise acquires the per-entity locks incrementally in
    request-body order (via ``_get_or_create_inventory`` → cascade →
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
            parsed = parse_composite_id(composite_id)
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
    Sets amount to theoretical_current_stock ONLY if amount is null/None.
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
        clamped_amount = max(theoretical_amount, 0)
        inventory, created = _get_or_create_inventory(
            parsed, defaults={"amount": clamped_amount, "is_finalized": True}
        )
        if not created:
            if inventory.amount is None:
                # "Assume counted == theoretical" means zero correction delta
                inventory.amount = 0
            inventory.is_finalized = True
            inventory.save()
            return 1, 0
        return 0, 1

    updated, created = _process_grouped_stock_with_theoretical(
        grouped, errors, process_item=_process
    )
    return _build_bulk_inventory_response(updated, created, errors)


@extend_schema(
    summary="Bulk set inventory to expected values",
    description="""
    Set amount to theoretical_current_stock for multiple INVENTORY entries.
    ONLY updates entries where amount is null/None.
    """,
    request=BulkIdsRequestSerializer,
    responses=BULK_INVENTORY_RESPONSE,
)
@api_view(["POST"])
@permission_classes([IsStaff])
@transaction.atomic
def bulk_set_as_expected_current_stock(request: Request) -> Response:
    """Set amount to theoretical_current_stock where amount is null/None."""
    composite_ids = parse_bulk_ids(request)
    _pre_acquire_entity_locks(composite_ids)

    grouped, errors = _group_composite_ids(composite_ids)

    def _process(parsed: dict, theoretical_amount) -> tuple[int, int]:
        clamped_amount = max(theoretical_amount, 0)
        inventory, created = _get_or_create_inventory(
            parsed, defaults={"amount": clamped_amount}
        )
        if not created:
            if inventory.amount is None:
                # "Set as expected" means counted == theoretical → zero delta
                inventory.amount = 0
                inventory.save()
                return 1, 0
            return 0, 0
        return 0, 1

    updated, created = _process_grouped_stock_with_theoretical(
        grouped, errors, process_item=_process
    )
    return _build_bulk_inventory_response(updated, created, errors)


@extend_schema(
    summary="Bulk set inventory to zero",
    description="""
    Set amount to 0 for multiple INVENTORY entries.
    ONLY creates entries where none exist yet.
    Useful for marking items as counted but found to be zero.
    """,
    request=BulkIdsRequestSerializer,
    responses=BULK_INVENTORY_RESPONSE,
)
@api_view(["POST"])
@permission_classes([IsStaff])
@transaction.atomic
def bulk_set_to_zero_current_stock(request: Request) -> Response:
    """Set amount to 0 for entries where amount is null/None."""
    composite_ids = parse_bulk_ids(request)
    _pre_acquire_entity_locks(composite_ids)

    updated_count = 0
    created_count = 0
    errors: list[dict[str, str]] = []

    for composite_id in composite_ids:
        try:
            parsed = parse_composite_id(composite_id)
            # Per-item savepoint: a DB error rolls back only this item and keeps
            # the connection usable, instead of poisoning the view's outer atomic
            # and 500-ing the whole batch on one bad row.
            with transaction.atomic():
                inventory, created = _get_or_create_inventory(
                    parsed, defaults={"amount": 0}
                )

                if not created:
                    if inventory.amount is None:
                        # "Set to zero" means counted = 0. Compute running
                        # balance to derive the correction delta:
                        # 0 − running_balance.
                        inv_date = _ywd_to_datetime(
                            parsed["year"],
                            parsed["delivery_week"],
                            parsed["day_number"],
                        )
                        inv_end = inv_date.replace(hour=23, minute=59, second=59)
                        running_balance = SnapshotService.compute_balance(
                            str(parsed["share_article_id"]),
                            parsed["unit"],
                            parsed["size"],
                            str(parsed["storage_id"]) if parsed["storage_id"] else None,
                            up_to=inv_end,
                        )
                        # ``running_balance`` is already Decimal — keep the
                        # subtraction Decimal so ``inventory.amount`` lands in
                        # the DecimalField without binary-fp drift.
                        inventory.amount = Decimal("0") - running_balance
                        inventory.save()
                        updated_count += 1
                else:
                    created_count += 1

        except (ValueError, CompositeIdInvalid) as exc:
            errors.append({"id": composite_id, "error": f"Invalid composite ID: {exc}"})
        except (
            DatabaseError,
            DjangoValidationError,
            DRFValidationError,
            TypeError,
            KeyError,
            AttributeError,
        ) as exc:
            # Per-item failure collection inside a bulk operation.
            errors.append({"id": composite_id, "error": str(exc)})

    return _build_bulk_inventory_response(updated_count, created_count, errors)


class StorageLoggingView(APIViewRolePermissionsMixin, APIView):
    read_permission = IsStaff
    write_permission = IsStaff
    """
    Stock ledger view for a specific storage location.

    Shows all movements and physical stock counts chronologically, with a
    running balance per (share_article, unit, size) group computed from
    movements only.  Physical counts (INVENTORY) are displayed alongside
    the running balance so discrepancies are immediately visible.
    """

    @extend_schema(
        summary="Get storage stock ledger",
        description="""
        Retrieve a chronological ledger of all stock movements and physical
        counts for a specific storage location.

        Each row includes:
        - **amount**: the movement delta (+harvest, −allocation) or the
          correction delta for INVENTORY rows.
        - **running_balance**: cumulative sum of movement amounts for the
          same (share_article, unit, size) group up to this point.

        Returned newest-first.
        """,
        parameters=[
            get_storage_parameter(required=True),
            get_share_article_parameter(required=False),
            catalogue_param("start_date", required=False),
            catalogue_param("end_date", required=False),
        ],
        responses={
            200: StorageLoggingEntrySerializer(many=True),
            400: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        params = validate_query_params(
            request,
            required=["storage"],
            optional=["share_article", "start_date", "end_date"],
        )
        storage_id: str | None = params["storage"]
        share_article_id: str | None = params["share_article"]

        storage: Storage = self._get_storage_or_error(storage_id)

        start_date, end_date = self._parse_date_filters(
            params["start_date"], params["end_date"]
        )

        # Default to three weeks ago when no start_date is provided
        if start_date is None:
            from datetime import timedelta

            start_date = timezone.now() - timedelta(weeks=2)
            start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)

        events = self._build_event_list(storage, share_article_id, start_date, end_date)
        self._compute_running_balances(events)

        events.reverse()
        return Response(events, status=status.HTTP_200_OK)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_storage_or_error(storage_id: str) -> Storage:
        return get_or_404(Storage, storage_id, "Storage", error_cls=StorageNotFound)

    @staticmethod
    def _parse_date_filters(
        start: date | None,
        end: date | None,
    ) -> tuple[datetime | None, datetime | None]:
        start_date: datetime | None = None
        end_date: datetime | None = None

        if start:
            start_date = datetime.combine(start, dt_time.min)
            if timezone.is_naive(start_date):
                start_date = timezone.make_aware(start_date)

        if end:
            end_date = datetime.combine(end, dt_time(23, 59, 59))
            if timezone.is_naive(end_date):
                end_date = timezone.make_aware(end_date)

        return start_date, end_date

    @staticmethod
    def _date_to_ywd(dt: datetime) -> tuple[int, int, int]:
        if timezone.is_aware(dt):
            dt = timezone.localtime(dt)
        iso = dt.isocalendar()
        return iso[0], iso[1], dt.weekday()

    # ------------------------------------------------------------------
    # Event list construction
    # ------------------------------------------------------------------

    def _build_event_list(
        self,
        storage: Storage,
        share_article_id: str | None,
        start_date: datetime | None,
        end_date: datetime | None,
    ) -> list[dict]:
        events: list[dict] = []
        storage_name = storage.name

        # All movements (including INVENTORY) come from a single table now
        movement_qs = MovementShareArticle.objects.filter(
            storage=storage,
        ).select_related("share_article")

        if share_article_id:
            movement_qs = movement_qs.filter(share_article_id=share_article_id)
        if start_date:
            movement_qs = movement_qs.filter(date__gte=start_date)
        if end_date:
            movement_qs = movement_qs.filter(date__lte=end_date)

        for movement in movement_qs:
            year, week, day_number = self._date_to_ywd(movement.date)
            is_inventory = movement.movement_type == MovementTypeOptions.INVENTORY
            events.append(
                {
                    "id": f"mv_{movement.id}",
                    "date": movement.date,
                    "type": movement.movement_type or "MOVEMENT",
                    "share_article": str(movement.share_article.id),
                    "share_article_name": movement.share_article.name,
                    "amount": (
                        movement.amount if movement.amount is not None else Decimal("0")
                    ),
                    "unit": movement.unit,
                    "size": movement.size,
                    "year": year,
                    "delivery_week": week,
                    "day_number": day_number,
                    "storage_name": storage_name,
                    "note": movement.note,
                    "cultivation_origin": getattr(movement, "cultivation_origin", None),
                    "washed": movement.washed if is_inventory else None,
                    "cleaned": movement.cleaned if is_inventory else None,
                    "for_shares": movement.for_shares if is_inventory else None,
                    "for_resellers": movement.for_resellers if is_inventory else None,
                    "for_markets": movement.for_markets if is_inventory else None,
                    "is_finalized": movement.is_finalized if is_inventory else None,
                }
            )

        events.sort(key=lambda x: x["date"])
        return events

    @staticmethod
    def _compute_running_balances(events: list[dict]) -> None:
        """Add ``running_balance`` to each event.

        ALL movement rows (including INVENTORY) change the balance, because
        INVENTORY amounts are stored as correction deltas.

        ``events`` must be sorted by date ascending.
        """
        # Accumulate in Decimal (amounts are DecimalField, decimal_places=3) so
        # the running balance stays exact; float() only at the per-row response
        # boundary below — mirrors StockService's Decimal-end-to-end pattern.
        balances: dict[tuple, Decimal] = defaultdict(lambda: Decimal("0"))
        for event in events:
            key = (event["share_article"], event["unit"], event["size"])
            balances[key] += event["amount"]
            event["running_balance"] = float(balances[key].quantize(Decimal("0.001")))
            event["amount"] = float(event["amount"])
