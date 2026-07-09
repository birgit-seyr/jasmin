from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from django.db.models import QuerySet

from ..models import (
    SharesDeliveryDay,
    ShareType,
    ShareTypeVariation,
)
from ..utils.iso_week_utils import saturday_of_iso_week
from .share_demand_service import ShareDemandService


class ShareDeliveryService:
    @staticmethod
    def get_variation_delivery_counts(
        share_type_id: str,
        year: int,
        delivery_week: int,
        manual: bool | None = None,
        for_tours: bool | None = None,
        for_stations: bool | None = None,
        joker: bool | None = None,
    ) -> list[dict[str, Any]]:
        """
        Return per-variation delivery counts broken down by delivery day,
        optionally further split by tour or station.

        Each result row contains identifying fields plus dynamic
        ``amount_day_<day_id>[_tour_<n>|_station_<id>]`` keys.

        Import-safety (load-bearing): the counts come from
        ``ShareDemandService.aggregated_rows`` — the demand PORT — NEVER from a
        direct ``ShareDelivery`` query. For external-CSV (import) tenants
        (``uploads_weekly_share_amount=True``) there are ZERO ``ShareDelivery``
        rows and demand lives in ``ExternalShareDemand``, so a "simplification"
        that reads ``ShareDelivery`` directly here would silently return
        all-zero counts and blank the AmountShares grid for those tenants. This
        service/viewset are named ``ShareDelivery*`` because they mostly serve
        ShareDeliveries — but THIS method is deliberately backend-agnostic; keep
        it routed through ``ShareDemandService``. (Locked by
        ``test_share_delivery_service.py::…::test_import_mode_reads_external_demand``.)

        ``joker``: ``False``/omitted = shipping-only (the AmountShares grid's
        default view), ``True`` = jokered-only. The underlying
        ``ShareDemandService.aggregated_rows`` is tri-state (``None`` = both),
        but this entry deliberately normalises ``None`` to ``False`` — a
        caller wanting the combined view uses ``aggregated_rows`` directly.
        """
        # Deliberate single normalisation (was previously re-collapsed inside
        # each per-day/tour/station helper): default view = shipping-only.
        joker = bool(joker)

        share_type_obj = ShareType.objects.get(id=share_type_id)

        active_at_date = saturday_of_iso_week(year, delivery_week)

        active_delivery_days = SharesDeliveryDay.current.active_at_date(
            active_at_date
        ).order_by("day_number")

        # Order by ``sort_order`` so the rows on AmountShares.tsx match
        # the office's configured display order. ``id`` is the
        # tiebreaker for stability when two variations share the same
        # sort_order (the modal's uniqueness check should prevent that,
        # but keep the fallback deterministic for legacy data).
        variations = (
            ShareTypeVariation.current.active_at_date(active_at_date)
            .filter(share_type=share_type_obj)
            .order_by("sort_order", "id")
        )

        result: list[dict[str, Any]] = []

        for variation in variations:
            row = _variation_header(share_type_obj, variation)

            if for_tours:
                _add_tour_counts(
                    row,
                    variation,
                    active_delivery_days,
                    active_at_date,
                    year,
                    delivery_week,
                    joker,
                )
            elif for_stations:
                _add_station_counts(
                    row,
                    variation,
                    active_delivery_days,
                    active_at_date,
                    year,
                    delivery_week,
                    joker,
                )
            else:
                _add_day_counts(
                    row,
                    variation,
                    active_delivery_days,
                    year,
                    delivery_week,
                    joker,
                )

            result.append(row)

        return result

    @staticmethod
    def get_weekly_variation_count_matrix(
        year: int,
        delivery_week: int,
        mode: str = "day",
    ) -> dict[str, Any]:
        """Whole-week per-variation count matrix for AmountShares on IMPORT
        (external-demand) tenants — the flat sibling of
        ``PackingListBoxesMatrixService.get_weekly_combination_matrix``.

        ROWS are the week's delivery days (or day × tour / day × station);
        COLUMNS are one per ``share_type_variation`` (empty ``add_ons``, so they
        render through the SAME ``useBoxCombinationColumns`` as the box
        combinations, keyed ``variation_<id>``); each cell is the number of that
        variation shipping in the row's scope. Counts come from the demand PORT
        (``ShareDemandService``), so this stays correct for external-CSV tenants
        that have no ``ShareDelivery`` rows.
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
            joker=False,
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _variation_header(
    share_type: ShareType, variation: ShareTypeVariation
) -> dict[str, Any]:
    return {
        "id": variation.id,
        "share_type_id": share_type.id,
        "share_type_name": share_type.name,
        "share_type_variation_id": variation.id,
        "share_type_variation_size": variation.size,
    }


def _add_tour_counts(
    row: dict[str, Any],
    variation: ShareTypeVariation,
    delivery_days: QuerySet,
    active_at_date: date,
    year: int,
    delivery_week: int,
    joker: bool | None,
) -> None:
    rows = ShareDemandService.aggregated_rows(
        year=year,
        delivery_week=delivery_week,
        delivery_day_ids=list(delivery_days.values_list("id", flat=True)),
        variation_id=variation.id,
        joker=joker,
    )
    for entry in rows:
        if entry["tour_number"] is None:
            continue
        row[f"amount_day_{entry['day_id']}_tour_{entry['tour_number']}"] = entry[
            "count"
        ]


def _add_station_counts(
    row: dict[str, Any],
    variation: ShareTypeVariation,
    delivery_days: QuerySet,
    active_at_date: date,
    year: int,
    delivery_week: int,
    joker: bool | None,
) -> None:
    rows = ShareDemandService.aggregated_rows(
        year=year,
        delivery_week=delivery_week,
        delivery_day_ids=list(delivery_days.values_list("id", flat=True)),
        variation_id=variation.id,
        joker=joker,
    )
    # ``aggregated_rows`` is grouped by station_day; collapse to station.
    bucket: dict[tuple, int] = {}
    for entry in rows:
        if entry["station_id"] is None:
            continue
        key = (entry["day_id"], entry["station_id"])
        bucket[key] = bucket.get(key, 0) + entry["count"]
    for (day_id, station_id), total in bucket.items():
        row[f"amount_day_{day_id}_station_{station_id}"] = total


def _add_day_counts(
    row: dict[str, Any],
    variation: ShareTypeVariation,
    delivery_days: QuerySet,
    year: int,
    delivery_week: int,
    joker: bool | None,
) -> None:
    rows = ShareDemandService.aggregated_rows(
        year=year,
        delivery_week=delivery_week,
        delivery_day_ids=list(delivery_days.values_list("id", flat=True)),
        variation_id=variation.id,
        joker=joker,
    )
    # Collapse rows (which are per station_day) to per day.
    per_day: dict[object, int] = {}
    for entry in rows:
        per_day[entry["day_id"]] = per_day.get(entry["day_id"], 0) + entry["count"]
    for day_id, total in per_day.items():
        row[f"amount_day_{day_id}"] = total
