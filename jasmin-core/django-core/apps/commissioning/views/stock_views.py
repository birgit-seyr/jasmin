from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from datetime import time as dt_time
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authz.permissions import APIViewRolePermissionsMixin, IsStaff
from apps.shared.request_utils import body
from core.serializers import ErrorResponseSerializer

from ..errors import (
    InventoryEntryFinalized,
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
    InventoryEntrySerializer,
    InventoryMetadataSerializer,
    StockComparisonSerializer,
    StorageLoggingEntrySerializer,
)
from ..services import SnapshotService, StockService
from ..services.inventory_counts import inventory_datetime, is_inventory_race
from ..utils import (
    build_composite_id,
)
from ..utils.lookup import get_or_404
from ..utils.query_params import validate_query_params
from ..utils.stock_count_input import parse_counted_amount, writable_composite_id

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

#: How far back the storage ledger reaches when the caller sends no start_date.
_LEDGER_DEFAULT_WINDOW = timedelta(weeks=2)


def _validated_inventory_metadata(request: Request) -> dict:
    """Return the validated flag/note fields present in the PATCH body."""
    serializer = InventoryMetadataSerializer(data=body(request))
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


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
            str(share_article.id): share_article
            for share_article in ShareArticle.objects.filter(id__in=share_article_ids)
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
            409: ErrorResponseSerializer,
        },
    )
    @transaction.atomic
    def patch(self, request: Request, composite_id: str) -> Response:
        parsed = writable_composite_id(composite_id)

        metadata = _validated_inventory_metadata(request)
        amount = parse_counted_amount(request)

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
        inventory_date = inventory_datetime(
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
        # baseline without rebuilding it.

        if not existing:
            # A metadata-only PATCH (no ``amount``) must NOT write a zeroing
            # correction against the theoretical balance (``0 − running_balance``,
            # an INVENTORY delta that cancels the theoretical stock to 0). It
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
                # Savepoint so a lost race (one_inventory_per_entity_day)
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
                        for_shares=metadata.get("for_shares", True),
                        for_resellers=metadata.get("for_resellers", False),
                        for_markets=metadata.get("for_markets", False),
                        washed=metadata.get("washed", False),
                        cleaned=metadata.get("cleaned", False),
                        note=metadata.get("note", ""),
                    )
            except (IntegrityError, DjangoValidationError) as exc:
                # A concurrent writer created this entity-day's INVENTORY
                # between the ``select_for_update().first()`` miss above and this
                # INSERT. Re-fetch the winner and fall through to the update
                # branch below — converging to an update (like the bulk path's
                # ``get_or_create_inventory``) instead of a bare 409 that would
                # discard the office's count.
                if not is_inventory_race(exc):
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
            # A finalized count is what the ledger builds on, so it stays put
            # until the entry is unfinalized; the flags and the note describe
            # the same count and remain editable. The stock grid echoes the
            # whole row back on every save, so only an ``amount`` that differs
            # from the stored count is a recount.
            if (
                existing.is_finalized
                and amount is not None
                and amount != existing.counted_amount
            ):
                raise InventoryEntryFinalized(
                    "Inventory entry is finalized — unfinalize it before "
                    "changing the count."
                )
            updated = _update_inventory_fields(existing, metadata)

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
                old_correction = existing.amount
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
        # ``counted_amount = None`` and must report no
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
            409: ErrorResponseSerializer,
        },
    )
    @transaction.atomic
    def delete(self, request: Request, composite_id: str) -> Response:
        parsed = writable_composite_id(composite_id)

        inventory_date = inventory_datetime(
            parsed["year"], parsed["delivery_week"], parsed["day_number"]
        )
        inventory_start = inventory_date.replace(hour=0, minute=0, second=0)
        inventory_end = inventory_date.replace(hour=23, minute=59, second=59)

        entries = MovementShareArticle.objects.filter(
            movement_type=MovementTypeOptions.INVENTORY,
            share_article_id=parsed["share_article_id"],
            unit=parsed["unit"],
            size=parsed["size"],
            storage_id=parsed["storage_id"],
            date__gte=inventory_start,
            date__lte=inventory_end,
        )

        if any(entry.is_finalized for entry in entries):
            raise InventoryEntryFinalized(
                "Inventory entry is finalized — unfinalize it before deleting it."
            )

        deleted_count, _ = entries.delete()

        if deleted_count == 0:
            raise InventoryEntryNotFound("Inventory entry not found")

        # Clean up snapshots so future balance calculations are not
        # poisoned by stale baselines from the deleted INVENTORY.
        SnapshotService.delete_snapshots_for_entity(
            parsed["share_article_id"],
            parsed["unit"],
            parsed["size"],
            parsed["storage_id"],
            date_from=inventory_start,
            date_to=inventory_end,
        )

        # Cascade: recompute future INVENTORY deltas and snapshots
        SnapshotService.cascade_future_inventories(
            parsed["share_article_id"],
            parsed["unit"],
            parsed["size"],
            parsed["storage_id"],
            after_date=inventory_start,
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


def _update_inventory_fields(inventory: MovementShareArticle, data: dict) -> bool:
    """Update inventory movement fields from validated data. Returns True if
    changed."""
    updated = False
    for field in _UPDATABLE_INVENTORY_FIELDS:
        if field in data:
            setattr(inventory, field, data[field])
            updated = True
    return updated


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
            catalogue_param(
                "start_date",
                required=False,
                description=(
                    "Inclusive range start (YYYY-MM-DD). Omitted, the ledger "
                    f"starts {_LEDGER_DEFAULT_WINDOW.days // 7} weeks ago."
                ),
            ),
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

        if start_date is None:
            start_date = timezone.now() - _LEDGER_DEFAULT_WINDOW
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
        start_date: datetime,
        end_date: datetime | None,
    ) -> list[dict]:
        events: list[dict] = []
        storage_name = storage.name

        # All movements (including INVENTORY) come from a single table
        movement_qs = MovementShareArticle.objects.filter(
            storage=storage,
        ).select_related("share_article")

        if share_article_id:
            movement_qs = movement_qs.filter(share_article_id=share_article_id)
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
                    "amount": movement.amount,
                    "unit": movement.unit,
                    "size": movement.size,
                    "year": year,
                    "delivery_week": week,
                    "day_number": day_number,
                    "storage_name": storage_name,
                    "note": movement.note,
                    "cultivation_origin": movement.cultivation_origin,
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
