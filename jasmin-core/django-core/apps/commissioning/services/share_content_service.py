from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from isoweek import Week

from ..errors import (
    CommissioningError,
    ShareArticleNotFound,
    ShareContentError,
    ShareContentNotFound,
    SharesDeliveryDayNotFound,
    ShareTypeVariationNotFound,
)
from ..models import (
    DeliveryStation,
    DeliveryStationDay,
    Forecast,
    MovementShareArticle,
    Reseller,
    Share,
    ShareArticle,
    ShareContent,
    SharesDeliveryDay,
    ShareTypeVariation,
    Storage,
)
from ..utils import (
    batch_get_physical_variation_totals_for_weeks,
    sort_share_articles,
)
from ..utils.dynamic_keys import DAY_VARIATION_RE, parse_amount_cell
from ..utils.iso_week_utils import previous_day_stock_coordinates
from .stock_service import StockService

logger = logging.getLogger(__name__)


class ShareContentService:
    """Service for processing harvest share planning data from frontend."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @transaction.atomic
    def process_share_planning_data(
        self,
        data: dict[str, Any],
        *,
        collect_movements: list[MovementShareArticle] | None = None,
    ) -> list[ShareContent]:
        """Process frontend data and create ShareContent + theoretical objects + movements.

        The theoretical and SHARECONTENT builders' snapshot cascades are
        collected and run as ONE union cascade at the end (a single sorted
        ``current_balance:*`` advisory-lock pass — two separate sorted passes
        could interleave with a concurrent writer and AB/BA-deadlock). When the
        caller passes ``collect_movements`` it takes over even that final
        cascade (``replace_share_planning`` folds the old movements in too).
        """
        year: int = data.get("year")
        delivery_week: int = data.get("delivery_week")
        share_article_id = data.get("share_article")
        unit: str | None = data.get("unit")
        size: str | None = data.get("size")
        note: str | None = data.get("note")
        seller_id = data.get("seller")
        cleaning: bool = data.get("cleaning", False)
        washing: bool = data.get("washing", False)
        kg_per_piece = data.get("kg_per_piece")
        price_per_unit = data.get("price_per_unit")
        packing_station: int = data.get("packing_station", 1)

        if not all([year, delivery_week, share_article_id]):
            raise CommissioningError(
                "Missing required fields: year, delivery_week, or share_article",
                code="share_content.missing_required",
            )

        active_at_date = Week(year, delivery_week).saturday()

        forecast = Forecast.objects.filter(
            year=year,
            delivery_week=delivery_week,
            share_article=share_article_id,
            unit=unit,
            size=size,
        ).first()

        day_variations = self._extract_day_variations(data)
        if not day_variations:
            # "All zero" is a valid update intent: the user cleared every
            # cell on this slot, which in this domain means "no human plan
            # any more" — the same state as a freshly forecast-scaffolded
            # row (amount IS NULL OR amount = 0; see
            # ``forecast_service._delete_orphaned_share_contents``). The
            # caller already wiped the slot's old rows before invoking
            # this path, so returning an empty list leaves the slot in
            # the unplanned state. Refusing to do this would force the
            # surrounding ``@transaction.atomic`` to roll the wipe back
            # and the user would silently see their cleared values
            # revert. The viewset's CREATE path enforces a non-empty
            # payload separately so a fresh ``POST`` with no amounts
            # still 400s.
            return []

        share_article = self._get_share_article(share_article_id)
        seller_obj: Reseller | None = (
            Reseller.objects.get(id=seller_id) if seller_id is not None else None
        )

        # Pre-fetch ShareTypeVariation and SharesDeliveryDay to avoid N+1
        variation_ids = {v for _, v, _, _, _ in day_variations}
        day_ids = {d for d, _, _, _, _ in day_variations}

        variations_by_id = {
            str(v.id): v
            for v in ShareTypeVariation.objects.filter(id__in=variation_ids)
        }
        days_by_id = {
            str(d.id): d for d in SharesDeliveryDay.objects.filter(id__in=day_ids)
        }

        # Pre-fetch all station days for this week (avoids per-day query)
        all_station_days = list(
            DeliveryStationDay.current.active_at_date(active_at_date)
            .filter(delivery_station__is_active=True)
            .select_related("delivery_station")
        )
        station_days_by_day: dict[Any, list[DeliveryStationDay]] = {}
        for share_delivery in all_station_days:
            station_days_by_day.setdefault(share_delivery.delivery_day_id, []).append(
                share_delivery
            )

        # Map station IDs to DeliveryStation objects (avoids N+1 per station)
        station_by_id: dict[Any, DeliveryStation] = {
            share_delivery.delivery_station_id: share_delivery.delivery_station
            for share_delivery in all_station_days
        }

        share_contents_to_create: list[ShareContent] = []
        seen_share_station: set[tuple[Any, Any]] = set()

        for day_id, variation_id, amount, tour, station_id in day_variations:
            share_type_variation = variations_by_id.get(str(variation_id))
            if share_type_variation is None:
                raise ShareTypeVariationNotFound(
                    f"ShareTypeVariation with id {variation_id} does not exist",
                    details={"variation_id": variation_id},
                )
            share_delivery_day = days_by_id.get(str(day_id))
            if share_delivery_day is None:
                raise SharesDeliveryDayNotFound(
                    f"SharesDeliveryDay with id {day_id} does not exist",
                    details={"day_id": day_id},
                )

            share, _ = Share.get_or_create_for_delivery(
                share_type_variation=share_type_variation,
                year=year,
                delivery_week=delivery_week,
                delivery_day=share_delivery_day,
            )

            if station_id is not None:
                resolved_stations = [station_by_id.get(station_id)]
                if resolved_stations[0] is None:
                    resolved_stations = [DeliveryStation.objects.get(id=station_id)]
            elif tour is not None:
                resolved_stations = [
                    share_delivery.delivery_station
                    for share_delivery in station_days_by_day.get(
                        share_delivery_day.id, []
                    )
                    if share_delivery.tour_number == int(tour)
                ]
            else:
                resolved_stations = [
                    share_delivery.delivery_station
                    for share_delivery in station_days_by_day.get(
                        share_delivery_day.id, []
                    )
                ]

            for station_obj in resolved_stations:
                if station_obj is None:
                    continue
                key = (share.id, station_obj.id)
                if key in seen_share_station:
                    raise ShareContentError(
                        f"Duplicate planning entry: share_article={share_article.id} "
                        f"unit={unit} size={size} resolves to the same delivery "
                        f"station ({station_obj.id}) for share {share.id} more than "
                        f"once. Check for overlapping tour/station selections on "
                        f"day {day_id} / variation {variation_id}."
                    )
                seen_share_station.add(key)
                share_contents_to_create.append(
                    ShareContent(
                        share=share,
                        share_article=share_article,
                        amount=amount,
                        unit=unit,
                        size=size,
                        note=note,
                        seller=seller_obj,
                        cleaning=cleaning,
                        washing=washing,
                        forecast=forecast,
                        delivery_station=station_obj,
                        kg_per_piece=(
                            Decimal(str(kg_per_piece)) if kg_per_piece else None
                        ),
                        price_per_unit=(
                            Decimal(str(price_per_unit)) if price_per_unit else None
                        ),
                        packing_station=packing_station or 1,
                    )
                )

        share_contents = ShareContent.objects.bulk_create(share_contents_to_create)

        # Re-fetch with select_related to avoid N+1 in theoretical/movement creation
        share_contents = list(
            ShareContent.objects.filter(
                id__in=[share_content.id for share_content in share_contents]
            ).select_related(
                "share__share_type_variation",
                "share__delivery_day",
                "share_article",
                "forecast",
                "seller",
            )
        )

        # Compute the demand totals once and share them — both builders
        # need the identical lookup.
        deferred_movements: list[MovementShareArticle] = (
            collect_movements if collect_movements is not None else []
        )
        variation_totals_by_week = self.variation_totals_by_week(share_contents)
        self.create_all_theoretical_objects(
            share_contents,
            variation_totals_by_week=variation_totals_by_week,
            collect_movements=deferred_movements,
        )
        self.create_movements(
            share_contents,
            variation_totals_by_week=variation_totals_by_week,
            collect_movements=deferred_movements,
        )
        if collect_movements is None and deferred_movements:
            from .snapshot_service import SnapshotService

            SnapshotService.cascade_for_movements(deferred_movements)

        return share_contents

    @transaction.atomic
    def recompute_for_shares(
        self,
        shares: Iterable[Share],
        *,
        collect_movements: list[MovementShareArticle] | None = None,
    ) -> list[Any]:
        """Wipe + rebuild theoreticals and SHARECONTENT movements for ``shares``.

        Idempotent — safe to call any time the inputs change (ShareContent
        edited, ShareDelivery added/removed, Forecast updated, day-fields
        moved). Locks the affected ``Share`` rows for the duration of the
        transaction to prevent concurrent rebuilds from racing.

        Snapshot cascades are single-pass: every movement the rebuild touches
        (new theoreticals, new SHARECONTENT rows, re-derived corrections, and
        the captured OLD movements) is accumulated and cascaded ONCE at the
        end, so the per-entity ``current_balance:*`` advisory locks are
        acquired in one canonically-sorted pass. The old shape cascaded in
        three separate passes (theoretical → new → old) whose concatenation
        was not globally sorted — two concurrent overlapping recomputes (or a
        recompute vs. a bulk stock write) could acquire the shared locks in
        opposite orders and AB/BA-deadlock. ``collect_movements`` hands even
        the final cascade to an enclosing caller that has more movements to
        fold into the same single pass.

        Returns the list of touched ``ShareContent`` ids (handy for tests
        and callers that want to invalidate caches).
        """
        # Local imports to keep the top-of-file lean and avoid cycles.
        from ..models import (
            TheoreticalCleanAmount,
            TheoreticalHarvest,
            TheoreticalPurchase,
            TheoreticalWashAmount,
        )

        share_ids = [s.id if hasattr(s, "id") else s for s in shares]
        if not share_ids:
            return []

        # Serialize concurrent recomputes for the same Share — without this,
        # two transactions touching the same Share could each delete + rebuild
        # at the same time and double-write movements. Lock in deterministic
        # (id) order so overlapping recomputes serialise without AB/BA-deadlocking
        # (Share declares no Meta.ordering, so the FOR UPDATE scan order is
        # otherwise plan-dependent).
        list(Share.objects.select_for_update().filter(id__in=share_ids).order_by("id"))

        share_contents = list(
            ShareContent.objects.filter(share_id__in=share_ids).select_related(
                "share__share_type_variation",
                "share__delivery_day",
                "share_article",
                "forecast",
                "seller",
                "delivery_station",
            )
        )
        if not share_contents:
            return []

        # Capture the OLD movements BEFORE the wipe so the rebuild can
        # re-cascade every storage a zeroed / relocated / date-shifted movement
        # strands. BOTH halves are captured: the SHARECONTENT rows AND the
        # theoretical HARVEST/PURCHASE/WASH/CLEAN movements — the latter carry
        # share_content=NULL (their source FK is ``theoretical_*``), so they are
        # reached via their Theoretical* parent's share_content link. The
        # rebuild's own cascades only cover the NEW storages, so an old
        # theoretical storage the rebuild relocates away from (e.g.
        # comes-from-long-term flips) would otherwise stay stranded.
        from .snapshot_service import SnapshotService
        from .theoretical_objects import recalculate_actual_corrections

        old_movements = list(
            MovementShareArticle.objects.for_share_contents(share_contents)
        )

        # Theoreticals cascade-delete their is_theoretical=True
        # MovementShareArticle rows (FK on_delete=CASCADE).
        TheoreticalHarvest.objects.filter(share_content__in=share_contents).delete()
        TheoreticalPurchase.objects.filter(share_content__in=share_contents).delete()
        TheoreticalWashAmount.objects.filter(share_content__in=share_contents).delete()
        TheoreticalCleanAmount.objects.filter(share_content__in=share_contents).delete()

        # SHARECONTENT-type movements point at ShareContent (which still
        # exists), so they don't cascade-delete — wipe them explicitly.
        MovementShareArticle.objects.filter(
            share_content__in=share_contents,
            movement_type="SHARECONTENT",
        ).delete()

        # Compute the demand totals once and share them — this is the
        # recompute hot path (a default-share-content save spans a whole
        # season of weeks) and the two builders need the identical lookup.
        deferred_movements: list[MovementShareArticle] = (
            collect_movements if collect_movements is not None else []
        )
        variation_totals_by_week = self.variation_totals_by_week(share_contents)
        self.create_all_theoretical_objects(
            share_contents,
            variation_totals_by_week=variation_totals_by_week,
            collect_movements=deferred_movements,
        )
        self.create_movements(
            share_contents,
            variation_totals_by_week=variation_totals_by_week,
            collect_movements=deferred_movements,
        )

        if old_movements:
            deferred_movements.extend(old_movements)
            # Re-derive actual harvest/purchase corrections for the OLD
            # theoretical dimensions too. create_theoretical_objects only recalcs
            # the dimensions of the NEW theoretical movements, so a dimension
            # whose theoreticals dropped to zero (demand gone) or relocated keeps
            # a stale correction (amount = counted − Σ_old) and its entity total
            # ≠ counted. Recomputing from the OLD dimensions re-derives them
            # against the CURRENT theoreticals (= 0 if gone) → entity total =
            # counted again. (SHARECONTENT keys in old_movements match no actual
            # correction, so they are harmless no-ops here.) The mutated
            # corrections join the deferred union instead of cascading here.
            recalculate_actual_corrections(
                old_movements, collect_movements=deferred_movements
            )

        # ONE cascade over everything the rebuild touched — old entities whose
        # movements were wiped/relocated, new theoretical + SHARECONTENT
        # entities, and re-derived corrections. cascade_for_movements sorts its
        # entity set, so this is the transaction's single, canonically-ordered
        # advisory-lock pass (unless an enclosing caller collects it).
        if collect_movements is None and deferred_movements:
            SnapshotService.cascade_for_movements(deferred_movements)

        return [share_content.id for share_content in share_contents]

    def get_share_content_as_frontend_data(
        self, share_content_queryset: QuerySet[ShareContent] | list[ShareContent]
    ) -> list[dict[str, Any]]:
        """Convert ShareContent objects to frontend data format.

        Orchestrates four phases, each its own method: batch prefetch of every
        per-group lookup, group-row initialisation, per-content accumulation
        into the group, and the flatten into the frontend's flat-key shape.
        """
        all_share_contents = list(share_content_queryset)

        forecast_by_key = self._prefetch_forecasts_by_group_key(all_share_contents)
        tour_number_lookup = self._prefetch_tour_numbers(all_share_contents)
        stock_by_week = self._prefetch_stock_by_week(all_share_contents)
        # One aggregated query for the whole set instead of 2-3 per week.
        variation_totals_by_week = self.variation_totals_by_week(all_share_contents)
        pricing_cache = self._prefetch_pricing_cache(all_share_contents)

        grouped_data: dict[tuple, dict[str, Any]] = {}
        for share_content in all_share_contents:
            share = share_content.share
            group_key = (
                share.year,
                share.delivery_week,
                share_content.share_article_id,
                share_content.unit,
                share_content.size,
            )
            if group_key not in grouped_data:
                grouped_data[group_key] = self._init_frontend_group_row(
                    share_content,
                    forecast=forecast_by_key.get(group_key),
                    stock_by_week=stock_by_week,
                    pricing_cache=pricing_cache,
                )
            self._accumulate_content_into_group(
                grouped_data[group_key],
                share_content,
                variation_totals_by_week=variation_totals_by_week,
                tour_number_lookup=tour_number_lookup,
            )

        return sort_share_articles(
            [self._flatten_group_row(row) for row in grouped_data.values()]
        )

    @staticmethod
    def _prefetch_forecasts_by_group_key(
        all_share_contents: list[ShareContent],
    ) -> dict[tuple, Forecast]:
        """Batch-fetch the forecasts for every unique (year, week, article,
        unit, size) group key — one query instead of one per group."""
        from django.db.models import Q

        group_keys_seen: set[tuple] = set()
        q_filter = Q()
        for share_content in all_share_contents:
            share = share_content.share
            group_key = (
                share.year,
                share.delivery_week,
                share_content.share_article_id,
                share_content.unit,
                share_content.size,
            )
            if group_key not in group_keys_seen:
                group_keys_seen.add(group_key)
                q_filter |= Q(
                    year=share.year,
                    delivery_week=share.delivery_week,
                    share_article_id=share_content.share_article_id,
                    unit=share_content.unit,
                    size=share_content.size,
                )

        if not group_keys_seen:
            return {}
        forecast_by_key: dict[tuple, Forecast] = {}
        for forecast in Forecast.objects.filter(q_filter).prefetch_related(
            "forecastsharetypevariation_set__share_type_variation"
        ):
            forecast_by_key[
                (
                    forecast.year,
                    forecast.delivery_week,
                    forecast.share_article_id,
                    forecast.unit,
                    forecast.size,
                )
            ] = forecast
        return forecast_by_key

    @staticmethod
    def _prefetch_tour_numbers(
        all_share_contents: list[ShareContent],
    ) -> dict[tuple, int | None]:
        """Batch the DeliveryStationDay tour_number lookup keyed by
        (delivery_station_id, delivery_day_id) — avoids a per-row query."""
        delivery_day_ids = {
            share_content.share.delivery_day_id for share_content in all_share_contents
        }
        station_ids = {
            share_content.delivery_station_id
            for share_content in all_share_contents
            if share_content.delivery_station_id
        }
        tour_number_lookup: dict[tuple, int | None] = {}
        if station_ids and delivery_day_ids:
            for delivery_station_day in DeliveryStationDay.objects.filter(
                delivery_station_id__in=station_ids,
                delivery_day_id__in=delivery_day_ids,
            ):
                tour_number_lookup[
                    (
                        delivery_station_day.delivery_station_id,
                        delivery_station_day.delivery_day_id,
                    )
                ] = delivery_station_day.tour_number
        return tour_number_lookup

    @staticmethod
    def _prefetch_stock_by_week(
        all_share_contents: list[ShareContent],
    ) -> dict[tuple[int, int], dict[tuple, dict]]:
        """Stock data (Sunday of the previous week) once per unique week."""
        stock_by_week: dict[tuple[int, int], dict[tuple, dict]] = {}
        unique_weeks = {
            (share_content.share.year, share_content.share.delivery_week)
            for share_content in all_share_contents
        }
        for year, delivery_week in unique_weeks:
            stock_year, stock_week, stock_day = previous_day_stock_coordinates(
                Week(year, delivery_week).day(0)
            )
            stock_by_week[(year, delivery_week)] = (
                StockService.get_theoretical_current_stock(
                    year=stock_year,
                    delivery_week=stock_week,
                    day_number=stock_day,
                )
            )
        return stock_by_week

    @staticmethod
    def _prefetch_pricing_cache(
        all_share_contents: list[ShareContent],
    ) -> dict[tuple, object]:
        """Pricing rows for articles whose content is missing price_per_unit,
        once per (article, year, week)."""
        pricing_cache: dict[tuple, object] = {}
        for share_content in all_share_contents:
            if share_content.price_per_unit is None:
                cache_key = (
                    share_content.share_article_id,
                    share_content.share.year,
                    share_content.share.delivery_week,
                )
                if cache_key not in pricing_cache:
                    tuesday = Week(cache_key[1], cache_key[2]).tuesday()
                    pricing_cache[cache_key] = (
                        share_content.share_article.get_pricing_on_date(tuesday)
                    )
        return pricing_cache

    def _init_frontend_group_row(
        self,
        share_content: ShareContent,
        *,
        forecast: Forecast | None,
        stock_by_week: dict[tuple[int, int], dict[tuple, dict]],
        pricing_cache: dict[tuple, object],
    ) -> dict[str, Any]:
        """The group row's static fields, built from the group's FIRST content
        row (per-content values are accumulated separately)."""
        share = share_content.share
        if forecast is not None:
            forecast_available_amount = forecast.amount
            forecast_unit = forecast.unit
            forecast_note = forecast.note
            forecast_id = forecast.id
            forecast_share_type_variation_ids = list(
                forecast.forecastsharetypevariation_set.values_list(
                    "share_type_variation_id", flat=True
                )
            )
        else:
            forecast_available_amount = None
            forecast_unit = None
            forecast_note = None
            forecast_id = None
            forecast_share_type_variation_ids = []

        share_article = share_content.share_article
        return {
            "id": f"{share.year}_{share.delivery_week}_{share_article.id}_{share_content.unit}_{share_content.size}",
            "year": share.year,
            "delivery_week": share.delivery_week,
            "share_article": share_article.id,
            "share_article_name": share_article.name,
            "kg_per_piece_S": share_article.kg_per_piece_S,
            "kg_per_piece_M": share_article.kg_per_piece_M,
            "kg_per_piece_L": share_article.kg_per_piece_L,
            "kg_per_bunch_S": share_article.kg_per_bunch_S,
            "kg_per_bunch_M": share_article.kg_per_bunch_M,
            "kg_per_bunch_L": share_article.kg_per_bunch_L,
            "kg_per_piece": self._get_kg_per_piece_with_fallback(share_content),
            "price_per_unit": self._get_price_per_unit_with_fallback(
                share_content,
                share.year,
                share.delivery_week,
                pricing_cache=pricing_cache,
            ),
            "packing_station": share_content.packing_station,
            "unit": share_content.unit,
            "size": share_content.size,
            "note": share_content.note,
            "seller": (share_content.seller_id if share_content.seller_id else None),
            "cleaning": share_content.cleaning,
            "washing": share_content.washing,
            "forecast_available_amount": forecast_available_amount,
            "forecast": forecast_id,
            "forecast_unit": forecast_unit,
            "forecast_note": forecast_note,
            "forecast_share_type_variation_ids": forecast_share_type_variation_ids,
            **self._get_stock_fields(
                stock_by_week.get((share.year, share.delivery_week), {}),
                share_content.share_article_id,
                share_content.unit,
                share_content.size,
            ),
            "variations": {},
            "basic_variations": {},
            "tour_variations": {},
            "day_planned_amounts": {},
            "backup_share_article": (
                share_content.backup_share_article_id
                if share_content.backup_share_article_id
                else None
            ),
            "backup_share_article_name": (
                share_content.backup_share_article.name
                if share_content.backup_share_article
                else None
            ),
            "backup_unit": share_content.backup_unit,
            "backup_size": share_content.backup_size,
            "backup_variations": {},
            "is_finalized": True,
        }

    def _accumulate_content_into_group(
        self,
        group_row: dict[str, Any],
        share_content: ShareContent,
        *,
        variation_totals_by_week: dict[tuple[int, int], dict],
        tour_number_lookup: dict[tuple, int | None],
    ) -> None:
        """Fold one content row's per-(day, variation, station) values into
        its group row's variation buckets and day-planned totals."""
        share = share_content.share
        day = share.delivery_day_id
        variation = share.share_type_variation_id
        base_key = f"day_{day}_variation_{variation}"

        # Group is finalized only if ALL its ShareContent rows are finalized
        if not share_content.is_finalized:
            group_row["is_finalized"] = False

        amount_str = str(share_content.amount) if share_content.amount else 0

        if share_content.delivery_station_id and share_content.amount:
            total_quantity = self._total_quantity_for(
                share_content, variation_totals_by_week
            )
            station_total = share_content.amount * total_quantity

            day_planned_key = f"day_{day}_planned_amount"
            group_row["day_planned_amounts"].setdefault(day_planned_key, Decimal(0))
            group_row["day_planned_amounts"][day_planned_key] += station_total

        if base_key not in group_row["basic_variations"]:
            group_row["basic_variations"][base_key] = amount_str

        # Track backup amount per day/variation
        backup_key = f"backup_{base_key}"
        if backup_key not in group_row["backup_variations"]:
            backup_amount = (
                str(share_content.backup_amount) if share_content.backup_amount else 0
            )
            group_row["backup_variations"][backup_key] = backup_amount

        if share_content.delivery_station_id:
            station_key = f"{base_key}_station_{share_content.delivery_station_id}"
            group_row["variations"][station_key] = amount_str

            tour_number = tour_number_lookup.get(
                (share_content.delivery_station_id, share.delivery_day_id)
            )
        else:
            tour_number = None

        if tour_number:
            tour_key = f"{base_key}_tour_{tour_number}"
            if tour_key not in group_row["tour_variations"]:
                group_row["tour_variations"][tour_key] = amount_str

    @staticmethod
    def _flatten_group_row(group_row: dict[str, Any]) -> dict[str, Any]:
        """Collapse the variation buckets into the flat ``day_X_...`` keys the
        frontend's planning grid expects."""
        day_planned_amounts = group_row.pop("day_planned_amounts")
        for day_key, amount in day_planned_amounts.items():
            group_row[day_key] = str(amount)

        group_row.update(group_row.pop("basic_variations"))
        group_row.update(group_row.pop("tour_variations"))
        group_row.update(group_row.pop("variations"))
        group_row.update(group_row.pop("backup_variations"))
        return group_row

    @staticmethod
    def _get_stock_fields(
        stock_data: dict[tuple, dict],
        share_article_id: str,
        unit: str | None,
        size: str | None,
    ) -> dict[str, Any]:
        """Build current_stock_begin_of_week and current_stock_note from stock data.

        Aggregates across all storages for the given (article, unit, size).
        """
        # Stock quantities are DecimalFields — accumulate in Decimal and
        # float only at the response boundary (the returned dict), so
        # cross-storage sums don't accrue binary-fp drift.
        total_theoretical = Decimal("0")
        total_counted = Decimal("0")
        any_counted = False
        collected_notes: list[str] = []

        sa_id_str = str(share_article_id)
        for (s_article, s_unit, s_size, _storage), values in stock_data.items():
            if s_article == sa_id_str and s_unit == unit and s_size == size:
                theoretical = values.get("theoretical_current_stock") or 0
                counted = values.get("current_stock_amount")
                if counted is not None:
                    any_counted = True
                    total_counted += Decimal(str(counted))
                    inv_note = (values.get("note") or "").strip()
                    if inv_note:
                        collected_notes.append(inv_note)
                total_theoretical += Decimal(str(theoretical))

        if any_counted:
            stock_value = max(total_counted, Decimal("0"))
            cs_note = "; ".join(collected_notes)
            note = f"gezählt; {cs_note}" if cs_note else "gezählt"
        elif total_theoretical:
            stock_value = max(total_theoretical, Decimal("0"))
            note = "errechnet"
        else:
            stock_value = Decimal("0")
            note = ""

        return {
            "current_stock_begin_of_week": float(stock_value),
            "current_stock_note": note,
        }

    def get_share_content_for_week(
        self,
        year: int,
        delivery_week: int,
        share_article: str | None = None,
        share_option: str | None = None,
        is_past: bool = False,
    ) -> list[dict[str, Any]]:
        """Get share content data for a specific week in frontend format.

        Also synthesizes "stock-only" rows for share articles that have
        leftover stock at the start of the week but no ``ShareContent``
        yet (no forecast, no manual plan). Without this, the planner is
        blind to e.g. 12 KG of potatoes still in the storage when the
        forecast didn't include potatoes this week. The synthetic rows
        flow through the standard frontend colour ladder (current_stock
        > 0 → blue) and can be edited like any other row — saving
        creates a real ShareContent via the CREATE path.
        """
        manager = ShareContent.active.for_period(is_past=is_past)

        queryset = manager.filter(
            share__year=year,
            share__delivery_week=delivery_week,
            share__share_type_variation__share_type__share_option=share_option,
        ).select_related(
            "share__share_type_variation",
            "share__delivery_day",
            "share_article",
            "seller",
            "backup_share_article",
        )

        if share_article:
            queryset = queryset.filter(share_article__id=share_article)

        rows = self.get_share_content_as_frontend_data(queryset)

        # Stock-only synthesis only when the caller isn't drilling
        # into a single article — when they are, they explicitly want
        # that article and that article alone, no scaffold noise.
        if not share_article:
            rows.extend(
                self._build_stock_only_rows(
                    year=year,
                    delivery_week=delivery_week,
                    existing_rows=rows,
                    share_option=share_option,
                )
            )

        return rows

    @staticmethod
    def _build_stock_only_rows(
        *,
        year: int,
        delivery_week: int,
        existing_rows: list[dict[str, Any]],
        share_option: str | None = None,
    ) -> list[dict[str, Any]]:
        """Synthesize planning rows for ``(article, unit, size)`` combos
        that have stock at the start of the week but no ``ShareContent``
        (no forecast, no manual plan). The frontend renders them via
        the same colour ladder as forecast/plan rows — stock > 0 lights
        the row blue — and saving an amount creates a real
        ``ShareContent`` via the CREATE path.

        Stock is fetched at the same "Sunday of the preceding ISO week"
        cutoff that ``get_share_content_as_frontend_data`` uses for
        existing rows, so the numbers line up between real rows and
        synthetic ones.
        """
        seen_keys: set[tuple[str, str, str]] = {
            (str(row["share_article"]), row["unit"], row["size"])
            for row in existing_rows
        }

        stock_coords = previous_day_stock_coordinates(Week(year, delivery_week).day(0))
        stock_data = StockService.get_theoretical_current_stock(
            year=stock_coords.year,
            delivery_week=stock_coords.week,
            day_number=stock_coords.day_index,
        )

        # Aggregate across storages per (article, unit, size). A combo
        # that already has a real row is skipped — its stock fields
        # were filled in by ``_get_stock_fields`` on that row.
        aggregates: dict[tuple[str, str, str], dict[str, Any]] = {}
        for (sa_id, unit, size, _storage), values in stock_data.items():
            key = (str(sa_id), unit, size)
            if key in seen_keys:
                continue
            counted = values.get("current_stock_amount")
            theoretical = values.get("theoretical_current_stock") or 0
            if counted is not None:
                stock_value = Decimal(str(counted))
                inv_note = (values.get("note") or "").strip()
            else:
                stock_value = Decimal(str(theoretical))
                inv_note = ""
            if stock_value <= 0:
                continue
            agg = aggregates.setdefault(
                key,
                {"stock_value": Decimal("0"), "notes": [], "any_counted": False},
            )
            agg["stock_value"] += stock_value
            if counted is not None:
                agg["any_counted"] = True
                if inv_note:
                    agg["notes"].append(inv_note)

        if not aggregates:
            return []

        # Only synthesize stock rows for articles actually assigned to this
        # share option (``share_option`` / ``share_option2`` / ``share_option3``
        # on ShareArticle). Otherwise leftover stock of e.g. broccoli would
        # surface as a row when planning honey shares. Articles not in this set
        # are dropped by the ``sa is None`` guard below.
        from django.db.models import Q

        article_qs = ShareArticle.objects.filter(
            id__in={sa_id for (sa_id, _, _) in aggregates}
        )
        if share_option:
            article_qs = article_qs.filter(
                Q(share_option=share_option)
                | Q(share_option2=share_option)
                | Q(share_option3=share_option)
            )
        share_articles_by_id = {str(sa.id): sa for sa in article_qs}

        rows: list[dict[str, Any]] = []
        for (sa_id, unit, size), agg in aggregates.items():
            sa = share_articles_by_id.get(sa_id)
            if sa is None:
                continue
            # Float only at the boundary — accumulated in Decimal above.
            stock_value = float(max(agg["stock_value"], Decimal("0")))
            if agg["any_counted"]:
                joined_notes = "; ".join(agg["notes"])
                stock_note = f"gezählt; {joined_notes}" if joined_notes else "gezählt"
            else:
                stock_note = "errechnet"
            rows.append(
                {
                    "id": f"{year}_{delivery_week}_{sa.id}_{unit}_{size}",
                    "year": year,
                    "delivery_week": delivery_week,
                    "share_article": sa.id,
                    "share_article_name": sa.name,
                    "kg_per_piece_S": sa.kg_per_piece_S,
                    "kg_per_piece_M": sa.kg_per_piece_M,
                    "kg_per_piece_L": sa.kg_per_piece_L,
                    "kg_per_bunch_S": sa.kg_per_bunch_S,
                    "kg_per_bunch_M": sa.kg_per_bunch_M,
                    "kg_per_bunch_L": sa.kg_per_bunch_L,
                    "kg_per_piece": None,
                    "price_per_unit": None,
                    "packing_station": 1,
                    "unit": unit,
                    "size": size,
                    "note": None,
                    "seller": None,
                    "cleaning": False,
                    "washing": False,
                    "forecast_available_amount": None,
                    "forecast": None,
                    "forecast_unit": None,
                    "forecast_note": None,
                    "forecast_share_type_variation_ids": [],
                    "current_stock_begin_of_week": stock_value,
                    "current_stock_note": stock_note,
                    "variations": {},
                    "basic_variations": {},
                    "tour_variations": {},
                    "backup_share_article": None,
                    "backup_unit": None,
                    "backup_size": None,
                    "backup_variations": {},
                    "is_finalized": False,
                    # Hint for the frontend so it can give the row a
                    # distinct affordance later (icon, tooltip, etc.).
                    # Today the colour ladder already lights it blue
                    # via ``current_stock > 0``; this is purely a
                    # forward-looking flag.
                    "is_stock_only": True,
                }
            )
        return rows

    def get_group_data(
        self, share_contents: QuerySet[ShareContent] | list[ShareContent]
    ) -> dict[str, Any] | None:
        """Return frontend data for a single group, or None."""
        frontend_data = self.get_share_content_as_frontend_data(share_contents)
        return frontend_data[0] if frontend_data else None

    @transaction.atomic
    def replace_share_planning(
        self,
        *,
        year: int,
        delivery_week: int,
        share_article_id: str,
        unit: str,
        size: str,
        data: dict[str, Any],
    ) -> list[ShareContent]:
        """Replace existing ShareContent rows for the (year, week, article, unit, size)
        slot with freshly-created rows from `data`, then cascade snapshots for any
        movements affected by the deletion.

        Empty payloads (``data`` carrying no usable day-variation cells —
        the user cleared every amount on the row) split into two cases:

        * Forecast-attached rows are KEPT, with ``amount`` reset to
          ``None``. The forecast is still asking for this row to exist;
          clearing the cells means "no human plan yet", not "remove the
          row". This preserves the row in the planning list so the user
          can fill it later.
        * Ad-hoc rows (no forecast link) are DELETED, since their only
          reason to exist was the human-typed amount that's now gone.

        Non-empty payloads keep the original wipe-and-rebuild semantics.
        """
        from .snapshot_service import SnapshotService
        from .theoretical_objects import recalculate_actual_corrections

        data = {**data, "share_article": share_article_id, "unit": unit, "size": size}

        existing_shares = Share.objects.filter(year=year, delivery_week=delivery_week)
        slot_filter = {
            "share__in": existing_shares,
            "share_article__id": share_article_id,
            "size": size,
            "unit": unit,
        }
        old_share_contents = ShareContent.objects.filter(**slot_filter)
        # Capture BOTH movement halves before the delete: the SHARECONTENT rows
        # AND the theoretical HARVEST/PURCHASE/WASH/CLEAN movements (these carry
        # share_content=NULL, reached via their Theoretical* parent's
        # share_content link). The wipe cascades the theoreticals away, so a
        # storage dimension this slot uniquely fed must still be re-cascaded and
        # its actual correction re-derived (mirrors delete_share_planning).
        old_movements = list(
            MovementShareArticle.objects.for_share_contents(old_share_contents)
        )

        day_variations = self._extract_day_variations(data)

        # Accumulate every movement the replace touches (the rebuild's new
        # movements, re-derived corrections, AND the captured old set) and
        # cascade ONCE — a single sorted ``current_balance:*`` advisory-lock
        # pass for the whole transaction instead of one pass per step.
        deferred_movements: list[MovementShareArticle] = []

        if not day_variations:
            # User cleared every cell. Spare forecast-attached rows so
            # the row stays visible (amount=None == "no human plan"); drop
            # the ad-hoc ones whose only purpose was the now-cleared
            # amount.
            affected_share_ids = set(
                old_share_contents.values_list("share_id", flat=True)
            )
            old_share_contents.filter(forecast__isnull=True).delete()
            old_share_contents.filter(forecast__isnull=False).update(amount=None)
            # The spared forecast rows now carry amount=None but still hold
            # theoreticals + SHARECONTENT movements built off the old
            # non-zero amount. Rebuild them so the cleared cells stop
            # contributing harvest/production demand, THEN cascade stock
            # snapshots — snapshots must be recomputed last, after the
            # movement set is corrected (mirrors the wipe-and-rebuild path).
            if affected_share_ids:
                from .recompute import recompute_shares

                recompute_shares(
                    affected_share_ids, collect_movements=deferred_movements
                )
            if old_movements:
                deferred_movements.extend(old_movements)
                # recompute_shares only re-derives the SURVIVING contents'
                # dimensions; a dropped ad-hoc row's uniquely-fed theoretical
                # storage (e.g. its own wash/clean storage) would keep a stale
                # actual correction. Re-derive over the captured 5-way set.
                recalculate_actual_corrections(
                    old_movements, collect_movements=deferred_movements
                )
            if deferred_movements:
                SnapshotService.cascade_for_movements(deferred_movements)
            # Re-fetch what survived so the response shows the cleared
            # forecast scaffold to the frontend.
            return list(ShareContent.objects.filter(**slot_filter))

        # Preserve the backup plan across the wipe-and-rebuild. It lives on
        # ShareContent (backup_share_article/unit/size + backup_amount), but the
        # rebuild from ``data`` carries only the MAIN amounts — so without this,
        # editing any cell silently drops the row's whole backup plan. Key it by
        # the ShareContent's own identity within the slot, ``(share,
        # delivery_station)`` (its unique constraint), so a PER-STATION backup is
        # preserved exactly rather than collapsed onto a single value.
        preserved_backup: dict[tuple[str, str | None], tuple[Any, ...]] = {}
        for old in old_share_contents:
            if old.backup_share_article_id or old.backup_amount:
                preserved_backup[(old.share_id, old.delivery_station_id)] = (
                    old.backup_share_article_id,
                    old.backup_unit,
                    old.backup_size,
                    old.backup_amount,
                )

        old_share_contents.delete()
        share_contents = self.process_share_planning_data(
            data, collect_movements=deferred_movements
        )

        # Re-stamp each rebuilt row from its matching (share, delivery_station).
        if preserved_backup:
            to_restamp = []
            for sc in share_contents:
                backup = preserved_backup.get((sc.share_id, sc.delivery_station_id))
                if backup is None:
                    continue
                (
                    sc.backup_share_article_id,
                    sc.backup_unit,
                    sc.backup_size,
                    sc.backup_amount,
                ) = backup
                to_restamp.append(sc)
            if to_restamp:
                ShareContent.objects.bulk_update(
                    to_restamp,
                    [
                        "backup_share_article",
                        "backup_unit",
                        "backup_size",
                        "backup_amount",
                    ],
                )

        if old_movements:
            deferred_movements.extend(old_movements)
            recalculate_actual_corrections(
                old_movements, collect_movements=deferred_movements
            )
        if deferred_movements:
            SnapshotService.cascade_for_movements(deferred_movements)

        return share_contents

    @transaction.atomic
    def delete_share_planning(
        self,
        *,
        year: int,
        delivery_week: int,
        share_article_id: str,
        unit: str,
        size: str,
    ) -> int:
        """Delete ShareContent rows matching the slot and cascade snapshots.

        Returns the number of deleted rows. Raises `ShareContentNotFound` if no
        rows match.
        """
        from .snapshot_service import SnapshotService

        existing_shares = Share.objects.filter(year=year, delivery_week=delivery_week)
        share_contents = ShareContent.objects.filter(
            share__in=existing_shares,
            share_article__id=share_article_id,
            unit=unit,
            size=size,
        )

        if not share_contents.exists():
            raise ShareContentNotFound(
                "No share content found for the given parameters"
            )

        # Capture BOTH movement halves before the cascade-delete: the
        # SHARECONTENT rows AND the theoretical HARVEST/PURCHASE/WASH/CLEAN
        # movements (share_content=NULL, linked via their Theoretical* parent).
        # Deleting the content cascade-kills the theoretical rows + movements, so
        # a dimension whose theoreticals vanish would keep a stale actual
        # correction (entity total ≠ counted) — mirror recompute_for_share_contents.
        from .theoretical_objects import recalculate_actual_corrections

        affected_movements = list(
            MovementShareArticle.objects.for_share_contents(share_contents)
        )
        deleted_count = share_contents.count()
        share_contents.delete()

        if affected_movements:
            SnapshotService.cascade_for_movements(affected_movements)
            recalculate_actual_corrections(affected_movements)

        return deleted_count

    @transaction.atomic
    def update_backup_fields(
        self,
        *,
        year: int,
        delivery_week: int,
        share_article_id: str,
        unit: str,
        size: str,
        data: dict[str, Any],
    ) -> QuerySet[ShareContent]:
        """Update backup_* fields on ShareContent rows for the given slot.

        `data` may contain `backup_share_article`, `backup_unit`, `backup_size`,
        and `day_{day_id}_variation_{var_id}` per-row backup amounts.
        Raises `ShareContentNotFound` if no rows match, or `ShareArticleNotFound`
        if the backup share article is invalid.
        """
        existing_shares = Share.objects.filter(year=year, delivery_week=delivery_week)
        share_contents = ShareContent.objects.filter(
            share__in=existing_shares,
            share_article__id=share_article_id,
            unit=unit,
            size=size,
        ).select_related("share")

        if not share_contents.exists():
            raise ShareContentNotFound(
                "No share content found for the given parameters"
            )

        backup_share_article_id = data.get("backup_share_article")
        backup_share_article = None
        if backup_share_article_id:
            try:
                backup_share_article = ShareArticle.objects.get(
                    id=backup_share_article_id
                )
            except ShareArticle.DoesNotExist as exc:
                raise ShareArticleNotFound(
                    f"ShareArticle {backup_share_article_id} not found"
                ) from exc

        backup_unit = data.get("backup_unit") or None
        backup_size = data.get("backup_size") or None

        backup_amounts: dict[tuple[str, str], Decimal] = {}
        for key, value in data.items():
            match = DAY_VARIATION_RE.match(key)
            if not match:
                continue
            day_id = match.group(1)
            var_id = match.group(2)
            if not value:
                # Falsy (0 / "" / None) means "no backup planned" — store 0.
                backup_amounts[(day_id, var_id)] = Decimal(0)
                continue
            backup_amounts[(day_id, var_id)] = parse_amount_cell(value, field=key)

        for share_content in share_contents:
            share_content.backup_share_article = backup_share_article
            share_content.backup_unit = backup_unit
            share_content.backup_size = backup_size

            day_id = str(share_content.share.delivery_day_id)
            var_id = str(share_content.share.share_type_variation_id)
            share_content.backup_amount = backup_amounts.get(
                (day_id, var_id), Decimal(0)
            )
            share_content.save(
                update_fields=[
                    "backup_share_article",
                    "backup_unit",
                    "backup_size",
                    "backup_amount",
                ]
            )

        return share_contents

    def variation_totals_by_week(
        self, share_contents: list[ShareContent]
    ) -> dict[tuple[int, int], dict]:
        """Demand totals for every (year, week) covered by ``share_contents``
        — ONE aggregated query per year (in practice: one) instead of 2-3
        per week. Keyed ``{(year, week): {"basic"|"tour"|"station": {...}}}``.

        Uses the union of variations across the year's weeks; a week where
        a variation has no demand simply has no lookup entry, which every
        consumer already treats as 0.
        """
        weeks_by_year: dict[int, set[int]] = defaultdict(set)
        variation_ids_by_year: dict[int, set] = defaultdict(set)
        for share_content in share_contents:
            weeks_by_year[share_content.share.year].add(
                share_content.share.delivery_week
            )
            variation_ids_by_year[share_content.share.year].add(
                share_content.share.share_type_variation_id
            )

        totals: dict[tuple[int, int], dict] = {}
        for year, weeks in weeks_by_year.items():
            physical_variations = list(
                ShareTypeVariation.objects.filter(
                    id__in=variation_ids_by_year[year],
                    variation_type="physical",
                )
            )
            if not physical_variations:
                continue
            week_totals = batch_get_physical_variation_totals_for_weeks(
                physical_variations, year, sorted(weeks)
            )
            for week, lookups in week_totals.items():
                totals[(year, week)] = lookups
        return totals

    @staticmethod
    def _total_quantity_for(
        share_content: ShareContent,
        variation_totals_by_week: dict[tuple[int, int], dict],
    ) -> int:
        """The subscribed-share quantity this content's amount is multiplied by.

        Station-scoped contents key into the ``"station"`` bucket (day,
        variation, station); basic contents into ``"basic"`` (day, variation).
        This is THE keying contract between the theoretical builder and the
        SHARECONTENT movement builder — both MUST resolve the identical
        quantity for a row or planned harvest and packed stock silently
        diverge, so it lives in exactly one place.
        """
        week_totals = variation_totals_by_week.get(
            (share_content.share.year, share_content.share.delivery_week), {}
        )
        if share_content.delivery_station_id:
            return week_totals.get("station", {}).get(
                (
                    share_content.share.delivery_day_id,
                    share_content.share.share_type_variation_id,
                    share_content.delivery_station_id,
                ),
                0,
            )
        return week_totals.get("basic", {}).get(
            (
                share_content.share.delivery_day_id,
                share_content.share.share_type_variation_id,
            ),
            0,
        )

    @transaction.atomic
    def create_all_theoretical_objects(
        self,
        share_contents: list[ShareContent],
        variation_totals_by_week: dict[tuple[int, int], dict] | None = None,
        *,
        collect_movements: list[MovementShareArticle] | None = None,
    ) -> dict[str, list]:
        """Create all theoretical objects in a single optimized operation.

        ``variation_totals_by_week``: pass the precomputed result of
        :meth:`variation_totals_by_week` when calling this back-to-back
        with :meth:`create_movements` (as every caller does) — both need
        the identical lookup and computing it twice doubles the most
        expensive queries of the recompute path.

        ``collect_movements`` defers the snapshot cascade to the caller —
        see ``theoretical_objects.create_theoretical_objects``.
        """
        from .theoretical_objects import (
            TheoreticalSourceData,
            build_theoretical_objects_from_rows,
        )

        if variation_totals_by_week is None:
            variation_totals_by_week = self.variation_totals_by_week(share_contents)

        def build_source(share_content, short_term, long_term):
            total_quantity = self._total_quantity_for(
                share_content, variation_totals_by_week
            )

            storage = Storage.select_harvest(
                short_term=short_term,
                long_term=long_term,
                comes_from_long_term=share_content.comes_from_long_term_storage,
            )

            return TheoreticalSourceData(
                year=share_content.share.year,
                delivery_week=share_content.share.delivery_week,
                delivery_day=share_content.share.delivery_day.day_number,
                harvesting_day=share_content.share.harvesting_day,
                washing_day=share_content.share.washing_day,
                cleaning_day=share_content.share.cleaning_day,
                share_article=share_content.share_article,
                amount=share_content.amount,
                unit=share_content.unit,
                size=share_content.size,
                note=share_content.note,
                washing=share_content.washing,
                cleaning=share_content.cleaning,
                forecast=share_content.forecast,
                seller=share_content.seller,
                is_purchased=share_content.share_article.is_purchased,
                share_content=share_content,
                storage=storage,
                total_amount_for_shares=(
                    share_content.amount * total_quantity
                    if share_content.amount
                    else None
                ),
                # A linked Forecast must match the content's size (enforced by
                # ShareContent._validate_forecast_dimensions), so the harvest is
                # planned on the content's OWN size — the same dimension the
                # actual-harvest correction lands on, so the actual offsets the
                # theoretical instead of double-counting on a separate size.
                harvest_size=share_content.size,
                comes_from_long_term_storage=share_content.comes_from_long_term_storage,
            )

        return build_theoretical_objects_from_rows(
            share_contents, build_source, collect_movements=collect_movements
        )

    @transaction.atomic
    def create_movements(
        self,
        share_contents: list[ShareContent],
        variation_totals_by_week: dict[tuple[int, int], dict] | None = None,
        *,
        collect_movements: list[MovementShareArticle] | None = None,
    ) -> list[MovementShareArticle]:
        """Create MovementShareArticle objects with storage allocation.

        ``variation_totals_by_week``: see
        :meth:`create_all_theoretical_objects` — pass the shared
        precomputed lookup when calling both.

        ``collect_movements`` defers the snapshot cascade to the caller —
        see ``movements.create_movements``.
        """
        from .movements import MovementSourceData, create_movements

        sources: list[MovementSourceData] = []

        if variation_totals_by_week is None:
            variation_totals_by_week = self.variation_totals_by_week(share_contents)

        for share_content in share_contents:
            # A cleared forecast row carries amount=None ("no human plan yet" —
            # set by replace_share_planning when every cell is emptied). It
            # contributes no SHARECONTENT movement (nothing to move), and
            # Decimal(str(None)) below would raise InvalidOperation. The
            # theoretical builder keeps a None-total theoretical for the row;
            # movements simply skip it.
            if share_content.amount is None:
                continue

            packing_day = share_content.share.packing_day
            if packing_day is None:
                packing_day = share_content.share.delivery_day.day_number

            total_quantity = self._total_quantity_for(
                share_content, variation_totals_by_week
            )

            total_amount = abs(
                Decimal(str(share_content.amount)) * Decimal(str(total_quantity))
            )

            sources.append(
                MovementSourceData(
                    year=share_content.share.year,
                    delivery_week=share_content.share.delivery_week,
                    delivery_day=share_content.share.delivery_day.day_number,
                    packing_day=packing_day,
                    share_article=share_content.share_article,
                    unit=share_content.unit,
                    size=share_content.size,
                    amount=total_amount,
                    movement_type="SHARECONTENT",
                    share_content=share_content,
                )
            )

        return create_movements(sources, collect_movements=collect_movements)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_day_variations(
        data: dict[str, Any],
    ) -> list[tuple[str, str, Decimal, str | None, str | None]]:
        """Extract day-variation combinations from frontend data.

        The frontend's planning row carries up to THREE parallel
        representations of the same data per ``(day, variation)``:

          * ``day_X_variation_Y``                 → bare row-level
                                                    amount (sum
                                                    across stations
                                                    /tours)
          * ``day_X_variation_Y_tour_N``          → per-tour amount
          * ``day_X_variation_Y_station_Z``       → per-station amount

        Depending on the active planning mode the form often
        propagates the user's single typed value into ALL three
        slots (so the row total displays consistently). If the
        backend trusts every slot, the bare entry collides with the
        specifics, AND a tour entry expands to all stations on that
        tour and collides with any explicit station entry — the
        downstream ``(share, station)`` dedupe in
        ``create_share_contents`` then raises "Duplicate planning
        entry …".

        Resolution: per ``(day, variation)`` group, pick the MOST
        SPECIFIC representation that was actually sent and drop the
        rest. Precedence:

            1. station-specific  (most precise — names a single
               delivery station explicitly)
            2. tour-specific     (mid — names a tour, fans to all
               stations on that tour)
            3. bare              (least — no tour or station,
               fans to every station on the day)

        Only the highest tier present in the group is emitted; the
        lower tiers are dropped as redundant.

        Zero-amount entries are also dropped at the source. ``0``
        semantically means "no plan for this tour/station", NOT
        "plan zero share content" — the frontend ships a zero-
        filled scaffold for every tour and station on every row
        regardless of what the user actually touched, and treating
        those zeros as real entries would (a) spawn phantom
        ``ShareContent`` rows and (b) re-introduce the station-
        collision symptom this dedupe was added to prevent.
        """
        # Walk once to collect every match. Track per-group whether
        # we saw any station-specific entry and whether we saw any
        # tour-specific entry, so the second pass knows which tier
        # to keep.
        all_entries: list[tuple[str, str, Decimal, str | None, str | None]] = []
        has_station_for_group: dict[tuple[str, str], bool] = {}
        has_tour_for_group: dict[tuple[str, str], bool] = {}

        for key, value in data.items():
            match = DAY_VARIATION_RE.match(key)
            if not match:
                continue

            if value is None or value == "" or value == "undefined":
                continue

            # Surface bad input as a 400 with the offending key — including the
            # well-formed-but-not-a-number strings "NaN"/"Infinity" — rather
            # than silently dropping it (the user sees "saved" but the row is
            # missing) or storing a garbage Decimal.
            amount = parse_amount_cell(value, field=key)

            # See docstring: zero is the scaffold default, never a
            # real plan.
            if amount == 0:
                continue

            day = match.group(1)
            variation = match.group(2)
            sub_type = match.group(3)
            sub_id = match.group(4)

            tour = sub_id if sub_type == "tour" else None
            station = sub_id if sub_type == "station" else None

            group_key = (day, variation)
            if station is not None:
                has_station_for_group[group_key] = True
            elif tour is not None:
                has_tour_for_group[group_key] = True

            all_entries.append((day, variation, amount, tour, station))

        # Second pass: emit only the highest-specificity tier present
        # for each (day, variation) group.
        day_variations: list[tuple[str, str, Decimal, str | None, str | None]] = []
        for entry in all_entries:
            day, variation, _amount, tour, station = entry
            group_key = (day, variation)

            if has_station_for_group.get(group_key):
                # Stations-tier group → keep ONLY station entries.
                if station is None:
                    continue
            elif has_tour_for_group.get(group_key):
                # Tours-tier group → keep ONLY tour entries.
                if tour is None:
                    continue
            # else: bare-only group → keep the bare entries.

            day_variations.append(entry)

        return day_variations

    @staticmethod
    def _get_share_article(share_article_id: str) -> ShareArticle:
        """Get ShareArticle by ID."""
        try:
            return ShareArticle.objects.get(id=share_article_id)
        except ShareArticle.DoesNotExist as exc:
            raise ShareArticleNotFound(
                f"ShareArticle with id {share_article_id} does not exist",
                details={"share_article_id": share_article_id},
            ) from exc

    @staticmethod
    def _get_kg_per_piece_with_fallback(share_content: ShareContent) -> Decimal | None:
        """Return kg_per_piece from share_content or fall back to share_article."""
        if share_content.kg_per_piece is not None:
            return share_content.kg_per_piece
        if share_content.unit == "PCS" and share_content.size:
            # ``size`` is enum-constrained (S/M/L) and ShareArticle has
            # a matching ``kg_per_piece_<size>`` for each — no default
            # needed. A typo or unexpected size value should crash here
            # rather than silently return None and feed wrong weights
            # into theoretical-harvest / pricing math.
            field_name = f"kg_per_piece_{share_content.size}"
            return getattr(share_content.share_article, field_name)
        return None

    @staticmethod
    def _get_price_per_unit_with_fallback(
        share_content: ShareContent,
        year: int,
        delivery_week: int,
        pricing_cache: dict[tuple, object] | None = None,
    ) -> Decimal | None:
        """Return price_per_unit from share_content or fall back to active pricing."""
        if share_content.price_per_unit is not None:
            return share_content.price_per_unit
        cache_key = (share_content.share_article_id, year, delivery_week)
        if pricing_cache is not None and cache_key in pricing_cache:
            pricing = pricing_cache[cache_key]
        else:
            tuesday = Week(year, delivery_week).tuesday()
            pricing = share_content.share_article.get_pricing_on_date(tuesday)
        if pricing is None:
            return None
        unit_price_map = {
            "KG": pricing.net_price_for_boxes_kg,
            "PCS": pricing.net_price_for_boxes_pieces,
            "BUNCH": pricing.net_price_for_boxes_bunch,
        }
        return unit_price_map.get(share_content.unit)
