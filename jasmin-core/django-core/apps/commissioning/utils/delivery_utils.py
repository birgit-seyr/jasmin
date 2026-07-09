"""
Delivery-specific utility functions.
Handles SharesDeliveryDay, DeliveryStationDay, and related queries.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db.models import QuerySet
from isoweek import Week

from ..errors import SharesDeliveryDayNotFound
from ..models import (
    DeliveryStationDay,
    SharesDeliveryDay,
    ShareTypeVariation,
)


def get_shares_delivery_day_from_day_number(
    year: int, delivery_week: int, day_number: int
) -> tuple[SharesDeliveryDay, date]:
    """
    Get the active delivery day for given parameters.

    Args:
        year: Year (e.g. 2024)
        delivery_week: ISO week number (1-53)
        day_number: Day of week (0=Monday, 6=Sunday)

    Returns:
        Tuple of (shares_delivery_day, active_at_date).

    Raises:
        SharesDeliveryDayNotFound: if no active delivery day exists for the
            given day_number (HTTP 404 via ``core.exception_handler``).
    """
    week_start = Week(year, delivery_week).monday()
    active_at_date = week_start + timedelta(days=day_number)

    shares_delivery_days = SharesDeliveryDay.current.active_at_date(active_at_date)
    shares_delivery_day = shares_delivery_days.filter(day_number=day_number).first()

    if not shares_delivery_day:
        raise SharesDeliveryDayNotFound(
            "No active delivery day found for the given day_number",
            details={
                "year": year,
                "delivery_week": delivery_week,
                "day_number": day_number,
            },
        )

    return shares_delivery_day, active_at_date


def get_delivery_station_days_from_shares_delivery_day(
    shares_delivery_day: SharesDeliveryDay,
    active_at_date: date,
) -> QuerySet[DeliveryStationDay]:
    """
    Get active delivery station days for a given delivery day.

    Returns ordered queryset with prefetched relationships.

    Args:
        shares_delivery_day: The delivery day
        active_at_date: Date to check time-bound validity against

    Returns:
        QuerySet of DeliveryStationDay objects, ordered by tour and stop
    """
    return (
        DeliveryStationDay.current.active_at_date(active_at_date)
        .filter(delivery_day=shares_delivery_day)
        .select_related("delivery_station__contact")
        .order_by("tour_number", "stop_order")
    )


def tour_station_ids(
    active_at_date: date,
    *,
    delivery_day: SharesDeliveryDay | None = None,
    day_number: int | None = None,
    tour: str,
) -> list[str]:
    """Delivery-station ids on ``tour`` for a delivery day, at ``active_at_date``.

    Resolves the active :class:`DeliveryStationDay` rows on the given tour and
    returns their ``delivery_station_id`` values — the set a packing / amount
    view narrows ShareContent down to when scoped to a single tour.

    Identify the delivery day EITHER by object
    (``delivery_day=<SharesDeliveryDay>``, which may be ``None`` to match rows
    with a NULL delivery day) OR by its ``day_number`` (``day_number=<0..6>``).
    When ``day_number`` is given it wins.
    """
    if day_number is not None:
        day_filter = {"delivery_day__day_number": day_number}
    else:
        day_filter = {"delivery_day": delivery_day}
    return list(
        DeliveryStationDay.current.active_at_date(active_at_date)
        .filter(tour_number=tour, **day_filter)
        .values_list("delivery_station_id", flat=True)
    )


def get_active_share_type_variations(
    year: int,
    delivery_week: int,
    shares_delivery_day: SharesDeliveryDay,
    delivery_station_days: QuerySet[DeliveryStationDay],
) -> QuerySet[ShareTypeVariation]:
    """
    Get all share type variations that have deliveries for this week/day.

    Only returns variations that:
    - Have actual deliveries (not just subscriptions)
    - Are not joker deliveries
    - Are for the specified week/day

    Args:
        year: Year
        delivery_week: ISO week number
        shares_delivery_day: The delivery day
        delivery_station_days: Station days to filter by

    Returns:
        QuerySet of ShareTypeVariation objects with share_type prefetched

    Example:
        >>> variations = get_active_share_type_variations(2024, 10, shares_delivery_day, delivery_station_days)
        >>> for var in variations:
        ...     print(f"{var.share_type.name} - {var.size}")
    """
    station_day_ids = list(delivery_station_days.values_list("id", flat=True))
    # Local import: utils is loaded before services, so importing
    # ShareDemandService at module top would cause a circular import.
    from ..services.share_demand_service import ShareDemandService

    rows = ShareDemandService.aggregated_rows(
        year=year,
        delivery_week=delivery_week,
        delivery_day_id=shares_delivery_day.id,
        joker=False,
    )
    variation_ids = {
        r["variation_id"]
        for r in rows
        if r["variation_id"] is not None
        and (not station_day_ids or r["station_day_id"] in station_day_ids)
    }

    return (
        ShareTypeVariation.objects.filter(id__in=variation_ids)
        .select_related("share_type")
        .order_by("share_type__name", "size")
    )
