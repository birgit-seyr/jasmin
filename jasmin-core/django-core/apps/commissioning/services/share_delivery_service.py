from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..models import (
    SharesDeliveryDay,
    ShareTypeVariation,
)
from ..utils.iso_week_utils import saturday_of_iso_week
from .share_demand_service import ShareDemandService


class ShareDeliveryService:
    @staticmethod
    def get_weekly_variation_count_matrix(
        year: int,
        delivery_week: int,
        mode: str = "day",
        joker: bool = False,
        donation_joker: bool = False,
    ) -> dict[str, Any]:
        """Whole-week per-variation count matrix for AmountShareTypeVariations on
        IMPORT (external-demand) tenants — the flat sibling of
        ``PackingListBoxesMatrixService.get_weekly_combination_matrix``.

        ROWS are the week's delivery days (or day × tour / day × station);
        COLUMNS are one per ``share_type_variation`` (empty ``add_ons``, so they
        render through the SAME ``useBoxCombinationColumns`` as the box
        combinations, keyed ``variation_<id>``); each cell is the number of that
        variation shipping in the row's scope. Counts come from the demand PORT
        (``ShareDemandService``), so this stays correct for external-CSV tenants
        that have no ``ShareDelivery`` rows.

        ``joker=True`` requests the jokered counts instead of the shipping ones.
        Import (CSV) demand carries no joker information, so the demand port
        returns an empty result for those tenants — the joker view is simply
        blank there, which is correct.
        """
        from ..models import DeliveryStation
        from .packing_list_service import PackingListService

        active_at_date = saturday_of_iso_week(year, delivery_week)
        delivery_days = list(
            SharesDeliveryDay.current.active_at_date(active_at_date).order_by(
                "day_number"
            )
        )
        day_number_by_id = {day.id: day.day_number for day in delivery_days}
        variations = list(
            ShareTypeVariation.current.active_at_date(active_at_date).order_by(
                "sort_order", "id"
            )
        )
        variation_ids = {variation.id for variation in variations}
        if not variation_ids or not delivery_days:
            return {"columns": [], "rows": []}

        columns = PackingListService._member_amount_columns(
            variation_ids, active_at_date
        )

        demand = ShareDemandService.aggregated_rows(
            year=year,
            delivery_week=delivery_week,
            delivery_day_ids=[day.id for day in delivery_days],
            variation_ids=variation_ids,
            joker=joker,
            donation_joker=donation_joker,
        )

        station_name_by_id: dict[str, str | None] = {}
        if mode == "stations":
            station_ids = {
                entry["station_id"] for entry in demand if entry["station_id"]
            }
            station_name_by_id = dict(
                DeliveryStation.objects.filter(id__in=station_ids).values_list(
                    "id", "short_name"
                )
            )

        # scope (day_id, tour, station_id) -> {variation column key: count}
        scope_counts: defaultdict[tuple, defaultdict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        for entry in demand:
            if not entry["count"]:
                continue
            day_id = entry["day_id"]
            column_key = f"variation_{entry['variation_id']}"
            if mode == "tours":
                if entry["tour_number"] is None:
                    continue
                scope = (day_id, entry["tour_number"], None)
            elif mode == "stations":
                if entry["station_id"] is None:
                    continue
                scope = (day_id, None, entry["station_id"])
            else:
                scope = (day_id, None, None)
            scope_counts[scope][column_key] += entry["count"]

        rows: list[dict[str, Any]] = []
        for scope in sorted(
            scope_counts,
            key=lambda s: (
                day_number_by_id.get(s[0], 99),
                s[1] if s[1] is not None else -1,
                station_name_by_id.get(s[2]) or "",
            ),
        ):
            day_id, tour, station_id = scope
            if tour is not None:
                row_id = f"{day_id}_tour_{tour}"
            elif station_id is not None:
                row_id = f"{day_id}_station_{station_id}"
            else:
                row_id = str(day_id)
            row = {
                "id": row_id,
                "day_number": day_number_by_id.get(day_id),
                "tour": tour,
                "delivery_station_id": station_id,
                "delivery_station_name": (
                    station_name_by_id.get(station_id) if station_id else None
                ),
            }
            row.update(scope_counts[scope])
            rows.append(row)

        return {"columns": columns, "rows": rows}
