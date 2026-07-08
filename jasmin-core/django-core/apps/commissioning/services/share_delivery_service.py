from __future__ import annotations

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
