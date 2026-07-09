"""Shared ShareContent packing base queryset builder.

Every packing / member-amount view opens its ShareContent read the same way:
the ``active.for_period`` manager scoped to a ``(year, delivery_week,
day_number)`` slot, an optional ``is_packed_bulk`` clause, and the
station-OR-tour narrowing ladder (a concrete ``delivery_station`` wins over a
resolved ``tour_station_ids`` list; passing neither is the all-stations case).
:func:`packing_share_contents` is the single source for that base + ladder so
each caller only layers on its own extra filters (share_type, variation ids,
select_related, ordering, a delivery-day probe).

The tour narrowing takes an already-resolved ``tour_station_ids`` list — callers
resolve a ``tour`` number to its station ids via
:func:`apps.commissioning.utils.delivery_utils.tour_station_ids` (the mirror of
the ``ShareDelivery`` box-derivation path).
"""

from __future__ import annotations

from django.db.models import QuerySet

from ..models import ShareContent


def packing_share_contents(
    year: int,
    week: int,
    day_number: int,
    *,
    is_past: bool,
    is_packed_bulk: bool | None = None,
    delivery_station: str | None = None,
    tour_station_ids: list[str] | None = None,
) -> QuerySet[ShareContent]:
    """Base ShareContent queryset for a packing / member-amount view.

    Applies, in order:

    - ``active.for_period(is_past=...)`` scoped to the ``(year, week,
      day_number)`` slot;
    - the ``is_packed_bulk`` variation clause (skipped when ``None``);
    - the station/tour narrowing — a concrete ``delivery_station`` wins over a
      resolved ``tour_station_ids`` list; passing neither leaves the query at
      all stations.

    Callers layer their own ``.filter(...)`` (share_type / variation ids),
    ``.select_related(...)`` / ``.values(...)`` and ordering on top; every one
    of those composes into the same to-one joins, so the emitted SQL is
    identical to the hand-built queries this replaces.
    """
    contents = ShareContent.active.for_period(is_past=is_past).filter(
        share__year=year,
        share__delivery_week=week,
        share__delivery_day__day_number=day_number,
    )
    if is_packed_bulk is not None:
        contents = contents.filter(
            share__share_type_variation__is_packed_bulk=is_packed_bulk
        )
    if delivery_station is not None:
        contents = contents.filter(delivery_station=delivery_station)
    elif tour_station_ids is not None:
        contents = contents.filter(delivery_station_id__in=tour_station_ids)
    return contents
