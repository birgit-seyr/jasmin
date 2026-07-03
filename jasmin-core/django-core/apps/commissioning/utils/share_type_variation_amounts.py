from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from ..models import (
    DeliveryStation,
    DeliveryStationDay,
    SharesDeliveryDay,
    ShareType,
    ShareTypeVariation,
    VirtualVariationComponent,
)


def _demand_service():
    """Lazy import to avoid utils ↔ services circular import."""
    from ..services.share_demand_service import ShareDemandService

    return ShareDemandService


def _aggregated_rows(
    *,
    year: int | None,
    delivery_week: int | None,
    delivery_day: SharesDeliveryDay | None,
    tour: int | None,
    delivery_station: DeliveryStation | None,
    variation_ids: Iterable[str] | None = None,
) -> list[dict]:
    """Thin wrapper around :meth:`ShareDemandService.aggregated_rows`.

    Always excludes joker deliveries (the historical behaviour of
    ``_build_base_queryset``).
    """
    return _demand_service().aggregated_rows(
        year=year,
        delivery_week=delivery_week,
        delivery_day_id=_to_id(delivery_day),
        delivery_station_id=_to_id(delivery_station),
        tour_number=tour,
        variation_ids=list(variation_ids) if variation_ids else None,
        joker=False,
    )


def _to_id(obj: Any) -> str | None:
    """Accept either a model instance or a raw id string."""
    if obj is None:
        return None
    return obj.id if hasattr(obj, "id") else obj


def _build_virtual_map(
    physical_variation_ids: Iterable[Any],
) -> dict[object, list[tuple[object, Decimal]]]:
    """``virtual_variation_id -> [(physical_variation_id, quantity)]`` for the
    given physical variations, in ONE query.

    Lets a single aggregated demand scan be resolved back into physical
    variations (a virtual variation's count is distributed to its physical
    components weighted by ``quantity``).
    """
    physical_ids = set(physical_variation_ids)
    virtual_map: dict[object, list[tuple[object, Decimal]]] = defaultdict(list)
    if not physical_ids:
        return virtual_map
    for virtual_component in VirtualVariationComponent.objects.filter(
        physical_variation_id__in=physical_ids
    ).select_related("virtual_variation"):
        virtual_map[virtual_component.virtual_variation_id].append(
            (virtual_component.physical_variation_id, virtual_component.quantity)
        )
    return virtual_map


def get_total_quantity_of_share_type_variations(
    share_option: str | None = None,
    share_type: ShareType | None = None,
    year: int | None = None,
    delivery_week: int | None = None,
    delivery_day: SharesDeliveryDay | None = None,
    tour: int | None = None,
    delivery_station: DeliveryStation | None = None,
) -> list[dict[str, Any]]:
    """Get total quantities grouped by share type variation (S, M, L, ...).

    Includes both physical and virtual variations.
    Excludes joker deliveries.
    """
    variation_qs = ShareTypeVariation.objects.all()
    if share_option is not None:
        variation_qs = variation_qs.filter(share_type__share_option=share_option)
    if share_type is not None:
        variation_qs = variation_qs.filter(share_type=share_type)

    variation_lookup = {v.id: v for v in variation_qs.only("id", "size")}
    if not variation_lookup:
        return []

    rows = _aggregated_rows(
        year=year,
        delivery_week=delivery_week,
        delivery_day=delivery_day,
        tour=tour,
        delivery_station=delivery_station,
        variation_ids=variation_lookup.keys(),
    )

    totals: dict[str, int] = defaultdict(int)
    for r in rows:
        if r["variation_id"] in variation_lookup:
            totals[r["variation_id"]] += int(r["count"] or 0)

    return sorted(
        (
            {
                "share__share_type_variation_id": variation_id,
                "share__share_type_variation__size": variation_lookup[
                    variation_id
                ].size,
                "total_quantity": total,
            }
            for variation_id, total in totals.items()
        ),
        key=lambda r: r["share__share_type_variation__size"] or "",
    )


def get_physical_share_type_variation_totals(
    share_type: ShareType | None = None,
    share_option: str | None = None,
    year: int | None = None,
    delivery_week: int | None = None,
    delivery_day: SharesDeliveryDay | None = None,
    tour: int | None = None,
    delivery_station: DeliveryStation | None = None,
) -> list[dict[str, Any]]:
    """
    Get total physical share_type_variations to pack, resolving virtual
    share_type_variations into their physical components.

    For each physical share_type_variation, sums direct subscriptions plus
    virtual share_type_variation subscriptions weighted by their component
    quantity.

    Returns:
        List of dicts with share_type_variation id, size, name and
        total_quantity.
    """
    filters: dict[str, Any] = {}
    if share_type is not None:
        filters["share_type"] = share_type
    if share_option is not None:
        filters["share_type__share_option"] = share_option

    physical_variations = list(
        ShareTypeVariation.objects.filter(variation_type="physical", **filters)
    )
    if not physical_variations:
        return []

    physical_ids = {physical_variation.id for physical_variation in physical_variations}

    # ONE VirtualVariationComponent query + ONE demand-aggregation query for
    # ALL variations at once, then aggregate per physical variation in Python.
    # (Previously this fired two queries PER physical variation — the full
    # week's demand was re-scanned for each one.) The day/tour/station filters
    # are pushed into the single aggregation query.
    virtual_map = _build_virtual_map(physical_ids)
    all_variation_ids = physical_ids | set(virtual_map.keys())

    rows = _aggregated_rows(
        year=year,
        delivery_week=delivery_week,
        delivery_day=delivery_day,
        tour=tour,
        delivery_station=delivery_station,
        variation_ids=all_variation_ids,
    )

    totals: dict[object, Decimal] = defaultdict(Decimal)
    for row in rows:
        var_id = row["variation_id"]
        count = Decimal(int(row["count"] or 0))
        if var_id in physical_ids:
            totals[var_id] += count
        # Virtual variations distribute their count to physical components.
        # (No-op for the external CSV backend — it only emits physical rows.)
        for physical_variation_id, qty in virtual_map.get(var_id, ()):
            totals[physical_variation_id] += count * qty

    return [
        {
            "share__share_type_variation_id": str(physical_variation.id),
            "share__share_type_variation__size": physical_variation.size,
            "share__share_type_variation__name": (
                physical_variation.name
                if hasattr(physical_variation, "name")
                else physical_variation.size
            ),
            "total_quantity": round(totals.get(physical_variation.id, Decimal(0))),
        }
        for physical_variation in physical_variations
    ]


def get_variation_quantity_for_station_day(
    station_day: DeliveryStationDay,
    year: int,
    delivery_week: int,
    variation: ShareTypeVariation,
) -> int:
    """
    Get total quantity for a variation at a specific station on a specific day.

    Filters by DeliveryStationDay (not just DeliveryStation).
    Excludes joker deliveries (cancelled/skipped).
    Does NOT include virtual variation components - counts direct subscriptions only.

    Args:
        station_day: DeliveryStationDay instance (specific station on specific day)
        year: Delivery year
        delivery_week: Delivery week number
        variation: ShareTypeVariation instance

    Returns:
        Total quantity of subscriptions

    Example:
        >>> get_variation_quantity_for_station_day(
        ...     station_day_obj,
        ...     2024,
        ...     10,
        ...     medium_veg_variation
        ... )
        12
    """
    # Routes through ``ShareDemandService`` so external-CSV tenants get
    # their counts from ``ExternalShareDemand`` instead of ``ShareDelivery``.
    return _demand_service().quantity_for_station_day(
        station_day_id=station_day.id,
        year=year,
        delivery_week=delivery_week,
        variation_id=variation.id,
    )


def get_variation_quantities_by_station_day(
    *, year: int, delivery_week: int, variation_ids: list[str]
) -> dict[tuple[str, str], int]:
    """Batch counterpart of :func:`get_variation_quantity_for_station_day`: the
    whole ``(station_day_id, variation_id) -> quantity`` grid in ONE query
    (routed through ``ShareDemandService`` so external-CSV tenants are covered).
    Replaces the per-cell N+1 in the delivery stations/tours overview."""
    if not variation_ids:
        return {}
    rows = _demand_service().aggregated_rows(
        year=year,
        delivery_week=delivery_week,
        variation_ids=list(variation_ids),
        joker=False,
    )
    return {(r["station_day_id"], r["variation_id"]): r["count"] for r in rows}


def batch_get_physical_variation_totals_for_weeks(
    physical_variations: Iterable[ShareTypeVariation] | Any,
    year: int,
    delivery_weeks: Iterable[int],
) -> dict[int, dict[str, dict[tuple, int]]]:
    """
    Batch-compute all variation totals for MANY weeks in 2 queries total —
    instead of 2-3 queries per week. This is the recompute hot path: a
    default-share-content save spans a whole season of weeks.

    Returns ``{delivery_week: {"basic": ..., "tour": ..., "station": ...}}``
    with the same three lookup dicts per week as the single-week variant:
    - "basic": {(day_id, pv_id): total} — no tour/station filter
    - "tour": {(day_id, pv_id, tour_number): total}
    - "station": {(day_id, pv_id, station_id): total}
    """
    physical_variation_ids = {
        physical_variation.id for physical_variation in physical_variations
    }
    weeks = list(delivery_weeks)
    if not physical_variation_ids or not weeks:
        return {}

    # 1. Pre-fetch all virtual components for these physical variations (1 query)
    virtual_map = _build_virtual_map(physical_variation_ids)

    all_variation_ids = physical_variation_ids | set(virtual_map.keys())

    # 2. Single aggregated query through ShareDemandService for ALL weeks.
    #    The subscription backend resolves variation_id to subscription's
    #    variation; the external CSV backend returns rows keyed by the
    #    physical variation only (so virtual_map will be a no-op).
    raw_rows = _demand_service().aggregated_rows(
        year=year,
        delivery_weeks=weeks,
        variation_ids=all_variation_ids,
        joker=False,
    )

    # 3. Build per-week result lookups, resolving virtual → physical
    per_week_basic: dict[int, dict[tuple, Decimal]] = defaultdict(
        lambda: defaultdict(Decimal)
    )
    per_week_tour: dict[int, dict[tuple, Decimal]] = defaultdict(
        lambda: defaultdict(Decimal)
    )
    per_week_station: dict[int, dict[tuple, Decimal]] = defaultdict(
        lambda: defaultdict(Decimal)
    )

    for row in raw_rows:
        week = row["delivery_week"]
        day_id = row["day_id"]
        var_id = row["variation_id"]
        tour = row["tour_number"]
        station_id = row["station_id"]
        count = row["count"]

        # Collect (physical_variation_id, weighted_count) pairs to accumulate
        targets: list[tuple[object, Decimal]] = []

        if var_id in physical_variation_ids:
            targets.append((var_id, Decimal(count)))

        if var_id in virtual_map:
            for physical_variation_id, qty in virtual_map[var_id]:
                targets.append((physical_variation_id, Decimal(count) * qty))

        for physical_variation_id, weighted in targets:
            per_week_basic[week][(day_id, physical_variation_id)] += weighted
            if tour is not None:
                per_week_tour[week][(day_id, physical_variation_id, tour)] += weighted
            if station_id is not None:
                per_week_station[week][
                    (day_id, physical_variation_id, station_id)
                ] += weighted

    return {
        week: {
            "basic": {k: round(v) for k, v in per_week_basic[week].items()},
            "tour": {k: round(v) for k, v in per_week_tour[week].items()},
            "station": {k: round(v) for k, v in per_week_station[week].items()},
        }
        for week in weeks
    }


def batch_get_physical_variation_totals_for_week(
    physical_variations: Iterable[ShareTypeVariation] | Any,
    year: int,
    delivery_week: int,
) -> dict[str, dict[tuple, int]]:
    """Single-week convenience wrapper around the multi-week batch."""
    totals = batch_get_physical_variation_totals_for_weeks(
        physical_variations, year, [delivery_week]
    )
    return totals.get(delivery_week, {"basic": {}, "tour": {}, "station": {}})
