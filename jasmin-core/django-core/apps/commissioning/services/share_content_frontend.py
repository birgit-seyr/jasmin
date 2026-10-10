"""The share-content planning page's data: share contents shaped into grid
rows with their forecasts, stock and prices, and the purchase cost per week."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import QuerySet
from isoweek import Week

from apps.shared.money import round_money

from ..models import (
    DeliveryStationDay,
    Forecast,
    ShareArticle,
    ShareContent,
    ShareTypeVariation,
)
from ..models.choices import UnitOptions
from ..utils import sort_share_articles
from ..utils.composite_id_utils import compose_slot_id
from ..utils.iso_week_utils import (
    previous_day_stock_coordinates,
    previous_monday,
    weeks_in_range,
)
from .share_content_stock import ShareContentStock
from .stock_service import StockService


class ShareContentFrontendData(ShareContentStock):
    """Reads for the share-content planning page."""

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
        option_by_variation = self._prefetch_share_options(all_share_contents)
        tour_number_lookup = self._prefetch_tour_numbers(all_share_contents)
        stock_by_week = self._prefetch_stock_by_week(all_share_contents)
        # One aggregated query for the whole set instead of 2-3 per week.
        variation_totals_by_week = self.variation_totals_by_week(all_share_contents)
        pricing_cache = self._prefetch_pricing_cache(all_share_contents)

        grouped_data: dict[tuple, dict[str, Any]] = {}
        for share_content in all_share_contents:
            share = share_content.share
            slot_key = (
                share.year,
                share.delivery_week,
                share_content.share_article_id,
                share_content.unit,
                share_content.size,
            )
            # A row is one share option's slot: an article can belong to three.
            share_option = option_by_variation[share.share_type_variation_id]
            group_key = (*slot_key, share_option)
            if group_key not in grouped_data:
                grouped_data[group_key] = self._init_frontend_group_row(
                    share_content,
                    share_option=share_option,
                    forecast=forecast_by_key.get(slot_key),
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
    def _prefetch_share_options(
        all_share_contents: list[ShareContent],
    ) -> dict[str, str | None]:
        """The share option of every variation the contents are planned for —
        one query instead of one per group; None for a share type without
        one."""
        variation_ids = {
            share_content.share.share_type_variation_id
            for share_content in all_share_contents
        }
        return dict(
            ShareTypeVariation.objects.filter(id__in=variation_ids).values_list(
                "id", "share_type__share_option"
            )
        )

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
            share_content.delivery_station_id for share_content in all_share_contents
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
        share_option: str | None,
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
            "id": compose_slot_id(
                share.year,
                share.delivery_week,
                share_article.id,
                share_content.unit,
                share_content.size,
                share_option=share_option,
            ),
            "year": share.year,
            "delivery_week": share.delivery_week,
            "share_article": share_article.id,
            "share_article_name": share_article.name,
            # Per-article buffer % for the commissioning-list PACKING view — the
            # picker grabs this much extra to cover spoilage. Surfaced on the row
            # (harmless to the harvest-planning grid, which ignores it) and
            # applied to the displayed amount client-side in CommissioningListPacking.
            "percentage_added_to_commissioning_list_packing": (
                share_article.percentage_added_to_commissioning_list_packing
            ),
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
            "seller": share_content.seller_id,
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
            "backup_share_article": share_content.backup_share_article_id,
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

        if share_content.amount:
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

        station_key = f"{base_key}_station_{share_content.delivery_station_id}"
        group_row["variations"][station_key] = amount_str

        tour_number = tour_number_lookup.get(
            (share_content.delivery_station_id, share.delivery_day_id)
        )
        # Tour 0 is a real tour (the field allows it and the save path writes
        # its cells); only a station with no station day that day has no tour.
        if tour_number is not None:
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
                    inventory_note = (values.get("note") or "").strip()
                    if inventory_note:
                        collected_notes.append(inventory_note)
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
        > 0 → blue) and can be edited like any other row — saving one
        updates its slot, which has no rows yet, so real ShareContent
        is created.
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

    def purchase_cost_by_week(
        self,
        start_date: date,
        end_date: date,
        *,
        is_past: bool = True,
    ) -> list[dict[str, Any]]:
        """Total money spent buying in purchased ("Zukauf") share articles, per
        ISO week over ``[start_date, end_date]``.

        Reproduces the harvest-share-planning page's per-week purchase figure —
        ``Σ over purchased ShareContent of price_per_unit × amount ×
        variation_demand`` — but aggregated server-side so only the per-week
        points cross the wire. Money stays Decimal end to end and is quantized
        to 2dp; a week with no purchases yields ``0``. ``is_past=True`` (the
        default — this report inherently spans past weeks) bypasses the archive
        cutoff so historical weeks are included.

        Import-mode tenants are handled transparently: the demand lookup routes
        through ``variation_totals_by_week`` → ``ShareDemandService``, which
        resolves ``ExternalShareDemand`` instead of ``ShareDelivery``.
        """
        # Snap the start back to its Monday so ``weeks_in_range``'s 7-day walk
        # lands on every week's Monday — an arbitrary (non-Monday) start could
        # otherwise skip the range's final partial week.
        weeks = weeks_in_range(previous_monday(start_date), end_date)
        if not weeks:
            return []

        years = {year for year, _ in weeks}
        week_numbers = {week for _, week in weeks}

        share_contents = [
            share_content
            for share_content in ShareContent.active.for_period(is_past=is_past)
            .filter(
                share__year__in=years,
                share__delivery_week__in=week_numbers,
                share_article__is_purchased=True,
            )
            .select_related(
                "share__share_type_variation",
                "share__delivery_day",
                "share_article",
            )
            # A plain (years × weeks) cross-product over-selects at year
            # boundaries — keep only the weeks actually in the range.
            if (share_content.share.year, share_content.share.delivery_week) in weeks
        ]

        # One batched demand scan for the whole span (backend-agnostic:
        # subscription or external demand), plus the missing-price fallback.
        variation_totals_by_week = self.variation_totals_by_week(share_contents)
        pricing_cache = self._prefetch_pricing_cache(share_contents)

        cost_by_week: dict[tuple[int, int], Decimal] = defaultdict(lambda: Decimal("0"))
        for share_content in share_contents:
            if not share_content.amount:
                continue
            quantity = self._total_quantity_for(share_content, variation_totals_by_week)
            if not quantity:
                continue
            year = share_content.share.year
            week = share_content.share.delivery_week
            price = self._get_price_per_unit_with_fallback(
                share_content, year, week, pricing_cache
            )
            if price is None:
                continue
            cost_by_week[(year, week)] += price * share_content.amount * quantity

        # Emit EVERY week in the range (0 where nothing was purchased) so the
        # bar chart has a continuous week axis, ordered chronologically.
        return [
            {
                "year": year,
                "week": week,
                "amount": str(round_money(cost_by_week[(year, week)])),
            }
            for year, week in sorted(weeks)
        ]

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
        the row blue — and saving an amount updates the row's slot of
        ``share_option``, creating its first ``ShareContent``.

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
        for (share_article_id, unit, size, _storage), values in stock_data.items():
            key = (str(share_article_id), unit, size)
            if key in seen_keys:
                continue
            counted = values.get("current_stock_amount")
            theoretical = values.get("theoretical_current_stock") or 0
            if counted is not None:
                stock_value = Decimal(str(counted))
                inventory_note = (values.get("note") or "").strip()
            else:
                stock_value = Decimal(str(theoretical))
                inventory_note = ""
            if stock_value <= 0:
                continue
            agg = aggregates.setdefault(
                key,
                {"stock_value": Decimal("0"), "notes": [], "any_counted": False},
            )
            agg["stock_value"] += stock_value
            if counted is not None:
                agg["any_counted"] = True
                if inventory_note:
                    agg["notes"].append(inventory_note)

        if not aggregates:
            return []

        # Only synthesize stock rows for articles actually assigned to this
        # share option (``share_option`` / ``share_option2`` / ``share_option3``
        # on ShareArticle). Otherwise leftover stock of e.g. broccoli would
        # surface as a row when planning honey shares. Articles not in this set
        # are dropped by the ``share_article is None`` guard below.
        from django.db.models import Q

        article_qs = ShareArticle.objects.filter(
            id__in={share_article_id for (share_article_id, _, _) in aggregates}
        )
        if share_option:
            article_qs = article_qs.filter(
                Q(share_option=share_option)
                | Q(share_option2=share_option)
                | Q(share_option3=share_option)
            )
        share_articles_by_id = {
            str(share_article.id): share_article for share_article in article_qs
        }

        rows: list[dict[str, Any]] = []
        for (share_article_id, unit, size), agg in aggregates.items():
            share_article = share_articles_by_id.get(share_article_id)
            if share_article is None:
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
                    "id": compose_slot_id(
                        year,
                        delivery_week,
                        share_article.id,
                        unit,
                        size,
                        share_option=share_option,
                    ),
                    "year": year,
                    "delivery_week": delivery_week,
                    "share_article": share_article.id,
                    "share_article_name": share_article.name,
                    "kg_per_piece_S": share_article.kg_per_piece_S,
                    "kg_per_piece_M": share_article.kg_per_piece_M,
                    "kg_per_piece_L": share_article.kg_per_piece_L,
                    "kg_per_bunch_S": share_article.kg_per_bunch_S,
                    "kg_per_bunch_M": share_article.kg_per_bunch_M,
                    "kg_per_bunch_L": share_article.kg_per_bunch_L,
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

    @staticmethod
    def _get_kg_per_piece_with_fallback(share_content: ShareContent) -> Decimal | None:
        """Return kg_per_piece from share_content or fall back to share_article."""
        if share_content.kg_per_piece is not None:
            return share_content.kg_per_piece
        if share_content.unit == UnitOptions.PCS and share_content.size:
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
            UnitOptions.KG: pricing.net_price_for_boxes_kg,
            UnitOptions.PCS: pricing.net_price_for_boxes_pieces,
            UnitOptions.BUNCH: pricing.net_price_for_boxes_bunch,
        }
        return unit_price_map.get(share_content.unit)
