from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any, Literal, TypedDict

from django.db import transaction
from django.db.models import Q, QuerySet
from isoweek import Week

from ..constants import PURCHASE_DAY
from ..models import (
    AdditionalTheoreticalCleanAmount,
    AdditionalTheoreticalHarvest,
    AdditionalTheoreticalPurchase,
    AdditionalTheoreticalWashAmount,
    CleanAmount,
    Crate,
    Harvest,
    MovementShareArticle,
    Purchase,
    Reseller,
    ShareArticle,
    Storage,
    TheoreticalCleanAmount,
    TheoreticalHarvest,
    TheoreticalPurchase,
    TheoreticalWashAmount,
    WashAmount,
)
from ..models.choices_text import MovementTypeOptions
from ..services.documentation_service import GenericDocumentationService
from ..services.stock_service import StockService
from ..utils import (
    build_storage_fields,
    sort_share_articles,
)
from ..utils.iso_week_utils import previous_day_stock_coordinates

# Type definitions
ModelType = Literal["harvest", "purchase", "washamount", "cleanamount"]
GroupingKey = tuple[
    int, str, str | None, int | None, int | None
]  # (share_article_id, unit, size, day_number, storage_id)


class ModelManagers(TypedDict):
    theoretical: Any
    additional: Any
    actual: Any


class GroupedData(TypedDict):
    share_article_id: str | None
    share_article_name: str
    unit: str | None
    size: str | None
    theoretical_entries: list[Any]
    additional_entries: list[Any]
    actual_entries: list[Any]


class DocumentationSummaryService:
    MODEL_MAPPING = {
        "harvest": {
            "theoretical": TheoreticalHarvest,
            "additional": AdditionalTheoreticalHarvest,
            "actual": Harvest,
        },
        "purchase": {
            "theoretical": TheoreticalPurchase,
            "additional": AdditionalTheoreticalPurchase,
            "actual": Purchase,
        },
        "washamount": {
            "theoretical": TheoreticalWashAmount,
            "additional": AdditionalTheoreticalWashAmount,
            "actual": WashAmount,
        },
        "cleanamount": {
            "theoretical": TheoreticalCleanAmount,
            "additional": AdditionalTheoreticalCleanAmount,
            "actual": CleanAmount,
        },
    }

    # FK field on MovementShareArticle for each additional-theoretical model.
    _ADDITIONAL_FK_FIELD: dict[str, str] = {
        "harvest": "additional_theoretical_harvest",
        "purchase": "additional_theoretical_purchase",
        "washamount": "additional_theoretical_wash_amount",
        "cleanamount": "additional_theoretical_clean_amount",
    }
    _MOVEMENT_TYPE: dict[str, str] = {
        "harvest": MovementTypeOptions.HARVEST,
        "purchase": MovementTypeOptions.PURCHASE,
        "washamount": MovementTypeOptions.WASH,
        "cleanamount": MovementTypeOptions.CLEAN,
    }

    # HARVEST additional entries split per content source (share vs order):
    # (payload amount key, for_*_content flags). Drives both the add and update
    # upsert paths so the two never drift.
    _CONTENT_TYPE_FLAGS: list[tuple[str, dict[str, bool]]] = [
        (
            "amount_share_content",
            {"for_share_content": True, "for_order_content": False},
        ),
        (
            "amount_order_content",
            {"for_share_content": False, "for_order_content": True},
        ),
    ]

    @staticmethod
    def _get_managers(model: ModelType, is_past: bool = False) -> ModelManagers:
        """Get the appropriate managers based on model type and past flag.

        Uses ``active.for_period(is_past)`` so that:
        - ``is_past=False`` → fast, recent-only queryset (cutoff window).
        - ``is_past=True`` → full queryset including archived records.
        """
        mapping = DocumentationSummaryService.MODEL_MAPPING[model]
        return {
            "theoretical": mapping["theoretical"].active.for_period(is_past=is_past),
            "additional": mapping["additional"].active.for_period(is_past=is_past),
            "actual": mapping["actual"].active.for_period(is_past=is_past),
        }

    @staticmethod
    def _get_short_term_storage() -> Storage | None:
        """Get the short-term harvest storage."""
        return Storage.short_term_harvest()

    @staticmethod
    def _build_base_filter(
        year: int,
        delivery_week: int,
        day_number: int | None = None,
        seller: int | None = None,
        is_preparation_lists: bool = False,
    ) -> Q:
        """Build base query filter for harvest/purchase queries."""
        base_filter = Q(year=year, delivery_week=delivery_week)

        if day_number is not None:
            base_filter &= Q(day_number=day_number)

        if seller is not None:
            base_filter &= Q(seller=seller)

        if is_preparation_lists:
            short_term_storage = DocumentationSummaryService._get_short_term_storage()
            if short_term_storage:
                base_filter &= Q(storage=short_term_storage)

        return base_filter

    @staticmethod
    def _get_grouping_key(entry: Any) -> GroupingKey:
        """Create grouping key from an entry."""
        storage_id = None
        if hasattr(entry, "storage_id") and entry.storage_id:
            storage_id = entry.storage_id
        elif hasattr(entry, "storage") and entry.storage:
            storage_id = entry.storage.id
        return (
            entry.share_article.id,
            entry.unit,
            entry.size,
            entry.day_number,
            storage_id,
        )

    @staticmethod
    def _fetch_data(
        managers: ModelManagers,
        base_filter: Q,
        single_id: str | None = None,
        model: ModelType = "harvest",
    ) -> tuple[QuerySet, QuerySet, QuerySet]:
        """Fetch theoretical, additional, and actual data."""
        theoretical_manager = managers["theoretical"]
        additional_manager = managers["additional"]
        actual_manager = managers["actual"]

        # Model-specific select_related for actual data
        actual_select = ["share_article"]
        if model == "harvest":
            actual_select.append("harvesting_crate")
        elif model == "purchase":
            actual_select.extend(["seller", "seller__contact"])

        if single_id:
            try:
                actual_entry = actual_manager.get(id=single_id)
                base_filter &= Q(
                    share_article=actual_entry.share_article,
                    unit=actual_entry.unit,
                    size=actual_entry.size,
                )
                actual_data = actual_manager.filter(id=single_id).select_related(
                    *actual_select
                )
            except (
                Harvest.DoesNotExist,
                Purchase.DoesNotExist,
                WashAmount.DoesNotExist,
                CleanAmount.DoesNotExist,
            ):
                return (
                    theoretical_manager.none(),
                    additional_manager.none(),
                    actual_manager.none(),
                )
        else:
            actual_data = actual_manager.filter(base_filter).select_related(
                *actual_select
            )

        theoretical_select = ["share_article"]
        if model == "harvest":
            theoretical_select.extend(["forecast", "forecast__plot"])

        theoretical_data = theoretical_manager.filter(base_filter).select_related(
            *theoretical_select
        )
        additional_data = additional_manager.filter(base_filter).select_related(
            "share_article"
        )

        return theoretical_data, additional_data, actual_data

    @staticmethod
    def _get_theoretical_stock_map(
        model: ModelType,
        year: int,
        delivery_week: int,
        day_number: int | None,
        single_id: str | None,
        actual_manager: Any,
    ) -> dict[tuple[int, str, str | None, int | None], dict[str, Any]]:
        """Get theoretical current stock map for entities."""
        if model not in ["harvest", "purchase", "washamount"]:
            return {}

        entity_filter = None
        if single_id:
            try:
                actual_entry = actual_manager.get(id=single_id)
                entity_filter = {
                    "share_article_id": actual_entry.share_article_id,
                    "unit": actual_entry.unit,
                    "size": actual_entry.size,
                }
            except (
                Harvest.DoesNotExist,
                Purchase.DoesNotExist,
                WashAmount.DoesNotExist,
            ):
                pass

        if model == "purchase":
            # Stock from the day_number before purchases land
            year, stock_week, stock_day = previous_day_stock_coordinates(
                Week(year, delivery_week).day(PURCHASE_DAY)
            )
        elif day_number is not None:
            # Stock from the day_number before harvesting/washing
            day_number = int(day_number)
            year, stock_week, stock_day = previous_day_stock_coordinates(
                Week(year, delivery_week).day(day_number)
            )
        else:
            stock_day = day_number
            stock_week = delivery_week

        return StockService.get_theoretical_current_stock(
            year=year,
            delivery_week=stock_week,
            day_number=stock_day,
            entity_filter=entity_filter,
        )

    @staticmethod
    def _group_entries(
        theoretical_data: QuerySet,
        additional_data: QuerySet,
        actual_data: QuerySet,
    ) -> dict[GroupingKey, GroupedData]:
        """Group entries by share_article_id, unit, and size."""
        grouped_data: dict[GroupingKey, GroupedData] = defaultdict(
            lambda: {
                "share_article_id": None,
                "share_article_name": "",
                "unit": None,
                "size": None,
                "theoretical_entries": [],
                "additional_entries": [],
                "actual_entries": [],
            }
        )

        # Process theoretical data
        for entry in theoretical_data:
            key = DocumentationSummaryService._get_grouping_key(entry)
            grouped_data[key]["share_article_id"] = entry.share_article.id
            grouped_data[key]["share_article_name"] = entry.share_article.name
            grouped_data[key]["unit"] = entry.unit
            grouped_data[key]["size"] = entry.size
            grouped_data[key]["theoretical_entries"].append(entry)

        # Process additional theoretical data
        for entry in additional_data:
            key = DocumentationSummaryService._get_grouping_key(entry)
            grouped_data[key]["share_article_id"] = entry.share_article.id
            grouped_data[key]["share_article_name"] = entry.share_article.name
            grouped_data[key]["unit"] = entry.unit
            grouped_data[key]["size"] = entry.size
            grouped_data[key]["additional_entries"].append(entry)

        # Process actual data
        for entry in actual_data:
            key = DocumentationSummaryService._get_grouping_key(entry)
            grouped_data[key]["share_article_id"] = entry.share_article.id
            grouped_data[key]["share_article_name"] = entry.share_article.name
            grouped_data[key]["unit"] = entry.unit
            grouped_data[key]["size"] = entry.size
            grouped_data[key]["actual_entries"].append(entry)

        return grouped_data

    @staticmethod
    def _calculate_sums(
        theoretical_entries: list[Any],
        additional_entries: list[Any],
        model: ModelType,
    ) -> tuple[float, float, float | None, float | None, float | None, float | None]:
        """Calculate various sum totals for entries."""
        theoretical_sum = sum(entry.amount or 0 for entry in theoretical_entries)
        additional_sum = sum(entry.amount or 0 for entry in additional_entries)

        if model == "harvest":
            theoretical_sum_share = sum(
                entry.amount or 0
                for entry in theoretical_entries
                if entry.share_content is not None
            )
            theoretical_sum_order = sum(
                entry.amount or 0
                for entry in theoretical_entries
                if entry.order_content is not None
            )
            additional_sum_share = sum(
                entry.amount or 0
                for entry in additional_entries
                if entry.for_share_content
            )
            additional_sum_order = sum(
                entry.amount or 0
                for entry in additional_entries
                if entry.for_order_content
            )
            return (
                theoretical_sum,
                additional_sum,
                theoretical_sum_share,
                theoretical_sum_order,
                additional_sum_share,
                additional_sum_order,
            )

        return theoretical_sum, additional_sum, None, None, None, None

    @staticmethod
    def _get_forecast_info(
        theoretical_entries: list[Any],
    ) -> tuple[str | None, str | None, str | None]:
        """Extract forecast information from theoretical entries."""
        if not theoretical_entries:
            return None, None, None

        try:
            first_entry = theoretical_entries[0]
            return (
                first_entry.forecast.bed_number,
                first_entry.forecast.note,
                first_entry.forecast.plot.name,
            )
        except AttributeError:
            return None, None, None

    @staticmethod
    def _calculate_theoretical_stock(
        share_article_id: str,
        unit: str,
        size: str | None,
        storage_id: str | None,
        theoretical_stock_map: dict[
            tuple[str, str, str | None, str | None], dict[str, Any]
        ],
        theoretical_sum_share: float = 0,
    ) -> tuple[float, float, float]:
        """Calculate theoretical current stock for an entry.

        Returns (total, share_stock, order_stock).
        Uses for_shares / for_resellers flags from the stock entries to split.
        Falls back from current_stock_amount to theoretical_current_stock.
        Negative values are clamped to 0.
        """
        if storage_id is None:
            matching_keys = [
                key
                for key in theoretical_stock_map.keys()
                if key[0] == share_article_id and key[1] == unit and key[2] == size
            ]
        else:
            candidate = (share_article_id, unit, size, storage_id)
            matching_keys = [candidate] if candidate in theoretical_stock_map else []

        if not matching_keys:
            return 0, 0.0, 0.0

        share_stock = 0.0
        order_stock = 0.0
        theoretical_sum_share = float(theoretical_sum_share or 0)

        for key in matching_keys:
            entry = theoretical_stock_map[key]
            stock = entry.get("current_stock_amount")
            if stock is None:
                stock = entry.get("theoretical_current_stock") or 0
            stock = max(float(stock), 0.0)

            is_share = entry.get("for_shares")
            is_order = entry.get("for_resellers")

            if is_share and is_order:
                # Both flags: assign up to theoretical_sum_share to share,
                # remainder to order
                to_share = min(stock, max(theoretical_sum_share - share_stock, 0))
                share_stock += to_share
                order_stock += stock - to_share
            elif is_share:
                share_stock += stock
            elif is_order:
                order_stock += stock
            else:
                share_stock += stock

        total = share_stock + order_stock

        return total, share_stock, order_stock

    @staticmethod
    def _build_result_entry(
        entry: Any,
        model: ModelType,
        share_article_id: str,
        unit: str,
        size: str | None,
        theoretical_sum: float,
        additional_sum: float,
        theoretical_id: str | None,
        additional_id: str | None,
        forecast_info: tuple[str | None, str | None, str | None],
        theoretical_current_stock: float | None,
        harvest_sums: tuple[float, float, float, float] | None = None,
        theoretical_current_stock_share_content: float | None = None,
        theoretical_current_stock_order_content: float | None = None,
        theoretical_note: str = "",
    ) -> dict[str, Any]:
        """Build a single result entry."""
        field_prefix = model
        forecast_bed_number, forecast_note, forecast_plot_name = forecast_info

        storage_fields = {}
        if model in ["harvest", "purchase"]:
            storage_fields = build_storage_fields(entry)

        result_entry = {
            "id": entry.id,
            "share_article": share_article_id,
            "share_article_name": entry.share_article.name,
            "unit": unit,
            "size": size,
            f"{field_prefix}_amount": entry.amount,
            f"theoretical_{field_prefix}_amount": theoretical_sum,
            "theoretical_id": theoretical_id,
            "additional_id": additional_id,
            f"additional_theoretical_{field_prefix}_amount": additional_sum,
            "forecast_plot_name": forecast_plot_name,
            "forecast_bed_number": forecast_bed_number,
            "forecast_note": forecast_note,
            "theoretical_current_stock": theoretical_current_stock,
            "amount_per_pu": (
                entry.amount_per_pu if model in ["harvest", "purchase"] else None
            ),
            "harvesting_crate": (
                entry.harvesting_crate.id
                if model == "harvest" and entry.harvesting_crate
                else None
            ),
            "harvesting_crate_name": (
                entry.harvesting_crate.short_name
                if model == "harvest"
                and entry.harvesting_crate
                and hasattr(entry.harvesting_crate, "short_name")
                else (
                    entry.harvesting_crate
                    if model == "harvest" and entry.harvesting_crate
                    else None
                )
            ),
            "seller": (
                entry.seller.id if model == "purchase" and entry.seller else None
            ),
            "seller_name": (
                entry.seller.contact.name
                if model == "purchase" and entry.seller
                else None
            ),
            "price_per_unit": (
                entry.price_per_unit
                if model == "purchase" and entry.price_per_unit
                else None
            ),
            "organic_status": (entry.organic_status if model == "purchase" else None),
            **storage_fields,
            "note": theoretical_note or entry.note or "",
        }

        if model == "harvest" and harvest_sums:
            (
                theoretical_sum_share,
                theoretical_sum_order,
                additional_sum_share,
                additional_sum_order,
            ) = harvest_sums
            result_entry.update(
                {
                    f"theoretical_{field_prefix}_amount_share_content": theoretical_sum_share,
                    f"theoretical_{field_prefix}_amount_order_content": theoretical_sum_order,
                    f"additional_theoretical_{field_prefix}_amount_share_content": additional_sum_share,
                    f"additional_theoretical_{field_prefix}_amount_order_content": additional_sum_order,
                    "theoretical_current_stock_share_content": theoretical_current_stock_share_content,
                    "theoretical_current_stock_order_content": theoretical_current_stock_order_content,
                    "is_finalized": (
                        entry.is_finalized if hasattr(entry, "is_finalized") else None
                    ),
                }
            )

        return result_entry

    @staticmethod
    def get_summary(
        year: int,
        delivery_week: int,
        model: ModelType,
        day_number: int | None = None,
        is_past: bool = False,
        single_id: str | None = None,
        include_next_week: bool = False,
        seller: int | None = None,
        is_preparation_lists: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Get harvest or purchase summaries grouped by share_article_id, unit, and size.

        Args:
            year: Delivery year
            delivery_week: Delivery week number
            model: Type of data to retrieve
            day_number: Specific delivery day_number (optional)
            is_past: Whether to include past data
            single_id: Filter to single entry ID
            include_next_week: Include next week's data
            seller: Filter by seller (purchase only)
            is_preparation_lists: Filter by short-term storage

        Returns:
            List of grouped summary records
        """
        # Check for short-term storage requirement
        if (
            is_preparation_lists
            and not DocumentationSummaryService._get_short_term_storage()
        ):
            return []

        # Build base filter
        base_filter = DocumentationSummaryService._build_base_filter(
            year, delivery_week, day_number, seller, is_preparation_lists
        )

        # Get managers
        managers = DocumentationSummaryService._get_managers(model, is_past)

        # Fetch data
        (
            theoretical_data,
            additional_data,
            actual_data,
        ) = DocumentationSummaryService._fetch_data(
            managers, base_filter, single_id, model
        )

        # Check if we have any data
        if not actual_data.exists():
            return []

        # Get theoretical stock map
        theoretical_stock_map = DocumentationSummaryService._get_theoretical_stock_map(
            model, year, delivery_week, day_number, single_id, managers["actual"]
        )

        # Group entries
        grouped_data = DocumentationSummaryService._group_entries(
            theoretical_data, additional_data, actual_data
        )

        # Build result
        result = []
        for (
            share_article_id,
            unit,
            size,
            _day,
            storage_id,
        ), data in grouped_data.items():
            # Calculate sums
            (
                theoretical_sum,
                additional_sum,
                theoretical_sum_share,
                theoretical_sum_order,
                additional_sum_share,
                additional_sum_order,
            ) = DocumentationSummaryService._calculate_sums(
                data["theoretical_entries"], data["additional_entries"], model
            )

            # Get IDs and forecast info
            theoretical_id = (
                data["theoretical_entries"][0].id
                if data["theoretical_entries"]
                else None
            )
            additional_id = (
                data["additional_entries"][0].id if data["additional_entries"] else None
            )
            forecast_info = DocumentationSummaryService._get_forecast_info(
                data["theoretical_entries"]
            )

            # Get note from theoretical entries (all share the same note)
            theoretical_note = ""
            for te in data["theoretical_entries"]:
                if te.note:
                    theoretical_note = te.note
                    break
            if not theoretical_note:
                for ae in data["additional_entries"]:
                    if ae.note:
                        theoretical_note = ae.note
                        break

            (
                theoretical_current_stock,
                theoretical_current_stock_share,
                theoretical_current_stock_order,
            ) = DocumentationSummaryService._calculate_theoretical_stock(
                share_article_id,
                unit,
                size,
                storage_id,
                theoretical_stock_map,
                theoretical_sum_share=theoretical_sum_share or 0,
            )

            # Process actual entries
            for entry in data["actual_entries"]:
                harvest_sums = None
                if model == "harvest":
                    harvest_sums = (
                        theoretical_sum_share,
                        theoretical_sum_order,
                        additional_sum_share,
                        additional_sum_order,
                    )

                result_entry = DocumentationSummaryService._build_result_entry(
                    entry=entry,
                    model=model,
                    share_article_id=share_article_id,
                    unit=unit,
                    size=size,
                    theoretical_sum=theoretical_sum,
                    additional_sum=additional_sum,
                    theoretical_id=theoretical_id,
                    additional_id=additional_id,
                    forecast_info=forecast_info,
                    theoretical_current_stock=theoretical_current_stock,
                    harvest_sums=harvest_sums,
                    theoretical_current_stock_share_content=theoretical_current_stock_share,
                    theoretical_current_stock_order_content=theoretical_current_stock_order,
                    theoretical_note=theoretical_note,
                )

                result.append(result_entry)

        return sort_share_articles(result)

    @staticmethod
    @transaction.atomic
    def _bulk_set_actual(
        items: list[dict[str, Any]],
        *,
        model: type,
        amount_key: str,
        unit_key: str,
        size_key: str,
        day_number_fn: Callable[[dict[str, Any]], int | None],
    ) -> None:
        """Shared core of the bulk "set as expected" actions: upsert the actual
        Harvest/Purchase row per item and (re)create its movement.

        The theoretical objects are deliberately NOT touched. They are
        short-term-locked (``RequiresShortTermStorageMixin`` rejects any other
        storage) and the office's storage picker is UI-restricted to that one
        storage — so there is nothing to relocate. The old relocation was either
        a no-op or, if a non-short-term storage reached the service, an illegal
        write of a non-short-term theoretical (it bypassed ``full_clean`` via a
        raw ``.update()``).

        ``day_number_fn`` resolves the slot's day: harvests carry their own
        ``day_number``; purchases are always ``PURCHASE_DAY`` (matching the
        ``TheoreticalPurchase``).
        """
        if not items:
            return

        # TXN-1: process items in a canonical (sorted) entity order so the
        # per-item advisory locks — theoretical_sum (via _sum_theoretical) and
        # current_balance (via the movement cascade), both transaction-scoped and
        # held to the outer commit — are acquired in the same order as every
        # other writer. In request order two concurrent set-actual calls over an
        # overlapping entity set could take them in opposite orders and deadlock
        # (AB/BA). The result is order-independent (each item is an isolated
        # upsert). Sort key mirrors CurrentBalanceService's None-coerced lock
        # ordering so it stays consistent with the other lock sites.
        items = sorted(
            items,
            key=lambda item: (
                str(item.get("id") or ""),
                item.get(unit_key) or "",
                item.get(size_key) or "",
                str(item.get("storage") or ""),
            ),
        )

        # Batch-fetch all referenced storages to avoid N+1.
        storage_ids = {item["storage"] for item in items if item.get("storage")}
        storages_by_id = {s.id: s for s in Storage.objects.filter(id__in=storage_ids)}

        for item in items:
            instance, _created = model.objects.update_or_create(
                year=item.get("year"),
                delivery_week=item.get("delivery_week"),
                day_number=day_number_fn(item),
                share_article_id=item.get("id"),
                unit=item.get(unit_key),
                size=item.get(size_key),
                storage=storages_by_id[item["storage"]],
                defaults={"amount": item.get(amount_key)},
            )
            # Upsert (delete-then-recreate) the movement: update_or_create can
            # return an existing row (office re-runs, or the composite key
            # already existed), and a plain create would append a second
            # movement with no uniqueness guard, double-counting stock.
            GenericDocumentationService._upsert_movement(instance)

    @staticmethod
    def bulk_set_as_expected(data: dict[str, Any]) -> None:
        """Record theoretical/expected HARVEST as actual harvest for the
        selected items (upsert + movement). No-op when ``selectedData`` is
        empty; the calling viewset owns the 204."""
        DocumentationSummaryService._bulk_set_actual(
            data.get("selectedData", []),
            model=Harvest,
            amount_key="theoretical_harvest_amount",
            unit_key="theoretical_harvest_unit",
            size_key="theoretical_harvest_size",
            day_number_fn=lambda item: item.get("day_number"),
        )

    @staticmethod
    def bulk_set_purchase_as_expected(data: dict[str, Any]) -> None:
        """Record theoretical/expected PURCHASE as actual purchase for the
        selected items (upsert + movement). Purchases always land on
        ``PURCHASE_DAY`` (matching the ``TheoreticalPurchase``), instead of the
        old NULL day_number. No-op when ``selectedData`` is empty."""
        DocumentationSummaryService._bulk_set_actual(
            data.get("selectedData", []),
            model=Purchase,
            amount_key="theoretical_purchase_amount",
            unit_key="theoretical_purchase_unit",
            size_key="theoretical_purchase_size",
            day_number_fn=lambda _item: PURCHASE_DAY,
        )

    @staticmethod
    @transaction.atomic
    def add_additional_theoretical_amount(
        data: dict[str, Any], model: ModelType
    ) -> Any:
        """Create an additional theoretical entry and its movement."""

        model_key = model.lower()
        models = DocumentationSummaryService.MODEL_MAPPING[model_key]
        share_article_obj = ShareArticle.objects.get(id=data.get("share_article"))
        short_term_storage = DocumentationSummaryService._get_short_term_storage()

        common_fields = {
            "year": data.get("year"),
            "delivery_week": data.get("delivery_week"),
            "day_number": (
                data.get("day_number") if model_key != "purchase" else PURCHASE_DAY
            ),
            "share_article": share_article_obj,
            "unit": data.get("unit"),
            "size": data.get("size"),
            "storage": short_term_storage,
        }

        # Purchase rows are uniquely identified per seller; without this the
        # additional row and the placeholder Purchase would be created with
        # seller=None even though the request supplied one.
        if model_key == "purchase":
            seller_id = data.get("seller")
            common_fields["seller"] = (
                Reseller.objects.filter(id=seller_id).first() if seller_id else None
            )

        fk_field = DocumentationSummaryService._ADDITIONAL_FK_FIELD[model_key]
        mtype = DocumentationSummaryService._MOVEMENT_TYPE[model_key]

        DocumentationSummaryService._upsert_additional_and_movement(
            models=models,
            common_fields=common_fields,
            data=data,
            model_key=model_key,
            share_article=share_article_obj,
            storage=short_term_storage,
            fk_field=fk_field,
            mtype=mtype,
            partial=False,
        )

        # Save note on all theoretical entries for this grouping (after the
        # upsert so freshly created additional rows also receive it).
        DocumentationSummaryService._propagate_note(
            models, common_fields, data.get("note")
        )

        # Get or create actual entry
        instance = DocumentationSummaryService._get_or_create_actual_instance(
            models["actual"], common_fields
        )

        # Update model-specific fields
        DocumentationSummaryService._update_model_specific_fields(instance, data, model)

        instance.save()
        return instance

    @staticmethod
    def _sync_additional_movement(
        additional_obj: Any,
        amount: Any,
        common_fields: dict[str, Any],
        share_article_obj: Any,
        storage: Any,
        fk_field: str,
        mtype: str,
    ) -> None:
        """Sync the movement for an additional theoretical entry."""
        from decimal import Decimal

        from .documentation_service import GenericDocumentationService
        from .snapshot_service import SnapshotService
        from .theoretical_objects import recalculate_actual_corrections

        _movement_datetime = GenericDocumentationService._movement_datetime

        old_movements = list(
            MovementShareArticle.objects.filter(**{fk_field: additional_obj})
        )
        MovementShareArticle.objects.filter(**{fk_field: additional_obj}).delete()

        new_movement = None
        # NOTE: ``amount`` may be a Decimal (DocumentationMixin.amount is a
        # DecimalField); ``int(Decimal("0.5"))`` is 0, which would silently
        # drop fractional adjustments. Compare against Decimal("0") instead.
        if amount and Decimal(str(amount)) > 0:
            new_movement = MovementShareArticle.objects.create(
                date=_movement_datetime(
                    common_fields["year"],
                    common_fields["delivery_week"],
                    common_fields["day_number"] or 0,
                ),
                movement_type=mtype,
                **{fk_field: additional_obj},
                share_article=share_article_obj,
                unit=common_fields["unit"],
                size=common_fields["size"],
                amount=Decimal(str(amount)),
                storage=storage,
                is_theoretical=True,
            )

        affected = old_movements + ([new_movement] if new_movement else [])
        if affected:
            SnapshotService.cascade_for_movements(affected)
            recalculate_actual_corrections(affected, {mtype})

    @staticmethod
    def _upsert_additional_and_movement(
        *,
        models: dict[str, Any],
        common_fields: dict[str, Any],
        data: dict[str, Any],
        model_key: str,
        share_article: Any,
        storage: Any,
        fk_field: str,
        mtype: str,
        partial: bool,
    ) -> None:
        """Upsert the additional-theoretical row(s) for this grouping and resync
        their movement(s).

        HARVEST splits into a share-content and an order-content entry (see
        ``_CONTENT_TYPE_FLAGS``); every other model carries a single ``amount``
        entry. ``share_article``/``storage`` are the movement dimensions — the
        caller passes them from the request payload (add) or the existing
        instance (update).

        ``partial=True`` (update) touches only the keys present in ``data`` (a
        harvest edit may send just one content amount); ``partial=False`` (add)
        always writes both harvest entries. A harvest payload carrying a plain
        ``amount`` instead of the content keys falls through to the single entry,
        preserving the update path's ``elif "amount" in data`` behaviour.
        """

        def _upsert(amount: Any, flags: dict[str, bool] | None = None) -> None:
            additional_obj, _ = models["additional"].objects.update_or_create(
                **common_fields, **(flags or {}), defaults={"amount": amount}
            )
            DocumentationSummaryService._sync_additional_movement(
                additional_obj,
                amount,
                common_fields,
                share_article,
                storage,
                fk_field,
                mtype,
            )

        if model_key == "harvest":
            handled = False
            for amount_key, flags in DocumentationSummaryService._CONTENT_TYPE_FLAGS:
                if partial and amount_key not in data:
                    continue
                _upsert(data.get(amount_key) or 0, flags)
                handled = True
            if handled:
                return

        # Non-harvest model, or a harvest payload with no content keys present.
        if partial and "amount" not in data:
            return
        _upsert(data.get("amount"))

    @staticmethod
    def _propagate_note(
        models: dict[str, Any], common_fields: dict[str, Any], note: Any
    ) -> None:
        """Write ``note`` onto every theoretical + additional row of this
        (year, week, day, article, unit, size) grouping. Storage/seller-blind so
        the whole grouping shares the office's note; no-op when ``note is None``.
        """
        if note is None:
            return
        theoretical_filter = {
            "year": common_fields["year"],
            "delivery_week": common_fields["delivery_week"],
            "day_number": common_fields["day_number"],
            "share_article": common_fields["share_article"],
            "unit": common_fields["unit"],
            "size": common_fields["size"],
        }
        models["theoretical"].objects.filter(**theoretical_filter).update(note=note)
        models["additional"].objects.filter(**theoretical_filter).update(note=note)

    @staticmethod
    def _get_or_create_actual_instance(
        actual_model: Any, common_fields: dict[str, Any]
    ) -> Any:
        """Get or create an actual instance with None amount."""
        try:
            return actual_model.objects.get(**common_fields, amount=None)
        except actual_model.DoesNotExist:
            return actual_model.objects.create(**common_fields, amount=None)

    @staticmethod
    def _update_model_specific_fields(
        instance: Any, data: dict[str, Any], model: ModelType
    ) -> None:
        """Update fields specific to the model type."""
        if model in ["harvest", "purchase"]:
            instance.amount_per_pu = data.get("amount_per_pu") or 0

            if model == "harvest":
                harvesting_crate = data.get("harvesting_crate")
                instance.harvesting_crate = (
                    Crate.objects.get(id=harvesting_crate) if harvesting_crate else None
                )

    @staticmethod
    @transaction.atomic
    def update_additional_theoretical_amount(
        data: dict[str, Any], pk: int, model: ModelType
    ) -> Any:
        """Update an additional theoretical entry and its movement."""
        model_key = model.lower()
        models = DocumentationSummaryService.MODEL_MAPPING[model_key]

        instance = models["actual"].objects.get(id=pk)

        common_fields = {
            "year": instance.year,
            "delivery_week": instance.delivery_week,
            "day_number": instance.day_number,
            "share_article": instance.share_article,
            "unit": instance.unit,
            "size": instance.size,
            "storage": instance.storage,
        }
        if model_key == "purchase":
            # AdditionalTheoreticalPurchase is identified per seller; the upsert
            # lookup below must include it (mirroring add_additional_theoretical_
            # amount), else a seller-blind update_or_create mutates the wrong
            # seller's row or raises MultipleObjectsReturned across sellers.
            common_fields["seller"] = instance.seller

        # Update model-specific fields
        DocumentationSummaryService._update_model_specific_fields(instance, data, model)
        instance.save()

        # Save note on all theoretical entries for this grouping (before the
        # upsert, preserving the update path's ordering).
        DocumentationSummaryService._propagate_note(
            models, common_fields, data.get("note")
        )

        fk_field = DocumentationSummaryService._ADDITIONAL_FK_FIELD[model_key]
        mtype = DocumentationSummaryService._MOVEMENT_TYPE[model_key]

        DocumentationSummaryService._upsert_additional_and_movement(
            models=models,
            common_fields=common_fields,
            data=data,
            model_key=model_key,
            share_article=instance.share_article,
            storage=instance.storage,
            fk_field=fk_field,
            mtype=mtype,
            partial=True,
        )

        return instance
